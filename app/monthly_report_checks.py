"""Pure pre-flight checks; the same gate protects UI and direct generation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.monthly_report_content_policy import (
    contains_price,
    price_column,
    table_has_pricing,
)
from app.monthly_report_model import (
    PLACEHOLDER_PHRASES,
    ReportDraft,
    included_sections,
    layout_blocks,
    used_block_keys,
)


@dataclass(frozen=True)
class ReportCheck:
    code: str
    message: str
    blocking: bool
    block_key: str = ""


def placeholder_matches(text: str) -> tuple[str, ...]:
    return tuple(phrase for phrase in PLACEHOLDER_PHRASES if re.search(
        r"(?<!\w)" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?!\w)", text, re.IGNORECASE,
    ))


_MONTHS = {name.casefold(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
_MONTH_RE = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True))
    + r")\b(?:\s+\d{1,2}(?!\d)(?:st|nd|rd|th)?[,]?)?(?:\s+(\d{4}))?", re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})/(\d{1,2})/(\d{2,4}))\b")


def stale_period_mentions(text: str, year: int, month: int) -> tuple[str, ...]:
    findings = []
    for match in _MONTH_RE.finditer(text):
        if match[1] in ("may", "march") and not re.search(r"\d", match[0]):
            continue
        # Historical wording is exempt only immediately before this reference.
        # "Since July. June activity" must still warn about the second sentence.
        if re.search(r"\bsince\s+$", text[max(0, match.start() - 12):match.start()], re.IGNORECASE):
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
    from app.monthly_report_designs import is_master
    native_master = is_master(draft.profile)
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
    from app.monthly_report_followups import problems, report_text
    for item in draft.follow_ups:
        for message in problems(item, draft):
            checks.append(ReportCheck("follow_up", message, True, item.key))
        if item.included:
            section_key = "issues" if item.category == "issue" else "proposals"
            if section_key not in {s.key for s in sections}:
                message = ("Include the Proposals section or explicitly leave this proposal out." if item.category == "proposal"
                           else "Include the section containing carried work, or explicitly resolve and remove the item.")
                checks.append(ReportCheck("follow_up_section", message, True, item.key))
            texts.append((section_key, report_text(item)))
    for block in draft.blocks:
        if block.key in used_block_keys(draft) and block.source != "Omit":
            from app.monthly_report_setup import carried_period
            prior_period = carried_period(block, draft.period)
            if prior_period:
                checks.append(ReportCheck("carried_period", f"This content was last confirmed for {prior_period.label}. Update it or confirm it is correct for {draft.period.label} before including it.", True, block.key))
            if block.ai_written and (block.ai_evidence_fingerprint or block.ai_paragraphs):
                from app.monthly_report_ai import ai_references, evidence_fingerprint
                if not block.ai_evidence_fingerprint or block.ai_evidence_fingerprint != evidence_fingerprint(draft.sources, ai_references(block)):
                    checks.append(ReportCheck("ai_evidence", "Evidence changed or a source is missing. Refresh and review the AI draft before generating.", True, block.key))
            if any("Unsupported number" in flag for paragraph in block.ai_paragraphs for flag in paragraph.flags):
                checks.append(ReportCheck("ai_number", "Correct unsupported numerical statements in the AI draft.", True, block.key))
            if block.org_nodes:
                if block.asset_hashes:
                    checks.append(ReportCheck("org_chart", "Choose the editable chart or the uploaded chart, not both in the same chart item.", True, block.key))
                from app.monthly_report_visuals import validate_org
                try:
                    validate_org(block.org_nodes)
                except ValueError as exc:
                    checks.append(ReportCheck("org_chart", str(exc), True, block.key))
                texts.extend((block.key, value) for node in block.org_nodes for value in (node.name, node.role, node.team))
            if type(block.photos_per_page) is not int or not 1 <= block.photos_per_page <= 6:
                checks.append(ReportCheck("photo_layout", "Choose between 1 and 6 photos per page.", True, block.key))
            from app.monthly_report_asset_review import pending_asset_indexes
            pending_pictures = pending_asset_indexes(block, draft.sources)
            if pending_pictures:
                count = len(pending_pictures)
                checks.append(ReportCheck("client_pages", f"Check {count} new or changed picture{'s' if count != 1 else ''} in {block.key.replace('_', ' ')} for relevance and visible pricing before including them.", True, block.key))
            if block.asset_hashes:
                from app.monthly_report_asset_review import asset_context
                from app.monthly_report_content_policy import page_allowed
                source_index = {s.id: s for s in draft.sources}
                image_references = {reference for n in range(len(block.asset_hashes)) for reference in asset_context(block, n)}
                for reference in block.references:
                    parts = reference.split(":")
                    source = source_index.get(parts[0])
                    if source is None and reference in image_references and len(parts) == 3 and parts[1].isdigit():
                        checks.append(ReportCheck("client_source_missing", "The original source for an included picture is missing. Restore its source file or replace/remove the picture before generating.", True, block.key))
                    if source and len(parts) == 3 and parts[1].isdigit():
                        page = int(parts[1])
                        if page not in source.selected_pages or not 1 <= page <= len(source.page_texts) or not page_allowed(source, page):
                            checks.append(ReportCheck("client_source_page", f"Remove or review page {page} of {source.filename} in this section. Its current selection is not approved for the client report.", True, block.key))
            for table in block.extra_tables:
                texts.extend((block.key, cell) for row in table.rows for cell in row)
                texts.extend((block.key, title) for title in table.columns)
                if table_has_pricing(table.columns, table.rows):
                    checks.append(ReportCheck("pricing", "Remove pricing or clarify ambiguous total rows in the client table.", True, block.key))
                if any(price_column(title) and any(i < len(r) and r[i].strip() for r in table.rows) for i, title in enumerate(table.columns)):
                    checks.append(ReportCheck("pricing", "Remove pricing columns from the client report.", True, block.key))
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
        carried = [item for item in draft.follow_ups if item.included and ("issues" if item.category == "issue" else "proposals") == section.key]
        has_content = bool(carried)
        for spec in section.blocks:
            block = blocks.get(spec.key)
            has_extra_tables = bool(block and any(any(c.strip() for row in t.rows for c in row) for t in block.extra_tables))
            present = bool(block and block.source != "Omit" and (
                block.text.strip() or block.asset_hashes or block.org_nodes or has_extra_tables or any(any(c.strip() for c in row) for row in block.rows)
            ))
            if spec.key == "equipment_issues" and carried:
                present = True
            if present and spec.type in ("image_page", "image_grid", "pdf_pages"):
                present = bool(block.asset_hashes or block.org_nodes or has_extra_tables or (block.source == "Stock text" and spec.stock_text_keys))
            if present and spec.type in ("table", "work_order_grid"):
                present = bool(block.rows or has_extra_tables or block.asset_hashes or (block.source == "Stock text" and spec.stock_text_keys))
            has_content |= present
            # Native ENFRA pages remain included when this month has no data.
            # Empty or explicit pending content must not force fabricated facts.
            if spec.required and not present and not native_master:
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
                    if table_has_pricing(tuple(c.title for c in spec.columns), block.rows, work_orders=spec.type == "work_order_grid"):
                        checks.append(ReportCheck("pricing", "Remove pricing or clarify ambiguous total rows in the client table.", True, spec.key))
                    texts.extend((spec.key, col.title) for col in spec.columns)
                    if any(price_column(col.title, col.type) and any(i < len(r) and r[i].strip() for r in block.rows) for i, col in enumerate(spec.columns)):
                        checks.append(ReportCheck("pricing", "Remove pricing columns from the client report.", True, spec.key))
        if not has_content:
            checks.append(ReportCheck("empty", f"{section.title} is included but empty.", False, section.key))
    for key, text in texts:
        if contains_price(text):
            checks.append(ReportCheck("pricing", f"Remove pricing from {key.replace('_', ' ')}. Client reports cannot contain prices.", True, key))
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
