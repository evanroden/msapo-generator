"""Source corrections use canonical evidence and never alter original file bytes."""
from dataclasses import replace
from datetime import date
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app import monthly_report_upload_ui as ui
from app.monthly_report_checks import preflight
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_model import synthetic_draft
from app.monthly_report_source_details import (
    KEEP_FACILITY, correct_source_details, facility_choice,
)


APP = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_upload_ui import render_source_details
from app.monthly_report_model import synthetic_profiles

def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["_monthly_source_detail_anchors"] = set()
view = st.radio("View", ["Section", "Batch"])
source = st.session_state["source"]
source = render_source_details(source, synthetic_profiles()[0], view, field)
st.session_state["source"] = source
'''


def source_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = b"Inspected pump. Bearing replacement remains recommended."
    content, _ = sources.ingest(profile, "2026-09-DemoNorth-synthetic.txt", raw)
    content = replace(content, source=replace(content.source, service_date="", facility="",
                                             classification="Vendor service"))
    return profile, raw, content


def test_explicit_correction_retains_original_hash_text_and_page_decisions(monkeypatch, tmp_path):
    profile, raw, content = source_fixture(monkeypatch, tmp_path)
    source = replace(content.source, client_page_exclusions=((1, "original-exclusion"),))
    updated = correct_source_details(source, profile, date(2026, 9, 16), profile.facilities[0].key)
    assert updated.service_date == "2026-09-16"
    assert updated.facility == profile.facilities[0].key
    assert updated.id == source.id and updated.sha256 == source.sha256
    assert updated.page_texts == source.page_texts
    assert updated.selected_pages == source.selected_pages
    assert updated.client_page_exclusions == source.client_page_exclusions
    assert updated.fingerprint != source.fingerprint
    assert sources.source_bytes(profile, updated) == raw
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    before = {c.code for c in preflight(replace(draft, sources=(source,)))}
    after = {c.code for c in preflight(replace(draft, sources=(updated,)))}
    assert {"source_date_unknown", "source_facility"} <= before
    assert not {"source_date_unknown", "source_facility"} & after


def test_unknown_and_foreign_identity_do_not_default_to_first_site(monkeypatch, tmp_path):
    profile, _, content = source_fixture(monkeypatch, tmp_path)
    assert facility_choice(content.source, profile) == ""
    foreign = replace(content.source, facility="Synthetic Other Site")
    assert facility_choice(foreign, profile) == KEEP_FACILITY
    assert correct_source_details(foreign, profile, None, KEEP_FACILITY).facility == foreign.facility
    assert correct_source_details(content.source, profile, None, "") == content.source
    with pytest.raises(ValueError, match="exact site"):
        correct_source_details(content.source, profile, None, "foreign-site")
    with pytest.raises(ValueError, match="one source date"):
        correct_source_details(content.source, profile, (date(2026, 9, 1), date(2026, 9, 2)), "")


def test_form_edits_require_submit_and_sync_between_canonical_views(monkeypatch, tmp_path):
    profile, raw, content = source_fixture(monkeypatch, tmp_path)
    app = AppTest.from_string(APP)
    app.session_state["source"] = content.source
    app.run()
    assert not app.exception
    assert app.date_input[0].value is None
    assert app.selectbox[0].value == ""
    app.date_input[0].set_value(date(2026, 9, 16))
    app.selectbox[0].set_value(profile.facilities[0].key)
    app.run()
    assert app.session_state["source"] == content.source
    app.button[0].click().run()
    current = app.session_state["source"]
    assert current.service_date == "2026-09-16"
    assert current.facility == profile.facilities[0].key
    app.radio[0].set_value("Batch").run()
    assert app.date_input[0].value == date(2026, 9, 16)
    app.date_input[0].set_value(date(2026, 9, 18))
    app.button[0].click().run()
    app.radio[0].set_value("Section").run()
    assert not app.exception
    assert app.date_input[0].value == date(2026, 9, 18)
    assert app.session_state["source"].service_date == "2026-09-18"
    app.date_input[0].set_value(None)
    app.button[0].click().run()
    app.run()
    assert app.session_state["source"].service_date == ""
    assert app.date_input[0].value is None
    assert sources.source_bytes(profile, app.session_state["source"]) == raw


def test_stale_form_submission_cannot_restore_older_metadata(monkeypatch, tmp_path):
    profile, _, content = source_fixture(monkeypatch, tmp_path)
    app = AppTest.from_string(APP)
    app.session_state["source"] = content.source
    app.run()
    app.date_input[0].set_value(date(2026, 9, 16))
    app.session_state["source"] = replace(content.source, service_date="2026-09-22")
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["source"].service_date == "2026-09-22"
    assert app.date_input[0].value == date(2026, 9, 22)
    assert any("corrected elsewhere" in item.value for item in app.info)


def test_native_text_section_has_editable_source_details_before_page_return(monkeypatch, tmp_path):
    profile, raw, content = source_fixture(monkeypatch, tmp_path)
    stream = BytesIO(raw)
    stream.name = content.source.filename
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: [stream])
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_section_uploads
from app.monthly_report_model import ReportPeriod, synthetic_profiles
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
result, _, _ = render_section_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9),
    "test", field, "water_reports")
st.session_state["result"] = result
''').run()
    assert not app.exception
    assert len(app.date_input) == 1
    assert app.date_input[0].value is None  # Filename is deliberately not date evidence.
    app.date_input[0].set_value(date(2026, 9, 10))
    next(w for w in app.selectbox if w.label == "Source facility").set_value(profile.facilities[0].key)
    next(w for w in app.button if w.label == "Save corrected details").click().run()
    assert not app.exception
    revised = app.session_state["result"][0]
    assert revised.service_date == "2026-09-10"
    assert revised.facility == profile.facilities[0].key
    assert sources.source_bytes(profile, revised) == raw
    app.run()
    assert app.session_state["result"][0] == revised


