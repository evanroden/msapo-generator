"""Report-only period decisions for individual, directly typed narrative items.

Original source bytes/dates and standing/history data are never edited here.
Receipts bind the target month and exact exported wording/evidence; they cannot
approve a different item, an AI claim, a picture, or the carried-block gate.
"""
from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
import json
import re

from app.monthly_report_asset_review import preserve_asset_reviews
from app.monthly_report_checks import stale_period_mentions, _MONTH_RE, _MONTHS, _DATE_RE
from app.monthly_report_content_policy import contains_price

PREFIX = "period-item:v1:"
HISTORICAL = "Historical context: "


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _record(value):
    return PREFIX + urlsafe_b64encode(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).decode()


def decisions(block, period):
    result = []
    for reference in block.references:
        if not reference.startswith(PREFIX):
            continue
        try:
            value = json.loads(urlsafe_b64decode(reference[len(PREFIX):]))
        except (ValueError, TypeError, UnicodeError):
            continue
        if isinstance(value, dict) and value.get("period") == period.key:
            result.append(value)
    return tuple(result)


def _manual(block):
    return block.source != "Omit" and not block.ai_written and not block.ai_paragraphs


def _evidence(block, sources):
    references = tuple(r for r in block.references if not r.startswith(PREFIX))
    identifiers = {r.split(":", 1)[0] for r in references}
    return _digest((references, tuple((s.id, s.fingerprint) for s in sources if s.id in identifiers)))


def historical_allowed(text, period):
    """Only earlier items; mixed current/future and invalid dates need editing."""
    if not stale_period_mentions(text, period.year, period.month) or contains_price(text):
        return False
    # Scan ALL dates, including current/future follow-ups that don't warn. A
    # mixed line must be split/edited, not collectively relabeled historical.
    for numeric in _DATE_RE.finditer(text):
        parts = numeric.groups()
        year, month, day = parts[:3] if parts[0] else (parts[5], parts[3], parts[4])
        try:
            observed = date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
        except ValueError:
            return False
        if observed >= period.start:
            return False
    for named in _MONTH_RE.finditer(text):
        if named[1] in ("may", "march") and not re.search(r"\d", named[0]):
            continue
        year, month = int(named[2]) if named[2] else period.year, _MONTHS[named[1].casefold()]
        if (year, month) >= (period.year, period.month):
            return False
        day = re.search(r"\s+(\d{1,2})(?!\d)", named[0])
        if day:
            try:
                date(year, month, int(day[1]))
            except ValueError:
                return False
    return True


def is_historical(block, text, period, sources=()):
    if not _manual(block) or not text.startswith(HISTORICAL) or not historical_allowed(text, period):
        return False
    evidence = _evidence(block, sources)
    return any(value.get("action") == "historical" and value.get("text") == _digest(text)
               and value.get("evidence") == evidence for value in decisions(block, period))


@dataclass(frozen=True)
class PeriodItem:
    index: int
    text: str
    mentions: tuple[str, ...]
    historical_allowed: bool


def pending_items(block, period, sources=()):
    if not _manual(block):
        return ()
    return tuple(PeriodItem(index, line, mentions, historical_allowed(line, period))
                 for index, line in enumerate(block.text.splitlines())
                 if (mentions := stale_period_mentions(line, period.year, period.month))
                 and not is_historical(block, line, period, sources))


def unresolved_mentions(block, period, sources=()):
    if not _manual(block):
        return stale_period_mentions(block.text, period.year, period.month)
    return tuple(dict.fromkeys(mention for item in pending_items(block, period, sources) for mention in item.mentions))


def item_sources(block, item, sources):
    """Exact supported lineage only; unrelated filename/date guesses are absent."""
    cited = {(parts[0], int(parts[1])) for r in block.references
             if not r.startswith(PREFIX) and len(parts := r.split(":")) == 3 and parts[1].isdigit()}
    labels = []
    for source in sources:
        for number, text in enumerate(source.page_texts, 1):
            if (source.id, number) not in cited:
                continue
            wording = item.text.removeprefix(HISTORICAL).lstrip("-• ")
            if wording and " ".join(wording.split()).casefold() in " ".join(text.split()).casefold():
                labels.append(f"{source.filename} · page/item {number}")
    return tuple(labels)


def resolve_item(block, period, index, action, *, expected_fingerprint, sources=()):
    if block.fingerprint != expected_fingerprint:
        raise ValueError("This wording changed. Check the current item before choosing again.")
    item = next((item for item in pending_items(block, period, sources) if item.index == index), None)
    if item is None:
        raise ValueError("This item is no longer awaiting a period decision.")
    lines = block.text.splitlines(keepends=True)
    record = {"period": period.key, "action": action}
    if action == "historical":
        if not item.historical_allowed:
            raise ValueError("Correct invalid, future or priced wording before retaining historical context.")
        exported = HISTORICAL + item.text.removeprefix(HISTORICAL)
        ending = lines[index][len(item.text):]
        lines[index] = exported + ending
        record.update(text=_digest(exported), evidence=_evidence(block, sources))
    elif action == "exclude":
        del lines[index]
        # Retain the exact removed wording only in this draft's receipt so a
        # repeated upload cannot silently restore it and an explicit Undo works.
        record.update(text=item.text, remaining=sum(line.rstrip("\r\n") == item.text for line in lines))
    else:
        raise ValueError("Choose a supported item operation.")
    reference = _record(record)
    updated = replace(block, text="".join(lines), references=tuple(dict.fromkeys((*block.references, reference))),
                      reviewed_fingerprint="", client_reviewed_fingerprint="")
    return preserve_asset_reviews(block, updated)


def exclusions(block, period):
    # Most recent deliberate removal owns the allowed count for that exact text.
    records = {}
    for value in decisions(block, period):
        if value.get("action") == "exclude" and isinstance(value.get("text"), str) and type(value.get("remaining")) is int and value["remaining"] >= 0:
            records[value["text"]] = value
    return tuple(records.values())


def apply_exclusions(block, period):
    """Reconcile repeat imports only in the same report month and manual model."""
    if not _manual(block):
        return block
    limits = {value["text"]: value["remaining"] for value in exclusions(block, period)}
    counts, kept = {}, []
    for line in block.text.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        counts[text] = counts.get(text, 0) + 1
        if text not in limits or counts[text] <= limits[text]:
            kept.append(line)
    text = "".join(kept)
    return block if text == block.text else preserve_asset_reviews(block, replace(block, text=text,
                    reviewed_fingerprint="", client_reviewed_fingerprint=""))


def restore_excluded(block, period, text, *, expected_fingerprint):
    if block.fingerprint != expected_fingerprint:
        raise ValueError("This wording changed. Check the current item before restoring it.")
    if not _manual(block) or text not in {value["text"] for value in exclusions(block, period)}:
        raise ValueError("This item is not excluded from this report.")
    removed = {_record(value) for value in decisions(block, period)
               if value.get("action") == "exclude" and value.get("text") == text}
    current_count = sum(line == text for line in block.text.splitlines())
    allowed = next(value["remaining"] for value in exclusions(block, period) if value["text"] == text)
    restored = block.text
    if current_count <= allowed:
        restored = "\n".join(filter(None, (block.text.rstrip("\r\n"), text)))
    return preserve_asset_reviews(block, replace(block, text=restored,
        references=tuple(ref for ref in block.references if ref not in removed),
        reviewed_fingerprint="", client_reviewed_fingerprint=""))
