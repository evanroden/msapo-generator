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
from app.monthly_report_section_uploads import prepare_section_pages, section_contents, source_destinations, CLASSIFICATION_DESTINATIONS
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
from app.monthly_report_guided import _refresh_period_editors_after_commit
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
# Match the production caller: consume a requested control refresh only after
# this fixture has committed all returned sources and block additions.
_refresh_period_editors_after_commit("synthetic")
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
    button(app, "Include page").click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
    button(app, "Exclude page").click().run()
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
    button(app, "Include page").click().run()
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
    assert button(app, "Include page").disabled
    assert button(app, "Add reviewed pages").disabled


def test_changed_caption_needs_one_new_review_without_rereading(monkeypatch, tmp_path):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(1))
    button(app, "Include page").click().run()
    assert not button(app, "Add reviewed pages").disabled
    next(w for w in app.text_input if w.label == "Page caption").set_value("Updated caption").run()
    assert button(app, "Add reviewed pages").disabled
    button(app, "Include page").click().run()
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
    render_section_uploads(*args, "improvements")
''', default_timeout=20).run()
    button(app, "Read monthly files").click().run()
    next(w for w in app.selectbox if w.label == "Classification").set_value("Vendor service").run()
    next(w for w in app.radio if w.label == "View").set_value("Section").run()
    button(app, "Include page").click().run()
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



def test_scorecard_utility_upload_uses_one_labeled_control_without_extra_heading(
        monkeypatch, tmp_path):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(1),
                      label="Scorecard files")
    next(w for w in app.radio if w.label == "Section").set_value(
        "utility_analysis").run()
    assert not app.exception
    assert not any("Utility results and charts" in node.value
                   for node in app.markdown)
    assert not any(w.label == "Page to review" for w in app.selectbox)
    assert not button(app, "Include all 1 PDF pages").disabled
    assert not app.session_state["test_blocks"]
    next(w for w in app.toggle if w.label == "Review individual pages").set_value(True).run()
    assert any(w.label == "Page to review" for w in app.selectbox)
    # The fallback still requires explicit price-safe page acceptance.
    assert button(app, "Add reviewed pages").disabled


def test_whole_pdf_preflight_counts_other_section_pages_before_review(monkeypatch, tmp_path):
    from app.monthly_report_section_uploads import preflight_whole_pdf
    profile, content = reviewed_content(monkeypatch, tmp_path, pages=3)
    existing = ResolvedBlock("vendor_reports", "This month",
                             asset_hashes=("existing.png",) * 148)
    blocks = {"vendor_reports": existing}
    unchanged = content.source
    budget = preflight_whole_pdf(profile, content, "water_reports", blocks)
    assert budget.new_pages == 3
    assert budget.already_included == 0
    assert budget.available_pages == 2
    assert budget.pages_fit is False
    assert budget.images_fit is None
    assert content.source == unchanged and blocks == {"vendor_reports": existing}
    # A reduced PDF that fits the remaining slots can be attempted, with no
    # silent page drop and no mutation by this read-only check.
    profile, smaller = reviewed_content(monkeypatch, tmp_path, pages=2)
    retry = preflight_whole_pdf(profile, smaller, "water_reports", blocks)
    assert retry.new_pages == 2 and retry.available_pages == 2 and retry.pages_fit
    assert smaller.source.selected_pages == (1, 2)


def test_whole_pdf_preflight_measures_normalized_bytes_without_approving(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from app.monthly_report_section_uploads import preflight_whole_pdf
    profile, content = reviewed_content(monkeypatch, tmp_path, pages=2)
    original = content.source
    class SizedBytes:
        def __init__(self, length):
            self.length = length
        def __len__(self):
            return self.length
    prepared = []
    def image(_profile, _content, number):
        prepared.append(number)
        return SimpleNamespace(data=SizedBytes((1 if number == 1 else 2) * 1024 * 1024))
    monkeypatch.setattr(sources, "page_image", image)
    block = ResolvedBlock("vendor_reports", "This month", asset_hashes=("existing.png",))
    report = {"vendor_reports": block}
    large = preflight_whole_pdf(profile, content, "water_reports", report,
                                 {"existing.png": SizedBytes(58 * 1024 * 1024)}, measure_bytes=True)
    assert large.new_pages == 2 and large.available_pages == sources.MAX_EMBED_PAGES - 1
    assert large.remaining_bytes == 2 * 1024 * 1024
    assert large.new_image_bytes == 3 * 1024 * 1024
    assert large.measured_all and large.images_fit is False
    assert prepared == [1, 2]
    prepared.clear()
    enough = preflight_whole_pdf(profile, content, "water_reports", report,
                                  {"existing.png": SizedBytes(55 * 1024 * 1024)}, measure_bytes=True)
    assert enough.images_fit is True and enough.measured_all
    assert prepared == [1, 2]
    assert content.source == original and report == {"vendor_reports": block}


def test_whole_pdf_preflight_rejects_cross_section_ownership(monkeypatch, tmp_path):
    from app.monthly_report_section_uploads import preflight_whole_pdf
    profile, content = reviewed_content(monkeypatch, tmp_path, pages=1)
    block, = sources.prepare_pages(profile, (content,), ((content.source.id, "vendor_reports"),))
    with pytest.raises(ValueError, match="another section"):
        preflight_whole_pdf(profile, content, "mbcx_report", {"vendor_reports": block})


def test_whole_pdf_fit_is_shown_before_page_approval(monkeypatch, tmp_path):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(2))
    assert not app.exception
    assert any("Whole PDF: 2 new pages" in c.value for c in app.caption)
    assert not app.session_state["test_blocks"]
    button(app, "Check whole-PDF image size").click().run()
    assert not app.exception
    assert any("All 2 new pages fit the current image budget" in s.value
               for s in app.success)
    assert not app.session_state["test_blocks"]
    assert button(app, "Add reviewed pages").disabled


@pytest.mark.parametrize("destination,label", [
    ("mbcx_report", "MBCx report files"),
    ("utility_analysis", "Scorecard files"),
])
def test_complete_pdf_action_keeps_main_budget_preflight(monkeypatch, tmp_path, destination, label):
    app = section_app(monkeypatch, tmp_path, pdf_bytes(2), label=label)
    app.radio[0].set_value(destination).run()
    assert not app.exception
    assert any("Whole PDF: 2 new pages" in c.value for c in app.caption)
    assert not app.session_state["test_blocks"]
    before = app.session_state["test_sources"]
    button(app, "Check whole-PDF image size").click().run()
    assert not app.exception
    assert any("All 2 new pages fit the current image budget" in s.value
               for s in app.success)
    assert app.session_state["test_sources"] == before
    assert not app.session_state["test_blocks"]
    button(app, "Include all 2 PDF pages").click().run()
    assert not app.exception
    assert len(app.session_state["test_blocks"][destination].asset_hashes) == 2