def test_repeated_source_views_emit_one_resolver_anchor(monkeypatch, tmp_path):
    _, _, content = source_fixture(monkeypatch, tmp_path)
    app = AppTest.from_string(APP + "\nrender_source_details(source, synthetic_profiles()[0], 'other', field)")
    app.session_state["source"] = content.source
    app.run()
    assert not app.exception
    anchor = 'id="source-details-' + content.source.id + '"'
    assert sum(anchor in node.value for node in app.markdown) == 1
    app.run()
    assert sum(anchor in node.value for node in app.markdown) == 1


def test_structured_native_activity_correction_preserves_manual_text_and_original(monkeypatch, tmp_path):
    from app import monthly_report_ai as ai
    profile, raw, content = source_fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "")
    stream = BytesIO(raw)
    stream.name = content.source.filename
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: [stream])
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_structured_uploads
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_profiles
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
st.session_state["_monthly_source_detail_anchors"] = set()
blocks = st.session_state.setdefault("blocks", {"activity_summary":
    ResolvedBlock("activity_summary", "This month", text="Keep my manual correction.")})
records, additions, _ = render_structured_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9),
    "test", field, "activity_summary", blocks=blocks)
blocks.update(additions)
st.session_state["result"] = records
''').run()
    assert not app.exception
    initial_text = app.session_state["blocks"]["activity_summary"].text
    assert "Keep my manual correction." in initial_text
    app.date_input[0].set_value(date(2026, 9, 12))
    next(w for w in app.selectbox if w.label == "Source facility").set_value(profile.facilities[0].key)
    next(w for w in app.button if w.label == "Save corrected details").click().run()
    assert not app.exception
    revised = app.session_state["result"][0]
    assert revised.service_date == "2026-09-12"
    assert sources.source_bytes(profile, revised) == raw
    assert app.session_state["blocks"]["activity_summary"].text == initial_text
    app.run()
    assert app.session_state["result"][0] == revised
    assert app.session_state["blocks"]["activity_summary"].text == initial_text
