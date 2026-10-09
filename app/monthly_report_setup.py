"""Conservative report setup and continuation; a cover is never date evidence for a page."""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import replace
from datetime import date
import re

from app.monthly_report_checks import stale_period_mentions
from app.monthly_report_import import DocxInspection, ImportMapping, _heading
from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, default_sections, layout_blocks
from app.monthly_report_asset_review import asset_fingerprint, normalize_asset_reviews, preserve_asset_reviews


MONTHLY_BLOCKS = frozenset({"work_orders", "activity_summary", "improvements", "mbcx_report", "service_calls",
                          "vendor_reports", "water_reports", "training_summary"})
PAGE_BLOCKS = frozenset({"vendor_reports", "water_reports", "mbcx_report"})
PERIOD_REVIEW_BLOCKS = frozenset({"utility_analysis", "mbcx_status"})
DECISIONS = ("Needs review", "Keep in report", "Save for reference", "Exclude from this draft")


def suggested_period(today: date) -> ReportPeriod:
    """During closeout (1–10) suggest last month, otherwise the current month."""
    return ReportPeriod.previous(today) if today.day <= 10 else ReportPeriod(today.year, today.month)


def month_selector(field, prefix: str, default: ReportPeriod, *, label: str = "Reporting") -> ReportPeriod:
    import streamlit as st
    left, right = st.columns(2)
    month = left.selectbox(label + " month", list(range(1, 13)), format_func=lambda n: calendar.month_name[n],
                           key=field(prefix + "_month_number", default.month))
    year = right.selectbox(label + " year", list(range(2000, default.year + 6)),
                          key=field(prefix + "_year", default.year))
    return ReportPeriod(year, month)


def report_period_findings(inspection, period):
    """Describe body evidence without classifying a whole mixed report by its cover."""
    monthly_sections = {"activity", "maintenance", "water", "mbcx", "training"}
    month = calendar.month_name[period.month]
    current_pattern = re.compile(
        rf"\b(?:{month}|{month[:3]}\.?)\s+{period.year}\b|"
        rf"\b{period.year}-{period.month:02d}-\d{{2}}\b|"
        rf"\b0?{period.month}/\d{{1,2}}/{period.year}\b", re.I)
    current = older = images = 0
    for item in inspection.items:
        if item.section not in monthly_sections:
            continue
        if item.kind == "image":
            images += 1
            continue  # nearby text/captions cannot establish an image's service date
        if item.kind not in ("text", "table"):
            continue
        text = "\n".join((item.text, *(" ".join(row) for row in item.rows)))
        current += bool(current_pattern.search(text))
        older += bool(stale_period_mentions(text, period.year, period.month))
    return {"current": current, "older": older, "images": images}


def suggested_mappings(inspection: DocxInspection) -> tuple[ImportMapping, ...]:
    """Ambiguous single-image/table destinations stay unmatched, not last-one-wins."""
    specs = {b.key: b for s in default_sections() for b in s.blocks} | {b.key: b for b in layout_blocks()}
    counts = Counter(i.suggested_slot for i in inspection.items if i.kind in ("image", "table"))
    result = []
    for item in inspection.items:
        spec = specs.get(item.suggested_slot)
        if not spec or item.kind not in ("image", "table", "text"):
            continue
        if counts[spec.key] > 1 and (spec.type == "image_page" or item.kind == "table"):
            continue
        if (item.kind == "image" and spec.type not in ("image_page", "image_grid", "pdf_pages") or
                item.kind == "text" and spec.type not in ("rich_text", "stock_text") or
                item.kind == "table" and spec.type not in ("table", "work_order_grid") and spec.key != "contact_matrix"):
            continue
        result.append(ImportMapping(item.id, spec.key))
    return tuple(result)


def item_findings(item, period: ReportPeriod, image_text: str = "") -> tuple[str, ...]:
    text = "\n".join((item.text, *(" ".join(row) for row in item.rows), image_text))
    findings = []
    stale = stale_period_mentions(text, period.year, period.month)
    if stale:
        findings.append("Other-month/date references: " + ", ".join(stale))
    if item.kind == "image" and not image_text.strip():
        findings.append("Image content has not been read. A nearby heading or cover date does not date this image.")
    if item.suggested_slot in MONTHLY_BLOCKS and not re.search(r"\d{4}|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", text, re.I):
        findings.append("No reliable month established; undated does not mean old.")
    if item.kind == "unsupported":
        findings.append("Unsupported content: retained in the original; inspect it before deciding whether it belongs in the output.")
    return tuple(findings)


