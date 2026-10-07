"""Evidence-only drafting. Files/cache/decoding stay on the caller thread."""

from dataclasses import asdict, replace
from datetime import date
import hashlib
import json
import re
import time

import anthropic

from app import monthly_report_library as library
from app.api_retry import OPERATION_BUDGET_SECONDS, complete_response_text, request_with_retry
from app.config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL
from app.monthly_report_content_policy import contains_price
from app.monthly_report_model import EvidenceFact, DraftParagraph, ResolvedBlock
from app.monthly_report_prompts import EXTRACT_PROMPT, DRAFT_PROMPT, PROMPT_VERSION
from app.monthly_report_sources import source_reference

MAX_EVIDENCE_CHARS = 60_000
MAX_COMPACT_CHARS = 60_000
MAX_CALLS = 80  # Shared per profile/month, including retries requested by a user.
BLOCK_KINDS = {
    "activity_summary": {"action", "finding", "reading"},
    "improvements": {"improvement", "action"},
    "equipment_issues": {"issue", "finding", "recommendation", "follow_up", "reading"},
    "training_summary": {"training"}, "work_orders": {"action", "finding"},
    "proposals": {"proposal", "follow_up", "recommendation"},
}
FACT_KINDS = set.union(*BLOCK_KINDS.values())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def clean_text(text):
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[contact omitted]", str(text))
    return re.sub(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)", "[contact omitted]", text).strip()


def numbers(text):
    return set(re.findall(r"(?<!\w)\d+(?:[.,]\d+)*(?!\w)", text))


def vendor_names(draft):
    """Only explicit vendor columns establish preferred spelling."""
    names = []
    specs = {b.key: b for s in draft.sections for b in s.blocks}
    for block in draft.blocks:
        if block.key != "subcontractor_matrix":
            continue
        tables = [(tuple(c.title for c in specs[block.key].columns), block.rows)] if block.key in specs else []
        tables += [(t.columns, t.rows) for t in block.extra_tables]
        for columns, rows in tables:
            indices = [i for i, c in enumerate(columns) if re.search(r"\b(?:vendor|company|contractor)\b", c, re.I)]
            names += [r[i].strip() for r in rows for i in indices if i < len(r) and r[i].strip()]
    return tuple(dict.fromkeys(names))


