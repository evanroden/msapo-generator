"""One visible source task, explicit destination and safe cross-section reuse.

Synthetic native AppTests use the unchanged production uploader/source keys.
Original bytes and existing report content are never overwritten by a passive
view or an uncommitted destination choice.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_section_uploads import source_destinations
from test_monthly_report_section_uploads import APP as SECTION_APP
from test_monthly_report_sources import pdf_bytes


BATCH_APP = """
import streamlit as st
from app.monthly_report_upload_ui import render_uploads
from app.monthly_report_model import ReportPeriod, synthetic_profiles

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

srcs, blocks, specs = render_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9),
    'routing_test', field, retain_accepted=True, show_intake=False)
st.session_state['routing_result'] = (srcs, blocks, specs)
"""


def batch_source(monkeypatch, tmp_path, *, filename="synthetic-vendor.pdf", pages=1):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, filename, pdf_bytes(pages))
    source = replace(content.source, classification="Vendor service",
                     facility=profile.facilities[0].title,
                     selected_pages=tuple(range(1, pages + 1)),
                     captions=tuple((n, "Synthetic equipment work on page " + str(n))
                                    for n in range(1, pages + 1)))
    source = replace(source, client_page_reviews=tuple(
        (n, page_fingerprint(source, n)) for n in source.selected_pages))
    assert all(page_allowed(source, n) for n in source.selected_pages)
    return replace(content, source=source)


def source_app(monkeypatch, tmp_path, *contents):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(SECTION_APP, default_timeout=30)
    app.session_state["synthetic_evidence"] = tuple(contents)
    app.run()
    assert not app.exception
    return app


def batch_app(monkeypatch, tmp_path, *contents):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(BATCH_APP, default_timeout=30)
    app.session_state["routing_test_evidence"] = tuple(contents)
    app.run()
    assert not app.exception
    return app


def text_lines(app):
    return [entry.value for entry in app.text]


@pytest.mark.parametrize("section", ["vendor_reports", "water_reports",
                                     "mbcx_report", "utility_analysis"])
def test_all_section_source_uploads_are_visible_without_a_popover(monkeypatch, tmp_path, section):
    app = source_app(monkeypatch, tmp_path)
    app.radio[0].set_value(section).run()
    assert not app.exception
    assert "Upload new" in text_lines(app)
    assert len(app.get("file_uploader")) == 1
    assert app.get("file_uploader")[0].proto.id.endswith(
        "_section_" + section + "_upload")
    assert not any(pop.proto.popover.label == "Add files" for pop in app.get("popover"))
    assert not any(e.label == "Use an uploaded file" for e in app.expander)
    assert not app.session_state["test_sources"]
    assert not app.session_state["test_blocks"]


def test_unassigned_previous_file_is_selectable_without_nested_disclosure(
        monkeypatch, tmp_path):
    content = batch_source(monkeypatch, tmp_path)
    content = replace(content, source=replace(content.source, classification="Reference only"))
    assert source_destinations((content,), {}, {})[content.source.id] == set()
    before = content.source
    app = source_app(monkeypatch, tmp_path, content)
    assert "Upload new" in text_lines(app)
    assert "Already uploaded" in text_lines(app)
    assert not any(e.label == "Use an uploaded file" for e in app.expander)
    assert next(s for s in app.selectbox if s.label == "Saved file").value == before.id
    assert not app.session_state["test_blocks"]
    app.run()
    assert app.session_state["synthetic_evidence_section_routes"] == {}
    next(b for b in app.button if b.label == "Use in Supporting service reports").click().run()
    assert not app.exception
    assert app.session_state["synthetic_evidence_section_routes"] == {
        before.id: "vendor_reports",
    }
    assert app.session_state["test_sources"][0].sha256 == before.sha256
    assert not app.session_state["test_blocks"]  # Reuse never approves pages.
    assert not any(e.label == "Use an uploaded file" for e in app.expander)


def test_mixed_unassigned_files_reuse_only_exact_chosen_source(
        monkeypatch, tmp_path):
    first = batch_source(monkeypatch, tmp_path, filename="north.pdf", pages=1)
    second = batch_source(monkeypatch, tmp_path, filename="south.pdf", pages=2)
    first = replace(first, source=replace(first.source, classification="Reference only"))
    second = replace(second, source=replace(second.source, classification="Reference only"))
    app = source_app(monkeypatch, tmp_path, first, second)
    assert not app.exception
    choose = next(s for s in app.selectbox if s.label == "Saved file")
    choose.set_value(second.source.id).run()
    assert not app.exception
    next(b for b in app.button if b.label == "Use in Supporting service reports").click().run()
    assert not app.exception
    assert app.session_state["synthetic_evidence_section_routes"] == {
        second.source.id: "vendor_reports",
    }
    assert first.source.id != second.source.id
    assert not app.session_state["test_blocks"]
    assert {s.sha256 for s in app.session_state["test_sources"]} == {
        first.source.sha256, second.source.sha256,
    }


def test_inferred_vendor_destination_is_visible_and_cancel_never_commits(
        monkeypatch, tmp_path):
    content = batch_source(monkeypatch, tmp_path)
    app = batch_app(monkeypatch, tmp_path, content)
    filename = content.source.filename
    assert any(filename in value and "Monthly activity" in value
               for value in text_lines(app))
    assert any(e.label == "Change destination (optional)" for e in app.expander)
    selector = next(s for s in app.selectbox
                    if s.label == "Report section for " + filename)
    assert selector.value == "improvements"
    assert app.session_state["routing_result"][1] == {}
    assert app.session_state["routing_test_evidence"][0].source.sha256 == content.source.sha256
    # No Add click means no image, page or report block is prepared or saved.
    app.run()
    assert not app.exception
    assert app.session_state["routing_result"][1] == {}
    assert not any(item.value.startswith(filename + " → Maintenance") for item in app.text)
    assert app.session_state["routing_test_evidence"][0].source.classification == "Vendor service"


def test_explicit_destination_change_is_bound_to_same_source_and_actual_add(
        monkeypatch, tmp_path):
    content = batch_source(monkeypatch, tmp_path)
    app = batch_app(monkeypatch, tmp_path, content)
    selector = next(s for s in app.selectbox
                    if s.label == "Report section for " + content.source.filename)
    selector.set_value("vendor_reports").run()
    assert not app.exception
    assert any(content.source.filename in value and "ENFRA onsite work only" in value
               for value in text_lines(app))
    assert app.session_state["routing_result"][1] == {}
    app.run()
    assert next(s for s in app.selectbox
                if s.label == "Report section for " + content.source.filename).value == "vendor_reports"
    button = next(b for b in app.button
                  if b.label == "Add selected pages and tables to report")
    assert not button.disabled
    button.click().run()
    assert not app.exception
    srcs, blocks, specs = app.session_state["routing_result"]
    assert "vendor_reports" in blocks and "improvements" not in blocks
    assert blocks["vendor_reports"].references == (
        sources.source_reference(srcs[0], 1),
    )
    assert srcs[0].classification == "Vendor service"  # Routing != reclassification.
    assert srcs[0].sha256 == content.source.sha256
    assert blocks["vendor_reports"].asset_hashes
    before=blocks["vendor_reports"]
    app.run()
    assert not app.exception
    assert app.session_state["routing_result"][1]["vendor_reports"] == before


def test_legacy_vendor_placement_is_never_auto_moved(monkeypatch, tmp_path):
    content = batch_source(monkeypatch, tmp_path)
    profile = synthetic_profiles()[0]
    block, = sources.prepare_pages(
        profile, (content,), ((content.source.id, "vendor_reports"),))
    from app.monthly_report_section_uploads import section_contents
    owners = source_destinations((content,), {}, {"vendor_reports": block})
    assert owners[content.source.id] == {"vendor_reports"}
    assert not section_contents((content,), "improvements", {},
                                {"vendor_reports": block})
