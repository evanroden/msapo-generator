"""Bounded, evidence-first full-document reading for optional Monthly fact suggestions.

Only explicit user actions invoke the reader. Original sources, manual edits and
review decisions are never changed by planning, network work or validation.
Model replies are untrusted and remain suggestions until source review.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import BoundedSemaphore
from dataclasses import dataclass
import hashlib
import json
import re
import time

from app.monthly_report_prompts import EXTRACT_PROMPT, PROMPT_VERSION

MAX_REGION_CHARS = 20_000
MAX_BATCH_CHARS = 48_000
MAX_BATCH_REGIONS = 20
MAX_REGION_LINES = 40
MAX_BATCH_CANDIDATE_LINES = 80
MAX_VISUALS_PER_BATCH = 1
MAX_PARALLEL_READS = 2
VERSION = "monthly-full-coverage-v1"
_MODEL_SLOTS = BoundedSemaphore(MAX_PARALLEL_READS)

# The extra receipt is deliberately not part of the old single-call prompt.
# An absent receipt is incomplete coverage, NOT an empty, successful page.
COVERAGE_PROMPT = EXTRACT_PROMPT + """
For this batch return one strict JSON object with:
{"reviewed_regions":["1.1"],"unsupported_regions":[],
 "facts":[{"source":"source id","region":"1.1","page":1,
 "kind":"finding","text":"...","quote":"exact original text", "uncertain":false}]}
