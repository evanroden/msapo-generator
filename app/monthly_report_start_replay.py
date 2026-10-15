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
    additions, replacements, removals = [], {}, set()
    # A reviewed source may now contribute no block at all (Start blank).
    # Process that side of the three-way delta before publishing its receipt.
    # Keep report structure and retained originals; remove only content still
    # equal to this verified source's last acknowledged contribution.
    incoming_keys = {b.key for b in incoming.blocks}
    for key in prior:
        if key in incoming_keys:
            continue
        present = current.get(key)
        if present is None:
            continue
        unchanged_report = (_content(present) == _content(prior[key])
                            and current_specs.get(key) == previous_specs.get(key))
        if not verified or not unchanged_report:
            label = key.replace("_", " ").capitalize()
            raise ValueError(
                f"{label} differs between this report and the repeated Starting report review. "
                "Your report and original are unchanged. Keep the earlier source selection, "
                "or make this correction directly in the report editor before importing again."
            )
        removals.add(key)
    for block in incoming.blocks:
        old = prior.get(block.key)
        if old is None:
            additions.append(block)
            continue
        same_source = (_content(block) == _content(old)
                       and incoming_specs.get(block.key) == previous_specs.get(block.key))
        if same_source:
            continue
        present = current.get(block.key)
        if (_content(present) == _content(block)
                and current_specs.get(block.key) == incoming_specs.get(block.key)):
            continue
        unchanged_report = (_content(present) == _content(old)
                            and current_specs.get(block.key) == previous_specs.get(block.key))
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

    revised = replace(existing, blocks=tuple(replacements.get(b.key, b) for b in existing.blocks
                                             if b.key not in removals),
                      sections=tuple(replace(s, blocks=tuple(
                          incoming_specs[b.key] if b.key in replacements and b.key in incoming_specs else b
                          for b in s.blocks)) for s in existing.sections))
    if not additions:
        return revised
    keys = {b.key for b in additions}
    delta = replace(incoming, blocks=tuple(additions), sections=tuple(
        replace(s, blocks=tuple(b for b in s.blocks if b.key in keys)) for s in incoming.sections))
    return merge_drafts(revised, delta)