def initial_decision(item, mapped: bool, period: ReportPeriod) -> str:
    if item.suggested_slot in MONTHLY_BLOCKS or item_findings(item, period) or item.kind == "unsupported":
        return "Needs review"
    if not mapped and not (item.kind == "text" and _heading(item.text)):
        return "Needs review"  # Unmatched new work must not default out of the output.
    return "Keep in report" if mapped else "Save for reference"


def design_profile(profile, inspection, mappings, overrides=()):
    """Persist confirmed logical order without treating Word section counts as a design."""
    destinations = {m.item_id: m.slot for m in mappings}
    skeleton = default_sections()
    owner = {b.key: s.key for s in skeleton for b in s.blocks}
    found, order, block_order, included = {}, [], {}, set()
    for item in inspection.items:
        slot = destinations.get(item.id)
        # Layout text/images do not belong to the last body section seen by
        # the XML inspector. Never insert footer/logo keys into section order.
        if item.part != "word/document.xml" or (slot and slot not in owner):
            continue
        section = owner.get(slot, item.section)
        if section not in {s.key for s in skeleton}:
            continue
        if slot and section not in order:
            order.append(section)
        if slot:
            included.add(section)
        if item.kind == "text" and _heading(item.text) == section and section not in found:
            if section not in order:
                order.append(section)
            # Floating text boxes can put an address footer, heading and large
            # decorative section number in the same XML paragraph. Recognizing
            # a section does not make that whole paragraph a usable title.
            title = re.sub(r"^\s*(?:Section\s+)?\d+[.\s:–-]*", "", item.text, flags=re.I).strip()
            title = re.sub(r"[\s\n]+\d+[.\s]*$", "", title).strip()
            if not title or len(title) > 90 or re.search(r"[\d@|\n]", title):
                title = next(s.title for s in skeleton if s.key == section)
            found[section] = title
        if slot:
            block_order.setdefault(section, [])
            if slot not in block_order[section]:
                block_order[section].append(slot)
    for s in skeleton:
        if s.key not in order:
            order.append(s.key)
        block_order.setdefault(s.key, [])
        block_order[s.key].extend(b.key for b in s.blocks if b.key not in block_order[s.key])
    return replace(profile, section_order=tuple(order), excluded_sections=tuple(s.key for s in skeleton if s.key not in included),
                   section_titles=tuple(found.items()), section_block_order=tuple((k, tuple(v)) for k, v in block_order.items()),
                   block_overrides=overrides, imported_from=inspection.sha256)


def merge_blocks(existing: ResolvedBlock | None, incoming: ResolvedBlock) -> ResolvedBlock:
    """Append evidence to a partial draft. Never substitute it for another editor's work."""
    if existing is None or existing.source == "Omit":
        return incoming
    if (incoming.fingerprint == existing.fingerprint
            and all(asset_fingerprint(incoming, n) == asset_fingerprint(existing, n)
                    for n in range(len(existing.asset_hashes)))):
        return preserve_asset_reviews(incoming, existing)
    if ((existing.org_nodes and incoming.asset_hashes) or (incoming.org_nodes and existing.asset_hashes)
            or (existing.org_nodes and incoming.org_nodes and existing.org_nodes != incoming.org_nodes)):
        raise ValueError("The incoming report has a different org chart. Keep it for reference and explicitly replace the existing chart after import; neither chart was overwritten.")
    text = existing.text
    if incoming.text.strip() and incoming.text.strip() not in text:
        text = "\n\n".join(t for t in (text, incoming.text) if t)
    images = list(existing.asset_hashes)
    captions = list(existing.asset_captions) + [""] * (len(images) - len(existing.asset_captions))
    for n, reference in enumerate(incoming.asset_hashes):
        if reference not in images:
            images.append(reference)
            captions.append(incoming.asset_captions[n] if n < len(incoming.asset_captions) else "")
    merged = replace(existing, source="This month", text=text,
                   rows=existing.rows + tuple(r for r in incoming.rows if r not in existing.rows),
                   asset_hashes=tuple(images), asset_captions=tuple(captions),
                   references=tuple(dict.fromkeys((*existing.references, *incoming.references))),
                   extra_tables=existing.extra_tables + tuple(t for t in incoming.extra_tables if t not in existing.extra_tables),
                   org_nodes=existing.org_nodes or incoming.org_nodes,
                   photos_per_page=existing.photos_per_page if existing.asset_hashes else incoming.photos_per_page,
                   ai_written=existing.ai_written or incoming.ai_written, reviewed_fingerprint="", client_reviewed_fingerprint="")
    # Empty placeholders and repeated imports must not demand another review of
    # an unchanged approved page. Transfer approval only for identical content,
    # allowing the internal carry-forward label to become "This month".
    # New references, text, captions or assets continue to invalidate approval.
    for reviewed in (existing, incoming):
        reviewed_captions = reviewed.asset_captions + ("",) * (len(reviewed.asset_hashes) - len(reviewed.asset_captions))
        if (reviewed.client_reviewed_fingerprint == reviewed.fingerprint
                and replace(merged, client_asset_reviews=(), asset_provenance=())
                == replace(reviewed, source=merged.source, asset_captions=reviewed_captions,
                           reviewed_fingerprint="", client_reviewed_fingerprint="",
                           client_asset_reviews=(), asset_provenance=())):
            merged = replace(merged, client_reviewed_fingerprint=merged.fingerprint)
            break
    # Each import names the provenance of its own pictures. Adding a different
    # picture/table never broadens the context of previously reviewed pictures.
    # The same bytes from a different source do acquire the combined provenance
    # and must be checked again under that changed context.
    contexts = {}
    for block in (normalize_asset_reviews(existing), normalize_asset_reviews(incoming)):
        for reference, context in block.asset_provenance:
            contexts[reference] = tuple(sorted(set((*contexts.get(reference, ()), *context))))
    merged = replace(merged, asset_provenance=tuple(contexts.items()))
    merged = preserve_asset_reviews(existing, merged)
    return preserve_asset_reviews(incoming, merged)


