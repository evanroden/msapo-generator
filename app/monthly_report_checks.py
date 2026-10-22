"""Pure pre-flight checks; the same gate protects UI and direct generation."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
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
    used_source_ids,
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


def _clearly_future_follow_up(text: str, start: int, end: int, *, source_year: int,
                              source_month: int, target_year: int, target_month: int) -> bool:
    """Do not mislabel explicitly future tasks as work in the wrong month.

    Only future month references in the same short clause with a clear planning
    qualifier are exempt. Earlier completed work stays reviewable, even when
    a later sentence mentions a follow-up.
    """
    if (source_year, source_month) <= (target_year, target_month):
        return False
    before = re.split(r"[.?!\n;]", text[max(0, start - 100):start])[-1]
    after = re.split(r"[.?!\n;]", text[end:end + 100])[0]
    context = before + " " + after
    if re.search(r"\b(?:completed|performed|occurred|finished|was done)\b", context, re.I):
        return False
    return bool(re.search(
        r"\b(?:future|follow[- ]?up|next\s+month|plan(?:ned)?|schedul\w*|"
        r"expected|upcoming|to\s+be\s+done|will\s+(?:check|inspect|return))\b",
        context, re.I))


def stale_period_mentions(text: str, year: int, month: int) -> tuple[str, ...]:
    findings = []
    for match in _MONTH_RE.finditer(text):
        if match[1] in ("may", "march") and not re.search(r"\d", match[0]):
            continue
        # Historical wording is exempt only immediately before this reference.
        # "Since July. June activity" must still warn about the second sentence.
        if re.search(r"\bsince\s+$", text[max(0, match.start() - 12):match.start()], re.IGNORECASE):
            continue
        observed_month = _MONTHS[match[1].casefold()]
        observed_year = int(match[2]) if match[2] else year
        if (observed_year, observed_month) != (year, month) and not _clearly_future_follow_up(
                text, match.start(), match.end(), source_year=observed_year,
                source_month=observed_month, target_year=year, target_month=month):
            findings.append(match[0])
    for match in _DATE_RE.finditer(text):
        parts = match.groups()
        yyyy, mm, dd = (parts[:3] if parts[0] else (parts[5], parts[3], parts[4]))
        try:
            value = date(int(yyyy) + (2000 if len(yyyy) == 2 else 0), int(mm), int(dd))
        except ValueError:
            findings.append(match[0])
            continue
        if (value.year, value.month) != (year, month) and not _clearly_future_follow_up(
                text, match.start(), match.end(), source_year=value.year,
                source_month=value.month, target_year=year, target_month=month):
            findings.append(match[0])
    return tuple(dict.fromkeys(findings))


def _annual_work_order_month_cells(key, table):
    """Coordinates of labels in the complete, two-measure annual grid only.

    Imported tables put repeated header bands in body rows. Preserve that
    structure when classifying labels; never exempt a month by its text alone.
    Row zero is the table's columns, followed by its unchanged body rows.
    The legacy editor also saved a six-row form after removing both empty
    first-half value rows. Recognize only these exact eight/six-row schemas;
    unknown/partial/reordered shapes retain normal date review.
    """
    rows = (table.columns, *table.rows)
    if key != "work_orders" or len(rows) not in (6, 8) or any(len(row) != 7 for row in rows):
        return frozenset()
    bands = (((0, "wo received", 1), (2, "", 7), (4, "closed", 1), (6, "", 7))
             if len(rows) == 8 else
             ((0, "wo received", 1), (1, "", 7), (3, "closed", 1), (4, "", 7)))
    for index, label, first in bands:
        row = rows[index]
        # Word wraps the measure heading across lines; compare its words
        # without rewriting saved cells or relaxing the required label.
        if " ".join(row[0].split()).casefold() != label:
            return frozenset()
        # Full names/abbreviations and one terminal period are labels. Years,
        # day numbers, prose, ranges and mixed values must not qualify.
        months = tuple(_MONTHS.get(cell.strip().removesuffix(".").casefold()) for cell in row[1:])
        if months != tuple(range(first, first + 6)):
            return frozenset()
    return frozenset((index, column) for index, _, _ in bands for column in range(1, 7))


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
    # Names and contract labels are identifiers, not evidence that work happened
    # on a date. Keep price/placeholder checks but omit month review for these.
    texts = [("report_identity", draft.profile.title), ("report_identity", draft.prepared_by),
             ("footer", draft.address_line)]
    texts.extend(("report_identity", f.title) for f in draft.profile.facilities)
    texts.append(("report_identity", draft.profile.contract))
    from app.monthly_report_followups import problems, report_text, followup_limit_message, output_followups
    limit = followup_limit_message(draft)
    if limit:
        for category, key in (("issue", "equipment_issues"), ("proposal", "proposals")):
            if any(item.category == category for item in output_followups(draft)):
                checks.append(ReportCheck("follow_up_limit", limit, True, key))
    followup_keys = [item.key for item in draft.follow_ups]
    if len(followup_keys) != len(set(followup_keys)):
        checks.append(ReportCheck("follow_up_identity", "Open the issue/proposal editor to repair colliding row identities before generating.", True))
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
            if block.ai_paragraphs:
                from app.monthly_report_ai import block_date_problems
                checks.extend(ReportCheck("ai_date", message, True, block.key)
                              for message in block_date_problems(block, draft.sources))
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
                    if source and reference in image_references and len(parts) == 3 and parts[1].isdigit():
                        page = int(parts[1])
                        if page not in source.selected_pages or not 1 <= page <= len(source.page_texts) or not page_allowed(source, page):
                            checks.append(ReportCheck("client_source_page", f"Remove or review page {page} of {source.filename} in this section. Its current selection is not approved for the client report.", True, block.key))
            for table in block.extra_tables:
                month_labels = _annual_work_order_month_cells(block.key, table)
                texts.extend((block.key, cell, None, (r, c) in month_labels)
                             for r, row in enumerate((table.columns, *table.rows))
                             for c, cell in enumerate(row))
                if table_has_pricing(table.columns, table.rows):
                    checks.append(ReportCheck("pricing", "Remove pricing or clarify ambiguous total rows in the client table.", True, block.key))
                if any(price_column(title) and any(i < len(r) and r[i].strip() for r in table.rows) for i, title in enumerate(table.columns)):
                    checks.append(ReportCheck("pricing", "Remove pricing columns from the client report.", True, block.key))
    layout_keys = {spec.key for spec in layout_blocks()} & used_block_keys(draft)
    for block in draft.blocks:
        if block.key in layout_keys and block.source != "Omit":
            texts.append((block.key, block.text, block))
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
                texts.append((spec.key, block.text, block))
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
    for item in texts:
        key, text = item[:2]
        narrative = item[2] if len(item) >= 3 else None
        structural_month = len(item) == 4 and item[3]
        if contains_price(text):
            checks.append(ReportCheck("pricing", f"Remove pricing from {key.replace('_', ' ')}. Client reports cannot contain prices.", True, key))
        phrases = placeholder_matches(text)
        if phrases:
            checks.append(ReportCheck("placeholder", f"Remove template instructions from {key}: {', '.join(phrases)}.", True, key))
        if key != "report_identity" and not structural_month:
            if narrative is not None:
                from app.monthly_report_period_items import apply_exclusions, unresolved_mentions
                stale = unresolved_mentions(narrative, draft.period, draft.sources)
                if apply_exclusions(narrative, draft.period).text != narrative.text:
                    checks.append(ReportCheck("period_removed", "Previously excluded dated wording reappeared. Resolve that exact item before generating.", True, key))
            else:
                stale = stale_period_mentions(text, draft.period.year, draft.period.month)
            if stale:
                checks.append(ReportCheck("period", f"Check period references in {key}: {', '.join(stale)}.", False, key))
    if estimated_bytes > 15 * 1024 * 1024:
        checks.append(ReportCheck("size", "Tracked report content and artwork may exceed 15 MB. Check the actual DOCX and PDF sizes after generating.", False))
    names = {name.strip().casefold() for facility in draft.profile.facilities for name in (facility.key, facility.title, *facility.aliases)}
    included_sources = used_source_ids(draft)
    missing_sources = included_sources - {source.id for source in draft.sources}
    for source_id in sorted(missing_sources):
        # Removing the intake record cannot authorize content that still cites
        # that original. Keep the content recoverable and point to its editor.
        block = next((block for block in draft.blocks if source_id in used_source_ids(
            replace(draft, blocks=(block,), follow_ups=()))), None)
        follow_up = next((item for item in draft.follow_ups if source_id in used_source_ids(
            replace(draft, blocks=(), follow_ups=(item,)))), None)
        key = block.key if block else follow_up.key if follow_up else ""
        checks.append(ReportCheck("source_missing",
            "An included item refers to a source file that is no longer in this draft. "
            "Restore the original source file or remove its linked report content.", True, key))
    for source in draft.sources:
        facility = source.facility.strip().casefold()
        foreign_included = bool(facility and facility not in names and source.id in included_sources)
        from app.monthly_report_source_scope import included_scope_valid
        unknown_included = ((not facility or source.scope_review) and source.id in included_sources
                            and not included_scope_valid(draft, source))
        if foreign_included:
            checks.append(ReportCheck("source_facility",
                f"{source.filename} is marked for {source.facility}, outside this report's selected sites. "
                "Correct its source details or remove the linked content.", True, source.id))
        elif unknown_included:
            checks.append(ReportCheck("source_facility",
                f"Establish the site scope of {source.filename} before including its content. "
                "Choose the exact sites in its source details, or remove the linked content.", True, source.id))
        # Classification and intake selections do not remove already-included
        # text/tables. They must not bypass the required foreign-site check.
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
        if ((not facility or facility not in names) and not foreign_included and not unknown_included
                and not (source.id in included_sources and included_scope_valid(draft, source))):
            checks.append(ReportCheck("source_facility", f"Check uploaded source facility: {source.filename} ({source.facility or 'not established'}).", False, source.id))
    from app.monthly_report_layout_checks import layout_checks
    checks.extend(layout_checks(draft))
    # Same issue can be reached through the cover and a repeated section
    # binding. Preserve distinct fields/messages but show each exact concern once.
    return tuple(dict.fromkeys(checks))
