"""Replay an acknowledged Starting source without restoring report-only deletions."""

from dataclasses import replace

from app.monthly_report_model import ReportDraft, ResolvedBlock
from app.monthly_report_setup import merge_drafts


def _content(block: ResolvedBlock | None):
    if block is None:
        return None
    # A saved review or carry label is not a new contribution from the source.
    # Retain all actual text, rows, captions, evidence and per-picture provenance.
    return replace(block, source="Omit" if block.source == "Omit" else "This month", reviewed_fingerprint="",
                   client_reviewed_fingerprint="", client_asset_reviews=())


def merge_starting_drafts(existing: ReportDraft | None, incoming: ReportDraft,
                          previous: ReportDraft | None = None, *, verified: bool = True) -> ReportDraft:
    """Three-way, report-scoped replay; unrelated sources use the normal merge.

    ``previous`` is the last acknowledged contribution from these exact bytes
    to this profile/month, not the current edited report. Unchanged source
    items stay consumed even when their current report block is blank/missing.
    Concurrent changes in both the report and its source review need a named
    correction, never an automatic overwrite or resurrection.
    """
    if existing is None or previous is None:
        return merge_drafts(existing, incoming)
    identity = lambda d: (d.profile.contract, d.profile.key, d.period)
    if identity(existing) != identity(incoming) or identity(previous) != identity(incoming):
        raise ValueError("Starting report replay belongs to different sites or a different month.")

    prior = {b.key: b for b in previous.blocks}
    current = {b.key: b for b in existing.blocks}
    previous_specs = {b.key: b for s in previous.sections for b in s.blocks}
    current_specs = {b.key: b for s in existing.sections for b in s.blocks}
    incoming_specs = {b.key: b for s in incoming.sections for b in s.blocks}
    additions, replacements, reselected_tables = [], {}, {}
    # A receipt proves what the source contained, not sole ownership of equal
    # report content: generic merging may have deduplicated earlier human text.
    # Do not silently acknowledge a blank source review while retaining that
    # content, or delete it by guessing ownership. Clear/omit it explicitly in
    # the report editor first; an already blank/omitted block stays unchanged.
    incoming_keys = {b.key for b in incoming.blocks}
    for key in prior:
        if key in incoming_keys:
            continue
        present = current.get(key)
        # Retaining table headings is not retaining monthly rows. The normal
        # editor keeps the schema after deleting every row; it must not make
        # the named Clear recovery impossible. Populated rows still block.
        populated = present is not None and present.source != "Omit" and bool(
            present.text.strip() or present.rows or present.asset_hashes
            or present.org_nodes or any(table.rows for table in present.extra_tables)
            or present.ai_paragraphs)
        # Imported footer text also lives outside the block in address_line.
        # Native generators use that value even when the block is absent.
        footer_remaining = key == "footer_text" and bool(existing.address_line.strip())
        if populated or footer_remaining:
            label = key.replace("_", " ").capitalize()
            raise ValueError(
                f"{label} is still in this report, but the repeated Starting review leaves it out. "
                "Your report and original are unchanged. Clear or omit this content in the report editor "
                "before importing again, or keep the earlier source selection."
            )
    for block in incoming.blocks:
        old = prior.get(block.key)
        if old is None:
            present = current.get(block.key)
            if present is not None and present.source == "Omit":
                # A deselected receipt has no block, but the report may retain
                # omitted human work. Consume this source selection without
                # letting generic merging replace or re-include that work.
                continue
            if present is not None and present.source != "Omit":
                # A deselected receipt has no block, while the report editor
                # retains empty table schemas after Clear. Explicitly selecting
                # that same source table again fills its empty slot, rather
                # than appending a second table beside the stale schema. Only
                # exact nonempty source identities qualify: other empty tables
                # and every populated table remain normal additive content.
                selected = {table.reference for table in block.extra_tables if table.reference}
                tables = tuple(table for table in present.extra_tables
                               if table.rows or not table.reference or table.reference not in selected)
                if tables != present.extra_tables:
                    reselected_tables[block.key] = replace(present, extra_tables=tables)
            additions.append(block)
            continue
        same_source = (_content(block) == _content(old)
                       and incoming_specs.get(block.key) == previous_specs.get(block.key))
        if same_source:
            continue
        present = current.get(block.key)
        # Native output also consumes address_line. A footer block matching
        # the prior source does not prove that independently edited value is
        # unchanged; the guided editor would copy a replacement block over it.
        address_compatible = (block.key != "footer_text" or existing.address_line in (
            previous.address_line, "" if block.source == "Omit" else block.text))
        if (_content(present) == _content(block)
                and current_specs.get(block.key) == incoming_specs.get(block.key)
                and address_compatible):
            continue
        unchanged_report = (_content(present) == _content(old)
                            and current_specs.get(block.key) == previous_specs.get(block.key)
                            and address_compatible)
        if not verified or not unchanged_report:
            label = block.key.replace("_", " ").capitalize()
            raise ValueError(
                f"{label} differs between this report and the repeated Starting report review. "
                "Your report and original are unchanged. Keep the earlier source selection, "
                "or make this correction directly in the report editor before importing again."
            )
        # An explicit changed source-review choice can replace only its own
        # unchanged contribution, never a block with intervening report edits.
        replacements[block.key] = block

    revised = replace(existing, blocks=tuple(replacements.get(b.key, reselected_tables.get(b.key, b))
                                             for b in existing.blocks),
                      sections=tuple(replace(s, blocks=tuple(
                          incoming_specs[b.key] if b.key in replacements and b.key in incoming_specs else b
                          for b in s.blocks)) for s in existing.sections))
    if not additions:
        return revised
    keys = {b.key for b in additions}
    delta = replace(incoming, blocks=tuple(additions), sections=tuple(
        replace(s, blocks=tuple(b for b in s.blocks if b.key in keys)) for s in incoming.sections))
    return merge_drafts(revised, delta)
