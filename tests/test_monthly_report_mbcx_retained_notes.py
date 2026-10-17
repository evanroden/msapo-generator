"""Legacy inclusion conflicts stay editable without reviving excluded notes."""
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from docx import Document
import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import DraftParagraph, ResolvedBlock


SCRIPT = '''
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_mbcx_ui import render_mbcx
from app.monthly_report_model import DraftParagraph, ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles
from app.monthly_report_setup import normalize_mbcx
from app.monthly_report_ui import _field
section=next(section for section in default_sections() if section.key=="mbcx")
initial=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),"Synthetic Editor",(section,),
    (INITIAL_STATUS, INITIAL_PAGES))
st.session_state.setdefault("original",initial)
draft=st.session_state.setdefault("draft",normalize_mbcx(initial))
blocks={block.key:block for block in draft.blocks}
spec=next(spec for spec in section.blocks if spec.key=="mbcx_report")
def edit_pages(block):
    return _edit_content(spec,block,SimpleNamespace(profile=draft.profile),"mbcx_probe",{},_field,draft)
status,pages=render_mbcx(blocks["mbcx_status"],blocks["mbcx_report"],"mbcx_probe",_field,edit_pages)
st.session_state["draft"]=replace(draft,blocks=(status,pages))
'''


def workspace(*, status=None, pages=None):
    status = status or ResolvedBlock("mbcx_status", "This month", text="Synthetic current included status.")
    pages = pages or ResolvedBlock("mbcx_report", "Omit", text="Synthetic retained earlier notes.",
                                   references=("retained-source",))
    return AppTest.from_string(SCRIPT.replace("INITIAL_STATUS", repr(status))
                               .replace("INITIAL_PAGES", repr(pages))).run()


def parts(app):
    return {block.key: block for block in app.session_state["draft"].blocks}


def textbox(app, label):
    return next(widget for widget in app.text_area if widget.label == label)


def test_conflicting_manual_notes_have_one_truthfully_named_reachable_editor():
    app = workspace()
    before = app.session_state["draft"]
    assert not app.exception
    assert [widget.label for widget in app.text_area] == ["Status or findings", "Retained page notes (left out)"]
    assert not any("Advanced layout" in widget.value for widget in (*app.warning, *app.caption, *app.info))
    assert not any(widget.value == parts(app)["mbcx_report"].text for widget in app.text)
    assert textbox(app, "Retained page notes (left out)").proto.default == parts(app)["mbcx_report"].text
    assert textbox(app, "Status or findings").proto.default == parts(app)["mbcx_status"].text
    app.run()
    assert app.session_state["draft"] == before


def test_editing_omitted_legacy_notes_preserves_exclusion_originals_and_docx_noninclusion():
    pages = ResolvedBlock("mbcx_report", "Omit", text="Synthetic excluded legacy findings.",
                          asset_hashes=("omitted-original.png",), references=("retained-source",))
    app = workspace(pages=pages)
    before = parts(app)
    original = app.session_state["original"]
    key = textbox(app, "Retained page notes (left out)").key
    textbox(app, "Retained page notes (left out)").set_value("Synthetic excluded findings corrected for later review.").run()
    current = parts(app)
    assert not app.exception and current["mbcx_report"].source == "Omit"
    assert current["mbcx_report"].text == "Synthetic excluded findings corrected for later review."
    assert current["mbcx_report"].asset_hashes == before["mbcx_report"].asset_hashes
    assert current["mbcx_report"].references == before["mbcx_report"].references
    assert current["mbcx_status"] == before["mbcx_status"]
    assert app.session_state["original"] == original
    assert textbox(app, "Retained page notes (left out)").key == key
    draft = app.session_state["draft"]
    def refuse_omitted_asset(reference):
        raise AssertionError("An omitted page reached the output asset resolver: " + reference)
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint, asset_loader=refuse_omitted_asset)
    document = Document(BytesIO(raw))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert text.count(current["mbcx_status"].text) == 1
    assert "Synthetic excluded" not in text
    with ZipFile(BytesIO(raw)) as package:
        assert b"Synthetic excluded" not in package.read("word/document.xml")