def request_json(content):
    """Network worker: no Streamlit, filesystem, image, PDF or cache operations."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("The document reader is not configured. Continue with entered text.")
    until = time.monotonic() + OPERATION_BUDGET_SECONDS
    with anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=0) as client:
        message = request_with_retry(lambda timeout: client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=8000, timeout=timeout,
            messages=[{"role": "user", "content": content}],
        ), until=until)
    raw = complete_response_text(message)
    if len(raw) > 100_000:
        raise ValueError("The reading exceeded its response budget; use fewer pages.")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("The reader did not return the required JSON object.")
    return value


def cache_path(profile, kind, key):
    if not re.fullmatch(r"[a-z_]+", kind) or not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("Invalid drafting cache identity.")
    return library._profile_path(profile.contract, profile.key) / "ai" / kind / (key + ".json")


def cached(profile, kind, key):
    path = cache_path(profile, kind, key)
    return library._read(path)["result"] if path.exists() else None


def save_cache(profile, kind, key, result):
    library._atomic_write(cache_path(profile, kind, key), library._json({"schema": 1, "result": result}))


def reserve_call(profile, period):
    root = library._profile_path(profile.contract, profile.key) / "ai" / "budgets"
    with library._locked(root):
        path = root / (period.key + ".json")
        value = library._read(path) if path.exists() else {"schema": 1, "calls": 0}
        if value["calls"] >= MAX_CALLS:
            raise ValueError("This report/month's 80-request drafting allowance is used. Cached results and manual editing remain available; no content was discarded.")
        value["calls"] += 1
        library._atomic_write(path, library._json(value))


def extraction_request(source, pages):
    pages = tuple(dict.fromkeys(pages))
    if not pages or any(type(n) is not int or not 1 <= n <= len(source.page_texts) for n in pages):
        raise ValueError("Choose real source pages to read.")
    evidence = [{"page": n, "text": source.page_texts[n-1]} for n in pages]
    if sum(len(p["text"]) for p in evidence) > MAX_EVIDENCE_CHARS:
        raise ValueError("These pages exceed 60,000 characters. Choose fewer pages; the remaining pages are preserved.")
    if not any(p["text"].strip() for p in evidence):
        raise ValueError("No readable text yet. Read an image page or enter its facts first.")
    key = digest((PROMPT_VERSION, source.sha256, evidence))
    return key, [{"type": "text", "text": EXTRACT_PROMPT + "\n" + json.dumps({"source_id": source.id, "pages": evidence})}]


def normalize_facts(value, source, pages, profile, period, vendors=()):
    raw = value.get("facts")
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Invalid fact list. No existing facts were changed.")
    result = []
    for item in raw:
        if not isinstance(item, dict) or type(item.get("page")) is not int or item["page"] not in pages:
            raise ValueError("A fact cited a page that was not read. No facts were accepted.")
        page = item["page"]
        kind = item.get("kind")
        text, quote = clean_text(item.get("text", "")), str(item.get("quote", "")).strip()
        if kind not in FACT_KINDS or not text or len(text) > 2000 or not quote or len(quote) > 4000:
            raise ValueError("A fact was incomplete or exceeded its bounds. No facts were accepted.")
        native = " ".join(source.page_texts[page-1].split()).casefold()
        if " ".join(quote.split()).casefold() not in native:
            raise ValueError("A fact's evidence quote was not found on its page. Review the source manually.")
        if contains_price(text) or numbers(text) - numbers(quote):
            raise ValueError("A suggested fact included pricing or unsupported numbers. No facts were accepted.")
        flags = []
        when = str(item.get("date") or "")
        if when:
            try:
                parsed = date.fromisoformat(when)
            except ValueError:
                when = ""
                flags.append("Date could not be verified")
            else:
                if not period.start <= parsed <= period.end:
                    flags.append("Outside the reporting month")
        site = clean_text(item.get("facility", ""))
        sites = {n.casefold(): f.title for f in profile.facilities for n in (f.title, *f.aliases)}
        if site and site.casefold() not in sites:
            flags.append("Facility does not match the confirmed report sites")
        site = sites.get(site.casefold(), site)
        vendor = clean_text(item.get("vendor", ""))
        vendor = next((v for v in vendors if v.casefold() == vendor.casefold()), vendor)
        tags = item.get("tags", [])
        if not isinstance(tags, list) or len(tags) > 50 or any(not isinstance(t, str) or len(t) > 80 for t in tags):
            raise ValueError("Invalid equipment tag list.")
        known = {t.casefold(): t for t in profile.asset_tags}
        tags = tuple(known.get(t.casefold(), t) for t in tags)
        if any(t.casefold() not in known for t in tags):
            flags.append("Equipment tag is not in this site's confirmed asset list")
        if item.get("uncertain"):
            flags.append("Reader marked this fact uncertain")
        status = str(item.get("status") or "")
        if status not in ("", "ongoing", "updated", "resolved"):
            flags.append("Issue status is unclear")
            status = "ongoing"
        identity = "fact-" + digest((source.sha256, page, kind, text, quote))[:20]
        result.append(EvidenceFact(identity, source.id, page, kind, text, clean_text(quote), when, site, vendor, tags, status, tuple(flags)))
    return tuple(dict((f.id, f) for f in result).values())


def evidence_fingerprint(sources, references):
    wanted = set(references)
    records = []
    for source in sources:
        refs = [source_reference(source, n) for n in range(1, len(source.page_texts)+1)]
        if wanted.intersection(refs):
            # Captions, selected pages, corrected text and reviewed fact edits all
            # invalidate a draft review, even when its visible words are unchanged.
            records.append((source.id, source.fingerprint))
            wanted.difference_update(refs)
    return "" if wanted else digest(records)


def drafting_request(block_key, sources, period, vendors=(), tags=(), instruction=""):
    if block_key not in BLOCK_KINDS or len(instruction) > 2000:
        raise ValueError("Choose a supported narrative and keep redrafting notes under 2,000 characters.")
    facts = tuple(f for s in sources for f in s.facts if f.kind in BLOCK_KINDS[block_key])
    if not facts:
        raise ValueError("No extracted facts for this section yet. Read sources or add Copilot notes first.")
    payload = {"block": block_key, "period": period.key, "vendors": vendors, "known_tags": tags,
               "facts": [asdict(f) for f in facts], "redrafting_notes": instruction}
    encoded = json.dumps(payload)
    if len(encoded) > MAX_COMPACT_CHARS:
        raise ValueError("This draft exceeds 60,000 characters of compact evidence. Select fewer sources; nothing was removed.")
    key = digest((PROMPT_VERSION, payload))
    return key, [{"type": "text", "text": DRAFT_PROMPT + "\n" + encoded}], facts


def normalize_draft(value, key, facts, sources):
    raw = value.get("paragraphs")
    if not isinstance(raw, list) or len(raw) > 60:
        raise ValueError("Invalid paragraph list. Your current narrative was preserved.")
    by_id = {f.id: f for f in facts}
    source_map = {s.id: s for s in sources}
    paragraphs = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Invalid draft paragraph.")
        ids = item.get("fact_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in by_id for i in ids):
            raise ValueError("A draft cited nonexistent evidence. Your narrative was preserved.")
        cited = [by_id[i] for i in ids]
        if any(f.source_id not in source_map or not 1 <= f.page <= len(source_map[f.source_id].page_texts) for f in cited):
            raise ValueError("A draft cited a missing source or page.")
        refs = tuple(dict.fromkeys(source_reference(source_map[f.source_id], f.page) for f in cited))
        text = clean_text(item.get("text", ""))
        if not text or len(text) > 2000 or contains_price(text):
            raise ValueError("A draft included prices or invalid text. Your narrative was preserved.")
        flags = list(dict.fromkeys(flag for f in cited for flag in f.flags))
        if numbers(text) - numbers(" ".join(f.text + " " + f.quote for f in cited)):
            flags.append("Unsupported number: edit this paragraph against its evidence")
        if item.get("uncertain"):
            flags.append("Model marked this paragraph uncertain")
        paragraphs.append(DraftParagraph(text, tuple(ids), refs, tuple(flags)))
    references = tuple(dict.fromkeys(r for p in paragraphs for r in p.references))
    return ResolvedBlock(key, "This month", text="\n".join("- " + p.text for p in paragraphs),
                         references=references, ai_written=True, ai_paragraphs=tuple(paragraphs),
                         ai_evidence_fingerprint=evidence_fingerprint(sources, references))


def reviewed_block(block, sources):
    if not block.ai_evidence_fingerprint or block.ai_evidence_fingerprint != evidence_fingerprint(sources, block.references):
        raise ValueError("Evidence changed. Redraft or compare and refresh the source links before review.")
    if any("Unsupported number" in f for p in block.ai_paragraphs for f in p.flags):
        raise ValueError("Correct unsupported numerical statements before review.")
    return replace(block, reviewed_fingerprint=block.fingerprint)
