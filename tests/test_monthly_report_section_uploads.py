"""Section uploads preserve canonical sources and append only reviewed new pages."""

from dataclasses import replace
from io import BytesIO

import fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources, monthly_report_upload_ui as ui
from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from app.monthly_report_section_uploads import prepare_section_pages, section_contents, source_destinations
from test_monthly_report_sources import pdf_bytes


def reviewed_content(monkeypatch, tmp_path, pages=2):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-service.pdf", pdf_bytes(pages))
    source = replace(content.source, client_page_reviews=tuple(
        (n, page_fingerprint(content.source, n)) for n in range(1, pages + 1)))
    return profile, replace(content, source=source)


def test_append_only_new_page_preserves_exact_source_provenance(monkeypatch, tmp_path):
    profile, content = reviewed_content(monkeypatch, tmp_path)
    blocks = sources.prepare_pages(profile, (content,), ((content.source.id, "water_reports"),))
    existing = replace(blocks[0], asset_hashes=blocks[0].asset_hashes[:1],
                       asset_captions=blocks[0].asset_captions[:1], references=blocks[0].references[:1],
                       asset_provenance=blocks[0].asset_provenance[:1], text="Keep this entered note.")
    additions = prepare_section_pages(profile, (content,), "water_reports", {existing.key: existing})
    result = additions["water_reports"]
    assert result.asset_hashes == blocks[0].asset_hashes[1:]
    assert result.references == (sources.source_reference(content.source, 2),)
    assert result.asset_provenance == blocks[0].asset_provenance[1:]
    assert not pending_asset_indexes(result)
    assert existing.text == "Keep this entered note."
    assert prepare_section_pages(profile, (content,), "water_reports", {blocks[0].key: blocks[0]}) == {}


def test_existing_source_owner_beats_route_and_classification(monkeypatch, tmp_path):
    profile, content = reviewed_content(monkeypatch, tmp_path)
    original_classification = content.source.classification
    block, = sources.prepare_pages(profile, (content,), ((content.source.id, "water_reports"),))
    bindings = {content.source.id: "vendor_reports"}
    assert section_contents((content,), "vendor_reports", bindings, {block.key: block}) == ()
    assert source_destinations((content,), bindings, {block.key: block})[content.source.id] == {"water_reports"}
    with pytest.raises(ValueError, match="another section"):
        prepare_section_pages(profile, (content,), "vendor_reports", {block.key: block})
    assert content.source.classification == original_classification


def test_review_and_total_report_limits_remain_enforced(monkeypatch, tmp_path):
    profile, content = reviewed_content(monkeypatch, tmp_path)
    unreviewed = replace(content, source=replace(content.source, client_page_reviews=()))
    with pytest.raises(ValueError, match="Check page 1"):
        prepare_section_pages(profile, (unreviewed,), "mbcx_report", {})
    existing = ResolvedBlock("vendor_reports", "This month", asset_hashes=("synthetic.png",) * 149)
    with pytest.raises(ValueError, match="150"):
        prepare_section_pages(profile, (content,), "mbcx_report", {existing.key: existing})


def test_page_budget_includes_unsaved_assets_in_other_sections(monkeypatch, tmp_path):
    profile, content = reviewed_content(monkeypatch, tmp_path, pages=1)
    existing = ResolvedBlock("vendor_reports", "This month", asset_hashes=("synthetic.png",))
    with pytest.raises(ValueError, match="60 MB"):
        prepare_section_pages(profile, (content,), "mbcx_report", {existing.key: existing},
                              {"synthetic.png": b"x" * (60 * 1024 * 1024)})


APP = '''
import streamlit as st
from app.monthly_report_upload_ui import render_section_uploads
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_setup import merge_blocks
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
destination = st.radio("Section", ["vendor_reports", "water_reports", "mbcx_report", "utility_analysis"])
blocks = st.session_state.setdefault("test_blocks", {})
sources, additions, specs = render_section_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9),
    "synthetic", field, destination, blocks=blocks)
st.session_state["test_sources"] = sources
st.session_state["test_additions"] = additions
if additions:
    st.session_state["test_apply_count"] = st.session_state.get("test_apply_count", 0) + 1
    for key, block in additions.items():
        blocks[key] = merge_blocks(blocks.get(key), block)
'''


def button(app, label):
    return next(w for w in app.button if w.label == label)


def section_app(monkeypatch, tmp_path, raw, label="Service report files"):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    stream = BytesIO(raw)
    stream.name = "synthetic.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda name, **kwargs: [stream] if name == label else [])
    return AppTest.from_string(APP, default_timeout=20).run()


