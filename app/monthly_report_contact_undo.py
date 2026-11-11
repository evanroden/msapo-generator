"""Report-local Undo for one explicit reviewed directory contact-table replacement.

An Undo receipt owns *only* the contact block and contact-specific section
metadata touched by the application. It cannot replace a newer contact edit,
another report's records, or unrelated later section/chart/workflow changes.
Nothing here writes to the shared contract directory or report history.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
)


_KEY = "contact_matrix"
_STALE = ("The contact table or report changed after the directory update. "
          "Undo cannot overwrite those later changes.")


@dataclass(frozen=True)
class ContactSectionUndo:
    key: str
    before_spec: BlockSpec
    after_spec: BlockSpec
    before_included: bool
    after_included: bool


@dataclass(frozen=True)
class ContactUndoReceipt:
    profile: ReportProfile
    period: ReportPeriod
    before_block: ResolvedBlock | None
    after_block: ResolvedBlock
    section_changes: tuple[ContactSectionUndo, ...]


def _contact_block(draft):
    blocks = [b for b in draft.blocks if b.key == _KEY]
    if len(blocks) > 1:
        raise ValueError("The report has duplicate contact blocks. Review before continuing.")
    return blocks[0] if blocks else None


def _contact_sections(draft):
    found = {}
    for section in draft.sections:
        contact = [b for b in section.blocks if b.key == _KEY]
        if len(contact) > 1 or section.key in found:
            raise ValueError("The report's contact section is ambiguous.")
        if contact:
            found[section.key] = (section, contact[0])
    return found


def capture_contact_undo(before: ReportDraft, applied: ReportDraft) -> ContactUndoReceipt:
    """Prepare a scoped receipt *after* the authoritative apply_contacts."""
    if before.profile != applied.profile or before.period != applied.period:
        raise ValueError("A contact Undo must remain in the same report and month.")
    original_sections = _contact_sections(before)
    applied_sections = _contact_sections(applied)
    if not original_sections or original_sections.keys() != applied_sections.keys():
        raise ValueError("Contact section identity changed during the directory update.")
    new = _contact_block(applied)
    if new is None:
        raise ValueError("A directory update did not produce an editable contact table.")
    changes = tuple(ContactSectionUndo(
        key, original_sections[key][1], applied_sections[key][1],
        original_sections[key][0].included, applied_sections[key][0].included,
    ) for key in original_sections)
    return ContactUndoReceipt(before.profile, before.period,
                              _contact_block(before), new, changes)


def contact_undo_ready(draft: ReportDraft, receipt: ContactUndoReceipt) -> bool:
    """Never use a historical session tuple as an authority to undo new work."""
    if (not isinstance(receipt, ContactUndoReceipt)
            or draft.profile != receipt.profile or draft.period != receipt.period):
        return False
    try:
        if _contact_block(draft) != receipt.after_block:
            return False
        now = _contact_sections(draft)
    except ValueError:
        return False
    if set(now) != {delta.key for delta in receipt.section_changes}:
        return False
    for delta in receipt.section_changes:
        section, current_spec = now[delta.key]
        if current_spec != delta.after_spec:
            return False
        if (delta.before_included != delta.after_included
                and section.included != delta.after_included):
            # The directory application enabled this section. A subsequent
            # Include/Omit action makes that old undo receipt stale.
            return False
    return True


def undo_contact_update(draft: ReportDraft, receipt: ContactUndoReceipt) -> ReportDraft:
    """Undo only our exact contact changes, preserving all independent edits."""
    if not contact_undo_ready(draft, receipt):
        raise ValueError(_STALE)
    deltas = {item.key: item for item in receipt.section_changes}
    sections = []
    for section in draft.sections:
        delta = deltas.get(section.key)
        if delta is None:
            sections.append(section)
            continue
        # Other specs inside the Organization section can have been edited
        # since Apply; restore only the specific contact spec we introduced.
        blocks = tuple(delta.before_spec if b.key == _KEY else b for b in section.blocks)
        included = (delta.before_included
                    if delta.before_included != delta.after_included else section.included)
        sections.append(replace(section, blocks=blocks, included=included))
    blocks = []
    for block in draft.blocks:
        if block.key == _KEY:
            if receipt.before_block is not None:
                blocks.append(receipt.before_block)
        else:
            blocks.append(block)
    return replace(draft, blocks=tuple(blocks), sections=tuple(sections))
