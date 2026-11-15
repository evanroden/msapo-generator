"""Report-local, identity-bound Undo of an explicit shared-directory contact Apply.

Undo does not roll back shared directory history. It only restores the
directory-owned contact prefix and provenance in the active working report.
Late report-authored rows, notes, images and unrelated section edits survive.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
)

UNDO_MARKER = "report-directory-undo:explicit"


def _directory_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(ref for ref in refs
                 if ref.startswith(("directory:", "directory-site:")))


def retire_inactive_directory_undo_receipts(session, active_key: str) -> None:
    """Discard report-local Undo controls for previously visited reports/months.

    Guided workspaces use different prefixes per contract, report and month;
    comparing a receipt to the *current* profile alone never sees an old key.
    Do not touch native row Undo or other unrelated session records.
    """
    for key in tuple(session):
        if (isinstance(key, str) and key.endswith("_directory_apply_undo")
                and key != active_key):
            session.pop(key, None)


def _report_scope(profile: ReportProfile) -> tuple:
    # The title, layout and presentation metadata are independent report
    # edits. Bind Undo to the contract/report/site identities instead.
    return (profile.contract, profile.key, profile.scope_type, profile.facilities)


def _contact(draft: ReportDraft) -> ResolvedBlock | None:
    return next((block for block in draft.blocks if block.key == "contact_matrix"), None)


def _contact_specs(draft: ReportDraft) -> tuple[tuple[str, BlockSpec, bool], ...]:
    return tuple((section.key, spec, section.included)
                 for section in draft.sections for spec in section.blocks
                 if spec.key == "contact_matrix")


@dataclass(frozen=True)
class DirectoryApplyUndo:
    profile: ReportProfile
    period: ReportPeriod
    previous_source: str
    previous_owned_rows: tuple[tuple[str, ...], ...]
    applied_owned_rows: tuple[tuple[str, ...], ...]
    previous_directory_refs: tuple[str, ...]
    applied_directory_refs: tuple[str, ...]
    applied_source: str
    previous_specs: tuple[tuple[str, BlockSpec, bool], ...]
    applied_specs: tuple[tuple[str, BlockSpec, bool], ...]
    had_previous_block: bool


def capture_directory_apply(
    before: ReportDraft, after: ReportDraft, applied_directory_rows: int,
) -> DirectoryApplyUndo:
    """Capture the exact mutation after a successful explicit Apply.

    Row counts, rather than names, distinguish directory rows from the
    report-owned suffix. An ambiguous/non-append-only result is not undoable.
    """
    if before.profile != after.profile or before.period != after.period:
        raise ValueError("The report identity changed during directory Apply.")
    previous, applied = _contact(before), _contact(after)
    if applied is None or applied_directory_rows < 0 or applied_directory_rows > len(applied.rows):
        raise ValueError("Cannot identify the applied directory contact rows.")
    tail = applied.rows[applied_directory_rows:]
    previous_rows = previous.rows if previous else ()
    count = len(previous_rows) - len(tail)
    if count < 0 or previous_rows[count:] != tail:
        raise ValueError("Cannot prove which contact rows the directory replaced.")
    after_refs = _directory_refs(applied.references)
    if not after_refs or not any(ref.startswith("directory:") for ref in after_refs):
        raise ValueError("The applied contacts lack verified directory provenance.")
    old_specs, new_specs = _contact_specs(before), _contact_specs(after)
    if not old_specs or tuple(key for key, _, _ in old_specs) != tuple(
        key for key, _, _ in new_specs
    ):
        raise ValueError("The report contact destination changed during Apply.")
    return DirectoryApplyUndo(
        profile=before.profile, period=before.period,
        previous_source=previous.source if previous else "Omit",
        previous_owned_rows=previous_rows[:count],
        applied_owned_rows=applied.rows[:applied_directory_rows],
        previous_directory_refs=_directory_refs(previous.references) if previous else (),
        applied_directory_refs=after_refs,
        applied_source=applied.source,
        previous_specs=old_specs,
        applied_specs=new_specs,
        had_previous_block=previous is not None,
    )


def undo_directory_apply(draft: ReportDraft, receipt: DirectoryApplyUndo) -> ReportDraft:
    """Revert only the acknowledged directory-owned delta, or refuse stale work.

    A subsequent local row addition/edit in the suffix is preserved. Changes
    to directory-owned rows, links, source or contact layout are a conflict.
    Directory revisions and all other report blocks are never rewritten.
    """
    if not isinstance(receipt, DirectoryApplyUndo):
        raise ValueError("A legacy directory Undo receipt cannot be verified.")
    if (_report_scope(draft.profile) != _report_scope(receipt.profile)
            or draft.period != receipt.period):
        raise ValueError("This directory Undo belongs to another report or month.")
    current = _contact(draft)
    length = len(receipt.applied_owned_rows)
    if (current is None or current.source != receipt.applied_source
            or len(current.rows) < length
            or current.rows[:length] != receipt.applied_owned_rows
            or _directory_refs(current.references) != receipt.applied_directory_refs):
        raise ValueError("Directory-owned contacts changed after Apply. Review them before Undo.")
    now_specs = _contact_specs(draft)
    if now_specs != receipt.applied_specs:
        raise ValueError("The contact layout changed after Apply. Review it before Undo.")

    # Retain all later report-only contact rows, even when they were edited,
    # and every later report-only note/extra table/asset/reference.
    rows = (*receipt.previous_owned_rows, *current.rows[length:])
    other_refs = tuple(ref for ref in current.references
                       if not ref.startswith(("directory:", "directory-site:"))
                       and ref != UNDO_MARKER)
    refs = tuple(dict.fromkeys((
        *receipt.previous_directory_refs, *other_refs, UNDO_MARKER,
    )))
    source = receipt.previous_source if receipt.had_previous_block else "This month"
    # Apply only admits an empty, unreviewed Omit placeholder. Do not restore
    # that placeholder over report-only notes or rows added after Apply: such
    # work must remain visible and a later explicit reapply must stay possible.
    # The marker prevents silent auto-fill without changing directory history.
    if source == "Omit" and not receipt.previous_directory_refs:
        source = "This month"
    restored = replace(
        current, source=source, rows=rows, references=refs,
        reviewed_fingerprint="", client_reviewed_fingerprint="",
    )
    old_specs = {key: (spec, included) for key, spec, included in receipt.previous_specs}
    sections = tuple(
        replace(section, included=old_specs[section.key][1],
                blocks=tuple(old_specs[section.key][0] if spec.key == "contact_matrix"
                             else spec for spec in section.blocks))
        if section.key in old_specs else section
        for section in draft.sections
    )
    blocks = tuple(restored if block.key == "contact_matrix" else block
                   for block in draft.blocks)
    return replace(draft, sections=sections, blocks=blocks)
