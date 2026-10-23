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


def test_a_profile_excluded_section_missing_from_an_older_draft_stays_left_out():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    retained = ResolvedBlock("training_summary", "This month", text="Synthetic retained training notes.")
    draft = replace(draft, profile=replace(draft.profile, excluded_sections=("training",)),
                    sections=tuple(section for section in draft.sections if section.key != "training"),
                    blocks=(*draft.blocks, retained))
    after = complete_guided_sections(draft)
    assert any(section.key == "training" and section.included for section in after.sections)
    assert _blocks(after)["training_summary"] == replace(retained, source="Omit")


def test_a_confirmed_proposal_stays_confirmed_when_its_section_is_left_out():
    from app.monthly_report_followups import confirmation, problems
    draft = _draft()
    proposal = ReportFollowUp("synthetic-proposal", "proposal", "Synthetic carried proposal.", "August 2026",
                              status="pending")
    unconfirmed = ReportFollowUp("synthetic-open-proposal", "proposal", "Synthetic unreviewed proposal.",
                                 "August 2026", status="pending")
    draft = replace(draft, sections=tuple(replace(section, included=False) if section.key == "proposals" else section
                                          for section in draft.sections),
                    follow_ups=(replace(proposal, reviewed_fingerprint=confirmation(proposal, draft.period)), unconfirmed))
    after = complete_guided_sections(draft)
    confirmed, still_open = after.follow_ups
    assert not confirmed.included and not problems(confirmed, after)
    assert not still_open.included and any("Confirm this proposal" in message for message in problems(still_open, after))


def test_a_table_frame_with_no_rows_is_not_content():
    from app.monthly_report_model import ReportTable
    draft = _draft()
    frame = ResolvedBlock("demo_training", "This month", extra_tables=(ReportTable(("Topic",), ()),),
                          rows=((" ",),))
    draft = replace(draft, blocks=tuple(frame if block.key == "demo_training" else block for block in draft.blocks))
    assert _blocks(complete_guided_sections(draft))["demo_training"] == frame


INCLUDE_APP = """
import streamlit as st
from dataclasses import replace
from app.monthly_report_ai_ui import edit_linked_paragraphs
from app.monthly_report_model import DraftParagraph, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field

draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
paragraph = (DraftParagraph("Synthetic inspected chiller.", (), ()),)
blocks = {key: ResolvedBlock(key, "Omit", text="- Synthetic inspected chiller.", ai_paragraphs=paragraph,
                             ai_written=True, reviewed_fingerprint="synthetic-reviewed")
          for key in ("activity_summary", "mbcx_report")}
st.session_state["result"] = edit_linked_paragraphs(draft, blocks, "qa_left_out_linked", _field)
"""


def test_left_out_source_linked_wording_can_be_included_again():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string(INCLUDE_APP, default_timeout=15).run()
    assert not app.exception
    buttons = [button for button in app.button if button.label == "Include in this report"]
    assert len(buttons) == 1  # MBCx keeps its own retained-notes control
    buttons[0].click().run()
    result = app.session_state["result"]
    assert result["activity_summary"].source == "This month" and not result["activity_summary"].reviewed
    assert result["activity_summary"].ai_paragraphs[0].text == "Synthetic inspected chiller."
    assert result["mbcx_report"].source == "Omit"


def test_legacy_issue_prose_of_a_left_out_section_becomes_left_out_issues():
    from app.monthly_report_model import ReportDraft, default_sections
    sections = tuple(replace(section, included=False) if section.key == "issues" else section
                     for section in default_sections())
    prose = ResolvedBlock("equipment_issues", "This month", text="- Synthetic chiller leak.\n- Synthetic belt noise.")
    draft = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Operator", sections, (prose,),
                        synthetic=True)
    after = complete_guided_sections(draft)
    issues = [item for item in after.follow_ups if item.category == "issue"]
    assert [item.text for item in issues] == ["Synthetic chiller leak.", "Synthetic belt noise."]
    assert not any(item.included for item in issues)  # left out, and each can be included again
    assert "Synthetic" not in _blocks(after)["equipment_issues"].text
    assert complete_guided_sections(after) == after


TABLE_APP = """
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ReportTable, ResolvedBlock
from app.monthly_report_ui import _field

table = ReportTable(("Vendor", "Scope"), (("Synthetic Vendor", "Chiller service"),))
block = ResolvedBlock("subcontractor_matrix", "Omit", extra_tables=(table,))
st.session_state["result"] = _edit_content(BlockSpec("subcontractor_matrix", "table"), block, None,
                                           "qa_left_out_table", {}, _field)
"""


def test_an_explicit_row_edit_includes_a_left_out_imported_table_again(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_guided as guided
    app = AppTest.from_string(TABLE_APP, default_timeout=15).run()
    assert not app.exception
    assert app.session_state["result"].source == "Omit"  # showing it changes nothing
    monkeypatch.setattr(guided, "_grid", lambda key, rows, **kwargs: [
        dict(row, Scope="Synthetic boiler service") for row in rows])
    app.run()
    result = app.session_state["result"]
    assert result.source == "This month"
    assert result.extra_tables[0].rows == (("Synthetic Vendor", "Synthetic boiler service"),)


ATTACHED_APP = """
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field

draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
blocks = st.session_state.setdefault("blocks", {
    "vendor_reports": ResolvedBlock("vendor_reports", "Omit", asset_hashes=("synthetic-vendor-page.png",),
                                    asset_captions=("Synthetic vendor page",)),
    "improvements": ResolvedBlock("improvements", "Omit", asset_hashes=("synthetic-photo.png",),
                                  asset_captions=("Synthetic improvement",)),
    "mbcx_report": ResolvedBlock("mbcx_report", "Omit", asset_hashes=("synthetic-mbcx.png",)),
    "end_of_life": ResolvedBlock("end_of_life", "Omit")})
for key, kind in (("vendor_reports", "pdf_pages"), ("improvements", "image_grid"),
                  ("mbcx_report", "pdf_pages"), ("end_of_life", "table")):
    blocks[key] = _edit_content(BlockSpec(key, kind), blocks[key], None, "qa_left_out_pages", {}, _field,
                                draft if kind == "image_grid" else None, manage_saved_pictures=False)
"""


def test_left_out_attached_pages_and_photos_can_be_included_without_uploading_again():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string(ATTACHED_APP, default_timeout=15).run()
    assert not app.exception
    include = [button.key for button in app.button if button.label == "Include in this report"]
    assert len(include) == 2  # MBCx keeps its own control; an empty block has nothing to include
    for key in include:
        app.button(key).click().run()
    app.run()
    blocks = app.session_state["blocks"]
    for key in ("vendor_reports", "improvements"):
        assert blocks[key].source == "This month" and blocks[key].asset_hashes  # the retained pages, as they were
    assert blocks["mbcx_report"].source == "Omit" and blocks["end_of_life"].source == "Omit"
    assert not any(button.label == "Include in this report" for button in app.button)