Candidate kind hints are search aids only, not source facts. If 100 facts cannot\ncover a region, mark it unsupported with a reason rather than omitting it.\nEvery region ID supplied must occur exactly once in reviewed_regions or
unsupported_regions (objects with region and a nonempty reason). A region with
no relevant facts still belongs in reviewed_regions if fully inspected.
Cite the exact source ID, region ID and original page for EACH fact. The quote
must be an exact contiguous excerpt from that region's native text. Do not
transcribe visual-only material into verified text facts; images without native
evidence must remain for human verification. Never turn plans, estimates,
recommendations or unfinished vendor work into completed ENFRA work.
No personal contact details, pricing or commercial terms in any fact.
"""


@dataclass(frozen=True)
class Region:
    identity: str
    page: int
    text: str
    visual: bool


@dataclass(frozen=True)
class Batch:
    key: str
    regions: tuple[Region, ...]

    @property
    def pages(self):
        return tuple(dict.fromkeys(r.page for r in self.regions))


@dataclass(frozen=True)
class Plan:
    source_id: str
    source_fingerprint: str
    pages: tuple[int, ...]
    batches: tuple[Batch, ...]
    empty_pages: tuple[int, ...]


def _digest(parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def plan(source, pages=None, *, model=None):
    """Deterministic lossless segmentation; every selected page is inventoried.

    A 60k+ native page is split into disjoint regions *without dropping bytes*.
    Visual-needed pages are isolated to avoid losing safe sibling pages if an
    image cannot be prepared. No paid request or I/O occurs here.
    """
    if model is None:
        from app import monthly_report_ai as ai
        model = ai.ANTHROPIC_MODEL
    requested = tuple(range(1, len(source.page_texts) + 1) if pages is None else pages)
    if not requested or any(type(n) is not int or n < 1 or n > len(source.page_texts)
                            for n in requested):
        raise ValueError("Choose real source pages to read.")
    selected = tuple(dict.fromkeys(requested))
    batches, current, size, lines, empty = [], [], 0, 0, []

    def flush():
        nonlocal current, size, lines
        if current:
            signature = [(r.identity, r.page, r.text, r.visual) for r in current]
            key = _digest((VERSION, PROMPT_VERSION, model, "facts",
                           source.id, source.sha256, signature))
            batches.append(Batch(key, tuple(current)))
        current, size, lines = [], 0, 0

    needs_vision = set(source.needs_vision)
    for number in selected:
        native = source.page_texts[number - 1]
        visual = number in needs_vision
        if not native and not visual:
            empty.append(number)
            continue
        # Preserve complete spreadsheet rows and paragraph lines where feasible.
        # Oversized single lines are split without deleting a character.
        pieces = []
        if native:
            current_piece = ""
            piece_lines = 0
            for line in native.splitlines(keepends=True):
                if piece_lines >= MAX_REGION_LINES and current_piece:
                    pieces.append(current_piece)
                    current_piece, piece_lines = "", 0
                while line:
                    room = MAX_REGION_CHARS - len(current_piece)
                    if not room:
                        pieces.append(current_piece)
                        current_piece = ""
                        room = MAX_REGION_CHARS
                    if len(line) <= room:
                        current_piece += line
                        piece_lines += bool(line.strip())
                        line = ""
                    else:
                        if current_piece:
                            pieces.append(current_piece)
                            current_piece = ""
                        else:
                            pieces.append(line[:MAX_REGION_CHARS])
                            line = line[MAX_REGION_CHARS:]
            if current_piece:
                pieces.append(current_piece)
        else:
            pieces = [""]
        for part, text in enumerate(pieces, 1):
            region = Region(f"{number}.{part}", number, text, visual)
            if (current and (visual or current[0].visual
                    or len(current) >= MAX_BATCH_REGIONS
                    or size + len(text) > MAX_BATCH_CHARS
                    or lines + _candidate_line_count(text) > MAX_BATCH_CANDIDATE_LINES)):
                flush()
            current.append(region)
            size += len(text)
            lines += _candidate_line_count(text)
            if visual:
                flush()
    flush()
    return Plan(source.id, source.fingerprint, selected, tuple(batches), tuple(empty))


def _candidate_line_count(text):
    return max(1, sum(bool(line.strip()) for line in text.splitlines()))


def _candidate_kinds(text):
    """Cheap, advisory native discovery. No extracted field comes from a hint."""
    candidates = {
        "action": ("replaced", "repaired", "performed", "completed",
                   "inspected", "serviced"),
        "reading": ("psi", "gpm", "temperature", "conductivity", "measured"),
        "training": ("training", "attendees", "instructor"),
        "follow_up": ("scheduled", "pending", "awaiting", "follow-up"),
        "recommendation": ("recommended", "recommendation", "proposed"),
        "issue": ("issue", "fault", "failure", "leak", "outage"),
    }
    lower = text.casefold()
    return [kind for kind, words in candidates.items()
            if any(word in lower for word in words)]


def _payload(batch, source):
    regions = [{"id": r.identity, "page": r.page, "text": r.text,
                "candidate_kinds": _candidate_kinds(r.text)}
               for r in batch.regions]
    return [{"type": "text", "text": COVERAGE_PROMPT + "\n" +
             json.dumps({"source_id": source.id, "regions": regions},
                        ensure_ascii=False)}]


def prepare_batch(batch, content, profile):
    """UI-thread-only image preparation, bounded to one visual per request."""
    from app import monthly_report_sources as sources
    from app.monthly_report_structured_uploads import reserve_bulk_image
    from app.ocr import image_blocks_for_vision

    payload = _payload(batch, content.source)
    for region in batch.regions:
        if not region.visual:
            continue
        if region.page not in sources.image_numbers(content):
            raise ValueError("This source page has no available image for visual reading.")
        image = sources.page_image(profile, content, region.page, preview=True)
        reserve_bulk_image(profile, content.source.sha256, image.data)
        payload.append({"type": "text", "text":
                        f"VISUAL EVIDENCE SOURCE {content.source.id} PAGE {region.page} "
                        f"SHA256 {hashlib.sha256(image.data).hexdigest()}. "
                        "Image is unverified until human review; do not fabricate native quotes."})
        payload.extend(image_blocks_for_vision(image.data, "." + image.extension))
    return payload


def prepare_run(plan_value, content, profile, period, *, ai_module=None):
    """Read valid caches first, charge once per *admitted* uncached request.

    Quota exhaustion or an unavailable image is a page-level pending receipt:
    previously admitted source siblings and cached evidence are retained.
    """
    from app import monthly_report_ai as ai
    ai = ai_module or ai
    cached, requests, unavailable = [], [], []
    exhausted = False
    for batch in plan_value.batches:
        try:
            saved = ai.cached(profile, "full_coverage", batch.key)
            if saved is not None:
                # An old/poisoned cache is never authority to mark pages done.
                _, rejected, _, _ = validate_batch(batch, saved, content.source, profile, period, ai_module=ai)
                if rejected:
                    raise ValueError("Cached reader claims require fresh verification.")
                cached.append((batch.key, saved))
                continue
        except (ValueError, TypeError, KeyError, OSError):
            pass
        if exhausted:
            unavailable.append((batch.key, "Monthly reader allowance exhausted"))
            continue
        try:
            payload = prepare_batch(batch, content, profile)
        except (ValueError, OSError, RuntimeError) as exc:
            unavailable.append((batch.key, "Visual reading requires manual review: " + str(exc)))
            continue
        try:
            ai.reserve_call(profile, period)
        except ValueError as exc:
            exhausted = True
            unavailable.append((batch.key, str(exc)))
            continue
        requests.append((batch.key, payload))
    return {"cached": tuple(cached), "requests": tuple(requests),
            "unavailable": tuple(unavailable)}


def join_prepared(prepared_runs):
    """Combine independent source plans into one bounded model worker.

    Keys include source IDs, so a different file cannot inherit evidence
    or a cached reply from an unrelated source.
    """
    return {
        field: tuple(item for part in prepared_runs for item in part[field])
        for field in ("cached", "requests", "unavailable")
    }


def run(prepared, *, read=None):
    """Network-only work, bounded to two in-flight provider calls.

    Partial failures are receipts, not successful empty JSON. Do not touch
    Streamlit, files, the source object or provider routing in worker threads.
    """
    from app.monthly_report_ai import request_json
    reader = read or request_json
    answers = {}
    first_ready = None
    started = time.monotonic()
    tasks = prepared["requests"]
    def limited_read(payload):
        with _MODEL_SLOTS:  # Global per-process cap, also across concurrent sessions.
            return reader(payload)

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_READS,
                            thread_name_prefix="monthly-cover") as executor:
        futures = {executor.submit(limited_read, payload): key for key, payload in tasks}
        for future in as_completed(futures):
            key = futures[future]
            seconds = time.monotonic() - started
            try:
                value = future.result()
                answers[key] = (value, "", seconds)
                if first_ready is None:
                    first_ready = seconds
            except Exception as exc:
                # No exception text containing uploaded source/prompt is exposed.
                answers[key] = (None, type(exc).__name__, seconds)
    return {"cached": prepared["cached"],
            "responses": tuple((key, *answers[key]) for key, _ in tasks),
            "unavailable": prepared["unavailable"],
            "first_response_seconds": first_ready,
            "total_seconds": time.monotonic() - started}


def _token(text):
    return " ".join(str(text).casefold().split())


def validate_batch(batch, value, source, profile, period, *, ai_module=None):
    """Fail closed on incomplete region inventory and ungrounded fields.

    Invalid individual claims are counted, never promoted to facts. A batch
    containing an invalid claim is marked 'needs review' rather than silently
    claiming every page was classified successfully.
    """
    from app import monthly_report_ai as ai
    from app.monthly_report_structured_uploads import _activity_text
    ai = ai_module or ai
    if not isinstance(value, dict) or not isinstance(value.get("facts"), list):
        raise ValueError("Reader returned no structured facts receipt.")
    if len(value["facts"]) > 100:
        raise ValueError("Reader exceeded the fact limit.")
    expected = {r.identity: r for r in batch.regions}
    reviewed = value.get("reviewed_regions")
    unsupported = value.get("unsupported_regions")
    if (not isinstance(reviewed, list) or not isinstance(unsupported, list)
            or any(not isinstance(r, str) for r in reviewed)
            or any(not isinstance(r, dict) or not isinstance(r.get("region"), str)
                   or not isinstance(r.get("reason"), str) or not r["reason"].strip()
                   for r in unsupported)):
        raise ValueError("Reader omitted its region coverage receipt.")
    unsupported_ids = [r["region"] for r in unsupported]
    if (len(reviewed) != len(set(reviewed))
            or len(unsupported_ids) != len(set(unsupported_ids))
            or set(reviewed) & set(unsupported_ids)
            or set(reviewed) | set(unsupported_ids) != set(expected)):
        raise ValueError("Reader did not account for every original region.")
    facts, rejected = [], 0
    rejected_regions, accepted_regions = set(), set()

    def reject(bad_region):
        nonlocal rejected
        rejected += 1
        if bad_region is not None:
            rejected_regions.add(bad_region.identity)
    for raw in value["facts"]:
        if not isinstance(raw, dict):
            reject(None)
            continue
        region = expected.get(raw.get("region"))
        if (region is None or region.identity not in reviewed
                or raw.get("source") != source.id
                or type(raw.get("page")) is not int or raw["page"] != region.page
                or not isinstance(raw.get("quote"), str)
                or not raw["quote"] or raw["quote"] not in region.text):
            reject(region)
            continue
        if (any(raw.get(field) and _token(raw[field]) not in _token(raw["quote"])
                for field in ("vendor", "facility"))
                or any(not isinstance(t, str) or _token(t) not in _token(raw["quote"])
                       for t in raw.get("tags", ()) if isinstance(raw.get("tags", ()), list))
                or raw.get("date") and not ai._date_supported(raw["quote"], raw["date"])):
            reject(region)
            continue
        if any(
                _activity_text(raw.get(field, "")) != raw.get(field, "").strip()
                for field in ("text", "quote")
                if isinstance(raw.get(field), str)
        ) or any(
                phrase in _token(raw.get("quote", ""))
                for phrase in ("terms and conditions", "indemnification",
                               "limitation of liability", "governing law",
                               "payment terms", "net 30", "net 60")
        ):
            reject(region)
            continue
        quoted, claimed = _token(raw.get("quote", "")), _token(raw.get("text", ""))
        # A negative/pending source must not become a positive maintenance or
        # training completion. Failing closed also avoids attribution of a
        # vendor visit to an ENFRA technician on a different employer's report.
        conditional = re.search(
            r"\b(?:did not|was not|were not|not yet|has not|had not|"
            r"could not|would not|scheduled|pending|planned|proposed|"
            r"awaiting|to be performed|not started)\b", quoted)
        if (conditional and not re.search(
                r"\b(?:did not|was not|were not|not yet|has not|had not|"
                r"could not|would not|scheduled|pending|planned|proposed|"
                r"awaiting|to be performed|not started)\b", claimed)
                or "enfra" in claimed and "enfra" not in quoted):
            reject(region)
            continue
        if raw.get("kind") == "action" and any(
                stem in _token(raw.get("text", ""))
                and stem not in _token(raw.get("quote", ""))
                for stem in ("replac", "repair", "complet", "perform",
                             "resolv", "instal", "finish", "restor")
        ):
            reject(region)
            continue
        if raw.get("kind") == "action" and any(
                word in _token(raw["quote"])
                for word in ("scheduled", "pending", "not started", "did not",
                             "would not", "planned", "proposed", "awaiting")
        ) and any(word in _token(raw.get("text", "")) for word in
                  ("completed", "repaired", "replaced", "performed", "finished",
                   "installed", "resolved")):
            reject(region)
            continue
        try:
            validated = ai.normalize_facts(
                {"facts": [raw]}, source, (region.page,), profile, period)
        except (ValueError, TypeError, KeyError):
            reject(region)
            continue
        if any(flag != "Reader marked this fact uncertain"
               for fact in validated for flag in fact.flags):
            reject(region)
            continue
        facts.extend(validated)
        accepted_regions.add(region.identity)
    return (tuple(dict((fact.id, fact) for fact in facts).values()),
            rejected, rejected_regions, accepted_regions)


def collect(plan_value, result, source, profile, period, *, ai_module=None):
    """Canonical source/page/quote facts with honest 100%-accounted inventory.

    A 'ready' page has all regions verified; a visual-only page remains manual
    review even when its image was delivered to the model.
    """
    from app import monthly_report_ai as ai
    ai = ai_module or ai
    own_keys = {batch.key for batch in plan_value.batches}
    returned = {key: (value, error) for key, value, error, _ in result["responses"]}
    returned.update((key, (value, "")) for key, value in result["cached"])
    missing = dict(result["unavailable"])
    region_status = {}
    facts, good, bad, invalid, cacheable = {}, 0, 0, 0, []
    for batch in plan_value.batches:
        rejected_regions, accepted_regions = set(), set()
        if batch.key in missing:
            status = "needs_review"
        elif batch.key not in returned or returned[batch.key][1]:
            status = "retry"
        else:
            try:
                value = returned[batch.key][0]
                batch_facts, rejected, rejected_regions, accepted_regions = validate_batch(
                    batch, value, source, profile, period, ai_module=ai)
                invalid += rejected
                status = "needs_review" if rejected else "ready"
                for fact in batch_facts:
                    facts[fact.id] = fact
                if batch.key not in {key for key, _ in result["cached"]} and not rejected:
                    cacheable.append((batch.key, value))
                good += not bool(rejected)
                bad += bool(rejected)
            except (ValueError, TypeError, KeyError):
                status = "retry"
        for region in batch.regions:
            # A rejected claim taints only its own region. A sibling region
            # that produced a verified fact stays ready even when its batch
            # also carried a rejected claim; a region with no verified fact
            # in a tainted batch stays needs_review with the batch.
            if region.identity in rejected_regions:
                own = "needs_review"
            elif region.identity in accepted_regions:
                own = "ready"
            else:
                own = status
            own = "visual_review" if region.visual and own == "ready" else own
            region_status.setdefault(region.page, []).append(own)
    inventory = {}
    for number in plan_value.pages:
        statuses = region_status.get(number, [])
        if number in plan_value.empty_pages:
            inventory[number] = "needs_review"  # Native blank != confirmed blank.
        elif not statuses:
            inventory[number] = "needs_review"
        elif all(status == "ready" for status in statuses):
            inventory[number] = "ready"
        elif "retry" in statuses:
            inventory[number] = "retry"
        elif "visual_review" in statuses:
            inventory[number] = "visual_review"
        else:
            inventory[number] = "needs_review"
    return {"facts": tuple(facts.values()), "inventory": inventory,
            "valid_batches": good, "review_batches": bad,
            "admitted_calls": sum(key in own_keys for key, *_ in result["responses"]),
            "cache_hits": sum(key in own_keys for key, _ in result["cached"]),
            "rejected_claims": invalid, "cacheable": tuple(cacheable),
            "unavailable": result["unavailable"],
            "first_response_seconds": result["first_response_seconds"],
            "total_seconds": result["total_seconds"]}
