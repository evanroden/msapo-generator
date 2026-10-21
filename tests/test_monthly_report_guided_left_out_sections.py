"""A section the user left out is never republished by the guided editor (Refs #297).

`complete_guided_sections` makes every standard section present on each
render. A section that was excluded now keeps its content left out (Omit)
instead of returning to the report; empty blocks and included sections are
unchanged. Synthetic values only.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document

from app.monthly_report_docx import _build_docx
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_model import (BlockSpec, ReportFollowUp, ReportPeriod, ResolvedBlock, SectionSpec,
                                      synthetic_draft, synthetic_profiles)

EXCLUDED_TEXT = "Synthetic training notes the user left out."


def _draft():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    blocks = tuple(replace(block, source="This month", text=EXCLUDED_TEXT) if block.key == "demo_training" else block
                   for block in draft.blocks)
    sections = tuple(replace(section, included=False) if section.key == "training" else section
                     for section in draft.sections)
    return replace(draft, blocks=blocks, sections=sections)


def _blocks(draft):
    return {block.key: block for block in draft.blocks}


def test_a_left_out_section_keeps_its_content_left_out():
    before = _draft()
    after = complete_guided_sections(before)
    assert all(section.included for section in after.sections)
    training = _blocks(after)["demo_training"]
    assert training.source == "Omit" and training.text == EXCLUDED_TEXT  # retained, not deleted
    unchanged = {key: block for key, block in _blocks(before).items() if key != "demo_training"}
    assert {key: _blocks(after)[key] for key in unchanged} == unchanged
    assert complete_guided_sections(after) == after  # every later render is stable


def test_a_left_out_section_never_reaches_the_word_file():
    text = "\n".join(paragraph.text for paragraph in
                     Document(BytesIO(_build_docx(complete_guided_sections(_draft())))).paragraphs)
    assert EXCLUDED_TEXT not in text
    assert "This section demonstrates the report layout." in text  # included sections still print


def test_an_empty_left_out_block_is_not_marked():
    draft = _draft()
    empty = ResolvedBlock("demo_training", "This month")
    draft = replace(draft, blocks=tuple(empty if block.key == "demo_training" else block for block in draft.blocks))
    assert _blocks(complete_guided_sections(draft))["demo_training"] == empty


def _with_rfi_text(draft):
    return replace(draft, blocks=tuple(replace(block, source="This month", text="Synthetic RFI request.")
                                       if block.key == "demo_rfi" else block for block in draft.blocks))


def test_an_appendix_that_is_only_off_by_default_is_not_a_users_choice():
    after = complete_guided_sections(_with_rfi_text(_draft()))
    assert _blocks(after)["demo_rfi"].source == "This month"  # unchanged behaviour


def test_an_appendix_the_profile_excluded_stays_left_out():
    draft = _with_rfi_text(_draft())
    draft = replace(draft, profile=replace(draft.profile, excluded_sections=("rfi",)))
    rfi = _blocks(complete_guided_sections(draft))["demo_rfi"]
    assert rfi.source == "Omit" and rfi.text == "Synthetic RFI request."


def test_carried_items_of_a_left_out_section_stay_left_out():
    draft = _draft()
    issue = ReportFollowUp("synthetic-issue", "issue", "Synthetic carried issue.", "August 2026")
    proposal = ReportFollowUp("synthetic-proposal", "proposal", "Synthetic carried proposal.", "August 2026")
    draft = replace(draft, follow_ups=(issue, proposal), sections=tuple(
        replace(section, included=False) if section.key == "issues" else section for section in draft.sections))
    after = complete_guided_sections(draft)
    assert after.follow_ups == (replace(issue, included=False), proposal)  # kept, left out, re-includable


def test_a_left_out_block_cancels_its_pending_library_replacement():
    draft = _draft()
    draft = replace(draft, blocks=tuple(replace(block, pending_library_save=True) if block.key == "demo_training"
                                        else block for block in draft.blocks))
    training = _blocks(complete_guided_sections(draft))["demo_training"]
    assert training.source == "Omit" and not training.pending_library_save and training.text == EXCLUDED_TEXT


def test_a_normally_on_optional_section_left_out_stays_left_out():
    draft = _draft()
    receivable = SectionSpec("accounts_receivable", "", "Accounts Receivable",
                             (BlockSpec("accounts_receivable_notes", "rich_text"),), included=False)
    notes = ResolvedBlock("accounts_receivable_notes", "This month", text="Synthetic receivable notes.")
    draft = replace(draft, sections=(*draft.sections, receivable), blocks=(*draft.blocks, notes))
    assert _blocks(complete_guided_sections(draft))["accounts_receivable_notes"].source == "Omit"