def merge_report_block(existing: ResolvedBlock | None, incoming: ResolvedBlock,
                       old_spec: BlockSpec | None, new_spec: BlockSpec | None) -> ResolvedBlock:
    """Merge known CMMS rows by identity without silently duplicating corrections.

    Imported tables can use arbitrary schemas, so column positions are trusted
    only for the complete column identities emitted by the CMMS mapper. A blank
    cell may acquire a value; conflicting known values require an explicit edit.
    This function is pure so callers can validate a whole upload before applying it.
    """
    schemas = {
        "service_calls": ("table", ("facility", "wo", "finished", "area", "task", "tag"), (0, 1)),
        "work_orders": ("work_order_grid", ("month", "facility", "pm", "cm", "total"), (0, 1)),
    }
    schema = schemas.get(incoming.key)
    if existing is None or existing.source == "Omit" or not schema or not old_spec or not new_spec:
        return merge_blocks(existing, incoming)
    kind, columns, identity_columns = schema
    if (existing.key != incoming.key or any(
            spec.key != incoming.key or spec.type != kind or tuple(c.key for c in spec.columns) != columns
            for spec in (old_spec, new_spec))):
        return merge_blocks(existing, incoming)
    if any(len(row) != len(columns) for row in (*existing.rows, *incoming.rows)):
        raise ValueError("The saved or uploaded work-order table has incomplete columns. Check its rows before adding; nothing was replaced.")
    rows, identities = [], {}
    for row in (*existing.rows, *incoming.rows):
        identity = tuple(" ".join(row[n].casefold().split()) for n in identity_columns)
        # An unfinished manually entered row is not evidence of the same work.
        if not all(identity):
            if row not in rows:
                rows.append(row)
            continue
        if identity not in identities:
            identities[identity] = len(rows)
            rows.append(row)
            continue
        index = identities[identity]
        saved = rows[index]
        differences = [n for n in range(len(columns)) if n not in identity_columns
                       and saved[n].strip() and row[n].strip() and saved[n].strip() != row[n].strip()]
        if differences:
            fields = ", ".join(old_spec.columns[n].title for n in differences)
            label = (f"service-call rows for {saved[0]}, WO {saved[1]}" if incoming.key == "service_calls"
                     else f"work-order totals for {saved[0]} at {saved[1]}")
            raise ValueError(f"Conflicting {label} ({fields}). Check the saved table and uploaded export before adding; nothing was replaced.")
        rows[index] = tuple(old if old.strip() else new for old, new in zip(saved, row))
    merged = merge_blocks(existing, incoming)
    if tuple(rows) == merged.rows:
        return merged
    return replace(merged, rows=tuple(rows), reviewed_fingerprint="", client_reviewed_fingerprint="")


