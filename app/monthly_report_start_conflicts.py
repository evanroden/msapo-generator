"""Explicit, report-only recovery for a different single organization page.

This is not a merge policy, artwork approval, or a logo selector. The ordinary
merge remains authoritative; only a current exact non-brand collision can be
replaced after its two previews were offered. No disposition is persisted as a
fictional consumed contribution: successful imports save the actual new block.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re

from app.monthly_report_model import ReportDraft, ResolvedBlock
from app.monthly_report_start_replay import merge_starting_drafts

LABELS = {
    "org_chart": "Organization chart",
    "business_hours_workflow": "Daytime outage procedure",
    "after_hours_workflow": "After-hours outage procedure",
    "contact_matrix": "Facility contact page",
}


def _digest(value):
    return hashlib.sha256(json.dumps(asdict(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _picture_only(block):
    return (block.source != "Omit" and len(block.asset_hashes) == 1 and len(block.asset_captions) <= 1
            and not (block.text.strip() or block.rows or block.org_nodes or block.ai_paragraphs
                     or block.extra_tables or block.ai_written))


@dataclass(frozen=True)
class ImageConflict:
    slot: str
    label: str
    current: ResolvedBlock
    incoming: ResolvedBlock
    binding: str


def image_conflicts(existing: ReportDraft | None, incoming: ReportDraft,
                    previous: ReportDraft | None, *, verified: bool,
                    source_sha256: str, profile_revision: int, snapshot_revision: int,
                    incarnation: str) -> tuple[ImageConflict, ...]:
    """Return only real merge conflicts in the finite non-brand page scope."""
    if existing is None:
        return ()
    identity = lambda d: (d.profile.contract, d.profile.key, d.period)
    if identity(existing) != identity(incoming) or previous and identity(previous) != identity(incoming):
        raise ValueError("Picture replacement belongs to a different report or month.")
    if (not re.fullmatch(r"[0-9a-f]{64}", source_sha256) or not incarnation
            or type(profile_revision) is not int or type(snapshot_revision) is not int
            or min(profile_revision, snapshot_revision) < 0):
        raise ValueError("Picture replacement review context is invalid.")
    for draft in (existing, incoming, previous):
        if draft and len({b.key for b in draft.blocks}) != len(draft.blocks):
            raise ValueError("Picture replacement has ambiguous report destinations.")
    old = {b.key: b for b in existing.blocks}
    for draft in (existing, incoming):
        keys = [b.key for section in draft.sections for b in section.blocks if b.key in LABELS]
        if len(keys) != len(set(keys)):
            raise ValueError("Picture replacement has ambiguous section destinations.")
    specs = {b.key: b for s in existing.sections for b in s.blocks}
    new_specs = {b.key: b for s in incoming.sections for b in s.blocks}
    context = (source_sha256, _digest(existing), _digest(incoming),
               _digest(previous) if previous else "", verified, profile_revision,
               snapshot_revision, incarnation)
    result = []
    for block in incoming.blocks:
        present = old.get(block.key)
        if (block.key not in LABELS or not present or not _picture_only(present)
                or not _picture_only(block) or present.asset_hashes == block.asset_hashes
                or specs.get(block.key) != new_specs.get(block.key)
                or specs.get(block.key) is None or specs[block.key].type != "image_page"):
            continue
        # Reuse the actual three-way policy: unchanged consumed source content
        # must not prompt again merely because a human edited the report later.
        narrow = lambda draft: replace(draft, blocks=tuple(b for b in draft.blocks if b.key == block.key)) if draft else None
        try:
            merge_starting_drafts(narrow(existing), narrow(incoming), narrow(previous), verified=verified)
        except ValueError:
            binding = hashlib.sha256(json.dumps((context, block.key, _digest(present), _digest(block))).encode()).hexdigest()
            result.append(ImageConflict(block.key, LABELS[block.key], present, block, binding))
    return tuple(result)


def apply_replacements(existing: ReportDraft, incoming: ReportDraft,
                       previous: ReportDraft | None, decisions: dict[str, str], **context) -> ReportDraft:
    """Validate every intent again, then replace detached blocks, not storage."""
    conflicts = {c.slot: c for c in image_conflicts(existing, incoming, previous, **context)}
    if any(slot not in conflicts or conflicts[slot].binding != binding for slot, binding in decisions.items()):
        raise ValueError("A picture or report changed after preview. Review both pictures again; your report is unchanged.")
    # Incoming is already built by the ordinary importer. Do not transplant old
    # reviews, captions, references or placement onto its independent occurrence.
    replacements = {slot: conflicts[slot].incoming for slot in decisions}
    return replace(existing, blocks=tuple(replacements.get(b.key, b) for b in existing.blocks))


@contextmanager
def snapshot_guard(profile, period, expected_revision, expected_fingerprint):
    """Hold the existing snapshot writer lock through the final import commit.

    save_report_setup independently CAS-checks the library/profile manifest.
    The separate snapshot lock prevents a report edit racing its recorded
    bootstrap_snapshot_revision. No ordinary/default save path is changed.
    """
    from app import monthly_report_library as library
    with library._locked(library._profile_path(profile.contract, profile.key, snapshots=True)):
        current = library.load_snapshot(profile.contract, profile.key, period)
        if ((current.revision if current else 0) != expected_revision
                or (current.draft.fingerprint if current else "") != expected_fingerprint):
            raise ValueError("Another report version was saved after picture review. Reopen the current report; your draft and upload are unchanged.")
        yield