def test_section_workflow_reads_once_reviews_and_applies_without_chain(monkeypatch, tmp_path):
    calls = []
    original = sources.ingest_batch
    def ingest(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(sources, "ingest_batch", ingest)
    app = section_app(monkeypatch, tmp_path, pdf_bytes(2))
    assert not app.exception
    assert len(calls) == 1
    assert not any(w.label in ("Read monthly files", "Prepare selected pages") for w in app.button)
    assert not any(w.label.startswith("Add synthetic") for w in app.selectbox)
    assert not app.multiselect
    assert button(app, "Add reviewed pages").disabled
    button(app, "Include page and continue").click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    button(app, "Leave page out and continue").click().run()
    assert not button(app, "Add reviewed pages").disabled
    button(app, "Add reviewed pages").click().run()
    assert not app.exception
    assert len(app.session_state["test_blocks"]["vendor_reports"].asset_hashes) == 1
    assert app.session_state["test_sources"][0].selected_pages == (1,)
    assert app.session_state["test_apply_count"] == 1
    app.run()
    assert app.session_state["test_additions"] == {}
    assert app.session_state["test_apply_count"] == 1
    assert len(calls) == 1
    assert button(app, "Add reviewed pages").disabled


def test_section_upload_does_not_embed_same_file_elsewhere(monkeypatch, tmp_path):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page and continue").click().run()
    button(app, "Add reviewed pages").click().run()
    existing = app.session_state["test_sources"][0]
    # Re-use the exact original content bytes: identity is content based.
    raw = BytesIO(sources.source_bytes(synthetic_profiles()[0], existing))
    raw.name = "renamed-synthetic.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda name, **kwargs: [raw])
    next(w for w in app.radio if w.label == "Section").set_value("water_reports").run()
    assert not app.exception
    assert len(app.session_state["test_sources"]) == 1
    assert app.session_state["test_sources"][0] == existing
    assert "water_reports" not in app.session_state["test_blocks"]
    assert any("already belongs to another" in w.value for w in app.warning)
    assert not any(w.label == "Add reviewed pages" for w in app.button)


def test_price_pages_cannot_be_included_even_by_direct_include(monkeypatch, tmp_path):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), "Equipment inspection. Invoice amount $500.")
        raw = pdf.tobytes()
    app = section_app(monkeypatch, tmp_path, raw)
    assert not app.exception
    assert button(app, "Include page and continue").disabled
    assert button(app, "Add reviewed pages").disabled


def test_changed_caption_needs_one_new_review_without_rereading(monkeypatch, tmp_path):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page and continue").click().run()
    assert not button(app, "Add reviewed pages").disabled
    next(w for w in app.text_input if w.label == "Page caption").set_value("Updated caption").run()
    assert button(app, "Add reviewed pages").disabled
    button(app, "Include page and continue").click().run()
    assert not button(app, "Add reviewed pages").disabled


def test_batch_and_section_views_cannot_overwrite_canonical_edits(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    stream = BytesIO(pdf_bytes(1))
    stream.name = "synthetic.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda name, **kwargs: [stream])
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_upload_ui import render_uploads, render_section_uploads
from app.monthly_report_model import ReportPeriod, synthetic_profiles
def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key
view = st.radio("View", ["Batch", "Section"])
args = synthetic_profiles()[0], ReportPeriod(2026, 9), "synthetic", field
if view == "Batch":
    render_uploads(*args)
else:
    render_section_uploads(*args, "vendor_reports")
''', default_timeout=20).run()
    button(app, "Read monthly files").click().run()
    next(w for w in app.selectbox if w.label == "Classification").set_value("Vendor service").run()
    next(w for w in app.radio if w.label == "View").set_value("Section").run()
    button(app, "Include page and continue").click().run()
    next(w for w in app.text_input if w.label == "Vendor").set_value("Synthetic updated vendor").run()
    next(w for w in app.radio if w.label == "View").set_value("Batch").run()
    assert not app.exception
    assert next(w for w in app.text_input if w.label == "Vendor").value == "Synthetic updated vendor"
    assert page_allowed(app.session_state["synthetic_evidence"][0].source, 1)
    assert not any(w.label.startswith("I checked this page:") for w in app.checkbox)
    next(w for w in app.text_input if w.label == "Page caption").set_value("Batch edited caption").run()
    next(w for w in app.radio if w.label == "View").set_value("Section").run()
    assert not app.exception
    assert next(w for w in app.text_input if w.label == "Page caption").value == "Batch edited caption"
    assert button(app, "Add reviewed pages").disabled