def test_editing_an_omitted_status_requires_its_existing_explicit_include_action():
    status = ResolvedBlock("mbcx_status", "Omit", text="Synthetic omitted separate update.",
                           references=("separate-source",))
    pages = ResolvedBlock("mbcx_report", "This month", text="Synthetic included page notes.",
                          references=("page-source",))
    app = workspace(status=status, pages=pages)
    textbox(app, "Status or findings").set_value("Synthetic corrected separate update.").run()
    current = parts(app)
    assert not app.exception and current["mbcx_status"].source == "Omit"
    assert current["mbcx_report"] == pages
    next(button for button in app.button if button.label == "Include this update").click().run()
    current = parts(app)
    assert not app.exception and current["mbcx_status"].source == "This month"
    assert current["mbcx_status"].text == "Synthetic corrected separate update."
    assert current["mbcx_status"].references == status.references
    assert current["mbcx_report"] == pages


@pytest.mark.parametrize("generation_key", ("mbcx_probe_rich_text_epoch", "_monthly_qa_generation"))
def test_report_reset_rejects_old_native_status_and_retained_note_values(generation_key):
    app = workspace()
    old_status = textbox(app, "Status or findings").key
    old_notes = textbox(app, "Retained page notes (left out)").key
    app.session_state[generation_key] = "new-mbcx-report-incarnation"
    current = parts(app)
    replacement = replace(app.session_state["draft"], blocks=(
        replace(current["mbcx_status"], text="Synthetic replacement status."),
        replace(current["mbcx_report"], text="Synthetic replacement retained notes.")))
    app.session_state["draft"] = replacement
    app.session_state[old_status] = "Stale previous status"
    app.session_state[old_notes] = "Stale previous retained notes"
    app.run()
    assert not app.exception and app.session_state["draft"] == replacement
    assert textbox(app, "Status or findings").key != old_status
    assert textbox(app, "Retained page notes (left out)").key != old_notes


def test_changed_source_rejects_old_note_value_while_ordinary_edits_keep_the_native_identity():
    app = workspace()
    old = textbox(app, "Retained page notes (left out)").key
    current = parts(app)
    replacement = replace(app.session_state["draft"], blocks=(current["mbcx_status"],
        replace(current["mbcx_report"], text="Synthetic changed source notes.", references=("changed-source",))))
    app.session_state["draft"] = replacement
    app.session_state[old] = "Stale source notes"
    app.run()
    assert not app.exception and app.session_state["draft"] == replacement
    assert textbox(app, "Retained page notes (left out)").key != old
    key = textbox(app, "Retained page notes (left out)").key
    textbox(app, "Retained page notes (left out)").set_value("Synthetic current correction.").run()
    assert textbox(app, "Retained page notes (left out)").key == key
    assert parts(app)["mbcx_report"].source == "Omit"


def test_omitted_linked_page_notes_keep_their_provenance_without_a_competing_textbox():
    paragraph = DraftParagraph("Synthetic excluded source-linked result.", ("fact-one",), ("source-one:1",))
    pages = ResolvedBlock("mbcx_report", "Omit", text="- " + paragraph.text,
                          ai_written=True, ai_paragraphs=(paragraph,), references=("source-one:1",),
                          ai_evidence_fingerprint="retained-evidence")
    app = workspace(pages=pages)
    assert not app.exception and [widget.label for widget in app.text_area] == ["Status or findings"]
    assert parts(app)["mbcx_report"] == pages
    assert any(widget.value == pages.text for widget in app.text)
    assert not any("wording and sources editor above" in widget.value for widget in app.caption)
    assert not any(button.label == "Include retained notes" for button in app.button)


def test_include_update_action_is_bound_to_the_report_incarnation():
    status = ResolvedBlock("mbcx_status", "Omit", text="Synthetic omitted separate update.")
    pages = ResolvedBlock("mbcx_report", "This month", text="Synthetic included page notes.")
    app = workspace(status=status, pages=pages)
    old = next(button for button in app.button if button.label == "Include this update").key
    app.session_state["mbcx_probe_rich_text_epoch"] = "new-identical-report"
    app.run()
    new = next(button for button in app.button if button.label == "Include this update").key
    assert new != old and parts(app)["mbcx_status"].source == "Omit"
