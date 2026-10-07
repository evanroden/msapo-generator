"""Conservative report setup and continuation; a cover is never date evidence for a page."""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import replace
from datetime import date
import re

from app.monthly_report_checks import stale_period_mentions
from app.monthly_report_import import DocxInspection, ImportMapping, _heading
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, layout_blocks


MONTHLY_BLOCKS = frozenset({"work_orders", "activity_summary", "improvements", "mbcx_report", "service_calls",
                          "vendor_reports", "water_reports", "training_summary"})
PAGE_BLOCKS = frozenset({"vendor_reports", "water_reports", "mbcx_report"})
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
    found, order, block_order = {}, [], {}
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
        if item.kind == "text" and _heading(item.text) == section and section not in found:
            title = re.sub(r"^\s*(?:Section\s+)?\d+[.\s:–-]*", "", item.text, flags=re.I).strip()
            if title:
                found[section] = title
        if slot:
            block_order.setdefault(section, [])
            if slot not in block_order[section]:
                block_order[section].append(slot)
    included = set(order)
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
    if incoming.fingerprint == existing.fingerprint:
        return existing
    text = existing.text
    if incoming.text.strip() and incoming.text.strip() not in text:
        text = "\n\n".join(t for t in (text, incoming.text) if t)
    images = list(existing.asset_hashes)
    captions = list(existing.asset_captions) + [""] * (len(images) - len(existing.asset_captions))
    for n, reference in enumerate(incoming.asset_hashes):
        if reference not in images:
            images.append(reference)
            captions.append(incoming.asset_captions[n] if n < len(incoming.asset_captions) else "")
    return replace(existing, source="This month", text=text,
                   rows=existing.rows + tuple(r for r in incoming.rows if r not in existing.rows),
                   asset_hashes=tuple(images), asset_captions=tuple(captions),
                   references=tuple(dict.fromkeys((*existing.references, *incoming.references))),
                   extra_tables=existing.extra_tables + tuple(t for t in incoming.extra_tables if t not in existing.extra_tables),
                   ai_written=existing.ai_written or incoming.ai_written, reviewed_fingerprint="", client_reviewed_fingerprint="")


def merge_drafts(existing: ReportDraft | None, incoming: ReportDraft) -> ReportDraft:
    if existing is None:
        return incoming
    if (existing.profile.contract, existing.profile.key, existing.period) != (incoming.profile.contract, incoming.profile.key, incoming.period):
        raise ValueError("Only merge drafts for the same confirmed profile and month.")
    old_specs = {b.key: b for s in existing.sections for b in s.blocks} | {b.key: b for b in layout_blocks()}
    old_blocks = {b.key: b for b in existing.blocks}
    occupied = {b.key for b in existing.blocks if b.text.strip() or b.rows or b.asset_hashes or b.extra_tables}
    new_specs = {b.key: b for s in incoming.sections for b in s.blocks}
    for s in incoming.sections:
        for spec in s.blocks:
            if spec.key in old_blocks and old_blocks[spec.key].rows and old_specs.get(spec.key) != spec:
                raise ValueError("Imported table columns differ from the saved report. Review the table mapping; existing work was not changed.")
    for block in incoming.blocks:
        old = old_blocks.get(block.key)
        spec = old_specs.get(block.key)
        if old and spec and spec.type == "image_page" and old.asset_hashes and block.asset_hashes and old.asset_hashes != block.asset_hashes:
            raise ValueError("Two different images target a single-image item. Keep the existing one and save the incoming image for reference, then explicitly replace it after import.")
        old_blocks[block.key] = merge_blocks(old_blocks.get(block.key), block)
    incoming_sections = {s.key: s for s in incoming.sections}
    sections = tuple(replace(s, included=s.included or incoming_sections.get(s.key, s).included,
                             blocks=tuple(new_specs.get(b.key, b) if b.key not in occupied else b for b in s.blocks)) for s in existing.sections)
    return replace(existing, blocks=tuple(old_blocks.values()), sections=sections)


def new_month_draft(draft: ReportDraft, period: ReportPeriod) -> ReportDraft:
    """Only an explicitly new month drops period-specific attachments, never a mixed import."""
    return replace(draft, period=period, sources=(), blocks=tuple(
        ResolvedBlock(b.key, "This month", extra_tables=tuple(replace(t, rows=(), reference="") for t in b.extra_tables))
        if b.key in MONTHLY_BLOCKS else b for b in draft.blocks))
