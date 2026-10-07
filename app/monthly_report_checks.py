"""Pure pre-flight checks; the same gate protects UI and direct generation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.monthly_report_model import PLACEHOLDER_PHRASES, ReportDraft, included_sections, layout_blocks, used_block_keys


@dataclass(frozen=True)
class ReportCheck:
    code: str
    message: str
    blocking: bool
    block_key: str = ""


def placeholder_matches(text: str) -> tuple[str, ...]:
    return tuple(phrase for phrase in PLACEHOLDER_PHRASES if re.search(
        r"(?<!\w)" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?!\w)", text, re.I,
    ))


_MONTHS = {name.casefold(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
_MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\b(?:\s+\d{1,2}(?!\d)(?:st|nd|rd|th)?[,]?)?(?:\s+(\d{4}))?", re.I,
)
_DATE_RE = re.compile(r"\b(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})/(\d{1,2})/(\d{2,4}))\b")


def stale_period_mentions(text: str, year: int, month: int) -> tuple[str, ...]:
    findings = []
    for match in _MONTH_RE.finditer(text):
        if match[1] in ("may", "march") and not re.search(r"\d", match[0]):
            continue
        # Historical wording is exempt only immediately before this reference.
        # "Since July. June activity" must still warn about the second sentence.
        if re.search(r"\bsince\s+$", text[max(0, match.start() - 12):match.start()], re.I):
            continue
        if _MONTHS[match[1].casefold()] != month or (match[2] and int(match[2]) != year):
            findings.append(match[0])
    for match in _DATE_RE.finditer(text):
        parts = match.groups()
        yyyy, mm, dd = (parts[:3] if parts[0] else (parts[5], parts[3], parts[4]))
        try:
            value = date(int(yyyy) + (2000 if len(yyyy) == 2 else 0), int(mm), int(dd))
        except ValueError:
            findings.append(match[0])
            continue
        if (value.year, value.month) != (year, month):
            findings.append(match[0])
    return tuple(dict.fromkeys(findings))


def preflight(draft: ReportDraft, estimated_bytes: int = 0) -> tuple[ReportCheck, ...]:
    checks = []
    sections = included_sections(draft.sections)
    if not draft.prepared_by.strip():
        checks.append(ReportCheck("prepared_by", "Enter who prepared this report.", True))
    if not sections:
        checks.append(ReportCheck("sections", "Include at least one section.", True))
    if len({s.key for s in draft.sections}) != len(draft.sections):
        checks.append(ReportCheck("duplicate_sections", "Section identities must be unique.", True))
    keys = [b.key for b in draft.blocks]
    if len(set(keys)) != len(keys):
        checks.append(ReportCheck("duplicate_blocks", "Block identities must be unique.", True))
    blocks = {b.key: b for b in draft.blocks}
    texts = [("cover", draft.profile.title), ("cover", draft.prepared_by), ("footer", draft.address_line)]
    texts.extend(("cover", f.title) for f in draft.profile.facilities)
    texts.append(("cover", draft.profile.contract))
    layout_keys = {spec.key for spec in layout_blocks()} & used_block_keys(draft)
    for block in draft.blocks:
        if block.key in layout_keys and block.source != "Omit":
            texts.append((block.key, block.text))
            if not block.reviewed:
                checks.append(ReportCheck("review", f"Review the AI draft: {block.key}.", True, block.key))
            if block.pending_library_save:
                checks.append(ReportCheck("library_save", f"Confirm the library replacement for {block.key}, or choose Replace once.", True, block.key))
    for section in sections:
        if not section.title.strip():
            checks.append(ReportCheck("title", "Enter a title for every included section.", True, section.key))
        texts.append((section.key, section.title))
        has_content = False
        for spec in section.blocks:
            block = blocks.get(spec.key)
            present = bool(block and block.source != "Omit" and (
                block.text.strip() or block.asset_hashes or any(any(c.strip() for c in row) for row in block.rows)
            ))
            if present and spec.type in ("image_page", "image_grid", "pdf_pages"):
                present = bool(block.asset_hashes or (block.source == "Stock text" and spec.stock_text_keys))
            if present and spec.type in ("table", "work_order_grid"):
                present = bool(block.rows or (block.source == "Stock text" and spec.stock_text_keys))
            has_content |= present
            if spec.required and not present:
                checks.append(ReportCheck("required", f"Resolve required block: {spec.key}.", True, spec.key))
            if block and block.source not in spec.allowed_sources:
                checks.append(ReportCheck("source", f"Unsupported source for {spec.key}.", True, spec.key))
            if block and block.pending_library_save:
                checks.append(ReportCheck("library_save", f"Confirm the library replacement for {spec.key}, or choose Replace once.", True, spec.key))
            # Even an incomplete optional image can carry a visible caption.
            # Scan all included text, rather than only fully resolved payloads.
            if block and block.source != "Omit":
                if not block.reviewed:
                    checks.append(ReportCheck("review", f"Review the AI draft: {spec.key}.", True, spec.key))
                texts.append((spec.key, block.text))
                texts.extend((spec.key, caption) for caption in block.asset_captions)
                texts.extend((spec.key, cell) for row in block.rows for cell in row)
                if block.rows:
                    texts.extend((spec.key, col.title) for col in spec.columns)
        if not has_content:
            checks.append(ReportCheck("empty", f"{section.title} is included but empty.", False, section.key))
    for key, text in texts:
        phrases = placeholder_matches(text)
        if phrases:
            checks.append(ReportCheck("placeholder", f"Remove template instructions from {key}: {', '.join(phrases)}.", True, key))
        stale = stale_period_mentions(text, draft.period.year, draft.period.month)
        if stale:
            checks.append(ReportCheck("period", f"Check period references in {key}: {', '.join(stale)}.", False, key))
    if estimated_bytes > 15 * 1024 * 1024:
        checks.append(ReportCheck("size", "Estimated output exceeds 15 MB.", False))
    names = {name.strip().casefold() for facility in draft.profile.facilities for name in (facility.key, facility.title, *facility.aliases)}
    for source in draft.sources:
        if source.classification == "Reference only" or not source.selected_pages:
            continue
        if source.service_date:
            try:
                value = date.fromisoformat(source.service_date)
                valid_period = draft.period.start <= value <= draft.period.end
            except ValueError:
                valid_period = False
            if not valid_period:
                checks.append(ReportCheck("source_period", f"Check uploaded source date: {source.filename} ({source.service_date}).", False, source.id))
        else:
            checks.append(ReportCheck("source_date_unknown", f"Confirm the reporting date for {source.filename}; no date has been established.", False, source.id))
        if not source.facility or source.facility.strip().casefold() not in names:
            checks.append(ReportCheck("source_facility", f"Check uploaded source facility: {source.filename} ({source.facility or 'not established'}).", False, source.id))
    return tuple(checks)