def _aligned_contact_rows(existing: BlockSpec | None, incoming: BlockSpec, rows):
    """Match complete, unambiguous headings; importer-generated keys are not a schema.

    Do not guess synonyms or trim away unfamiliar columns. A genuinely changed
    set of headings still needs explicit mapping before it can join saved rows.
    """
    if existing is None or existing.type != "table" or incoming.type != "table":
        return None
    old_titles = tuple(" ".join(c.title.casefold().split()) for c in existing.columns)
    new_titles = tuple(" ".join(c.title.casefold().split()) for c in incoming.columns)
    if (not old_titles or "" in old_titles or "" in new_titles
            or len(set(old_titles)) != len(old_titles) or len(set(new_titles)) != len(new_titles)
            or set(old_titles) != set(new_titles)):
        return None
    order = tuple(new_titles.index(title) for title in old_titles)
    if (any(old.type != incoming.columns[index].type for old, index in zip(existing.columns, order))
            or any(len(row) > len(new_titles) for row in rows)):
        return None
    return tuple(tuple(row[index] if index < len(row) else "" for index in order) for row in rows)


def merge_drafts(existing: ReportDraft | None, incoming: ReportDraft) -> ReportDraft:
    if existing is None:
        return incoming
    if (existing.profile.contract, existing.profile.key, existing.period) != (incoming.profile.contract, incoming.profile.key, incoming.period):
        raise ValueError("Only merge drafts for the same confirmed profile and month.")
    old_specs = {b.key: b for s in existing.sections for b in s.blocks} | {b.key: b for b in layout_blocks()}
    old_blocks = {b.key: b for b in existing.blocks}
    occupied = {b.key for b in existing.blocks if b.text.strip() or b.rows or b.asset_hashes or b.org_nodes or b.extra_tables}
    new_specs = {b.key: b for s in incoming.sections for b in s.blocks}
    incoming_blocks = {b.key: b for b in incoming.blocks}
    for s in incoming.sections:
        for spec in s.blocks:
            old = old_blocks.get(spec.key)
            block = incoming_blocks.get(spec.key)
            # A partial import also carries unused template specifications.
            # Those cannot conflict with a contact table reviewed in this draft.
            if not (old and old.rows and block and block.rows) or old_specs.get(spec.key) == spec:
                continue
            rows = _aligned_contact_rows(old_specs.get(spec.key), spec, block.rows) if spec.key == "contact_matrix" else None
            if rows is None:
                raise ValueError("Imported table columns differ from the saved report. Review the table mapping; existing work was not changed.")
            incoming_blocks[spec.key] = replace(block, rows=rows)
    for block in incoming.blocks:
        block = incoming_blocks[block.key]
        old = old_blocks.get(block.key)
        spec = old_specs.get(block.key)
        if old and spec and spec.type == "image_page" and old.asset_hashes and block.asset_hashes and old.asset_hashes != block.asset_hashes:
            raise ValueError("Two different images target a single-image item. Keep the existing one and save the incoming image for reference, then explicitly replace it after import.")
        old_blocks[block.key] = merge_blocks(old_blocks.get(block.key), block)
    incoming_sections = {s.key: s for s in incoming.sections}
    sections = tuple(replace(s, included=s.included or incoming_sections.get(s.key, s).included,
                             blocks=tuple(new_specs.get(b.key, b) if b.key not in occupied else b for b in s.blocks)) for s in existing.sections)
    return replace(existing, blocks=tuple(old_blocks.values()), sections=sections)


def normalize_mbcx(draft: ReportDraft) -> ReportDraft:
    """Separate legacy MBCx wording from monthly pages on a detached draft.

    Saved snapshots remain immutable. References stay with the pages as well as
    the copied text because legacy blocks do not identify which reference backs
    which part. Changed review fingerprints are deliberately invalidated.
    """
    section = next((s for s in draft.sections if s.key == "mbcx"), None)
    if not section or not any(b.key == "mbcx_report" for b in section.blocks):
        return draft
    status_spec = next(b for s in default_sections() if s.key == "mbcx" for b in s.blocks if b.key == "mbcx_status")
    specs = section.blocks
    if not any(b.key == "mbcx_status" for b in specs):
        index = next(n for n, b in enumerate(specs) if b.key == "mbcx_report")
        specs = (*specs[:index], status_spec, *specs[index:])
    blocks = {b.key: b for b in draft.blocks}
    legacy = blocks.get("mbcx_report")
    status = blocks.get("mbcx_status")
    if legacy and (legacy.text.strip() or legacy.ai_paragraphs):
        # Conflicting explicit omissions cannot safely become one combined note.
        # Retain both blocks untouched so no excluded text is silently revived.
        conflicting_omission = bool(status and status.text.strip()
                                    and (status.source == "Omit") != (legacy.source == "Omit"))
        if not conflicting_omission:
            incoming = ResolvedBlock(
                "mbcx_status", legacy.source, text=legacy.text, references=legacy.references,
                ai_written=legacy.ai_written, ai_paragraphs=legacy.ai_paragraphs,
                ai_evidence_fingerprint=legacy.ai_evidence_fingerprint,
            )
            if status and (status.text.strip() or status.ai_paragraphs):
                # Do not replace one editor's wording with another editor's work.
                merged = merge_blocks(status, incoming)
                paragraphs = tuple(dict.fromkeys((*status.ai_paragraphs, *incoming.ai_paragraphs)))
                status = replace(merged, source="Omit" if legacy.source == "Omit" else merged.source,
                                 ai_paragraphs=paragraphs, ai_evidence_fingerprint="")
            else:
                status = incoming
            blocks["mbcx_report"] = preserve_asset_reviews(legacy, replace(legacy, text="", ai_written=False, ai_paragraphs=(),
                                             ai_evidence_fingerprint="", reviewed_fingerprint="",
                                             client_reviewed_fingerprint=""))
    if status is None:
        status = ResolvedBlock("mbcx_status", "This month")
    blocks["mbcx_status"] = status
    return replace(draft, sections=tuple(replace(s, blocks=specs) if s.key == "mbcx" else s for s in draft.sections),
                   blocks=tuple(blocks.values()))


def carried_period(block: ResolvedBlock, current_period: ReportPeriod) -> ReportPeriod | None:
    """Return the last confirmed period of populated, carried monthly content."""
    if (block.key not in PERIOD_REVIEW_BLOCKS or block.source == "Omit"
            or not (block.text.strip() or block.rows or block.asset_hashes or block.extra_tables or block.ai_paragraphs)):
        return None
    for reference in block.references:
        if reference.startswith("report-period:"):
            try:
                prior = ReportPeriod(*(int(value) for value in reference.split(":", 1)[1].split("-")))
            except (TypeError, ValueError):
                continue
            if prior != current_period:
                return prior
    return None


def confirm_current_period(block: ResolvedBlock, period: ReportPeriod) -> ResolvedBlock:
    """Explicit current-month confirmation preserves original evidence and dates."""
    references = tuple(r for r in block.references if not r.startswith("report-period:"))
    return preserve_asset_reviews(block, replace(block, source="Omit" if block.source == "Omit" else "This month",
                   references=(*references, "report-period:" + period.key),
                   reviewed_fingerprint="", client_reviewed_fingerprint=""))


def _carry_period_content(block: ResolvedBlock, period: ReportPeriod) -> ResolvedBlock:
    if block.key not in PERIOD_REVIEW_BLOCKS or not (
            block.text.strip() or block.rows or block.asset_hashes or block.extra_tables or block.ai_paragraphs):
        return block
    references = block.references
    if not any(r.startswith("report-period:") for r in references):
        references = (*references, "report-period:" + period.key)
    if not any(r.startswith("report-origin:") for r in references):
        references = (*references, "report-origin:" + period.key)
    return preserve_asset_reviews(block, replace(block, source="Omit" if block.source == "Omit" else "Last month", references=references,
                   reviewed_fingerprint="", client_reviewed_fingerprint=""))


def new_month_draft(draft: ReportDraft, period: ReportPeriod) -> ReportDraft:
    """Only an explicitly new month drops period-specific attachments, never a mixed import."""
    draft = normalize_mbcx(draft)
    if period == draft.period:
        return draft
    from app.monthly_report_followups import seed_followups
    follow_ups = seed_followups(draft)
    carried_keys = {"equipment_issues", "proposals"}
    blocks = tuple(
        preserve_asset_reviews(b, ResolvedBlock(b.key, "This month", photos_per_page=b.photos_per_page,
                      asset_hashes=b.asset_hashes if b.key in carried_keys else (),
                      asset_captions=b.asset_captions if b.key in carried_keys else (),
                      references=b.references if b.key in carried_keys and b.asset_hashes else (),
                      extra_tables=tuple(replace(t, rows=(), reference="") for t in b.extra_tables)))
        if b.key in MONTHLY_BLOCKS or b.key in carried_keys else _carry_period_content(b, draft.period) for b in draft.blocks)
    # Keep evidence backing carried content at its original date and hash;
    # removing all sources would strand reviewed wording and attached charts.
    references = {r for b in blocks for r in (*b.references, *(t.reference for t in b.extra_tables),
                                               *(r for p in b.ai_paragraphs for r in p.references))}
    references.update(r for item in follow_ups for r in item.references)
    sources = tuple(s for s in draft.sources if any(r == s.id or r.startswith(s.id + ":") for r in references))
    return replace(draft, period=period, sources=sources, follow_ups=follow_ups, blocks=blocks)
