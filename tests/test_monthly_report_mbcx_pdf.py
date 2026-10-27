"""Synthetic whole-document inclusion, without paid extraction or private files."""

from dataclasses import asdict, replace
from io import BytesIO

from docx import Document
import pymupdf as fitz
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_asset_review import pending_asset_indexes
from app.monthly_report_content_policy import page_fingerprint
from app.monthly_report_mbcx_pdf import prepare_whole_pdf, whole_pdf_pages
from app.monthly_report_model import (BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock,
                                      SectionSpec, synthetic_profiles)


def pdf_bytes(count=3, bad_page=None):
    with fitz.open() as pdf:
        for number in range(1, count + 1):
            page = pdf.new_page(width=792 if number == 2 else 612,
                                height=612 if number == 2 else 792)
            text = (bad_page if number == 2 and bad_page is not None else
                    f"Synthetic commissioning result page {number}. Equipment inspection complete.")
            if text:
                page.insert_text((50, 50), text)
            if number == 3:
                page.set_rotation(90)
        return pdf.tobytes()


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = pdf_bytes()
    content, _ = sources.ingest(profile, "synthetic-commissioning.pdf", raw)
    return profile, content, raw


def test_complete_pdf_preserves_order_provenance_original_and_word_pages(prepared):
    profile, content, raw = prepared
    before = asdict(content)
    revised, additions = prepare_whole_pdf(profile, content, {})
    block = additions["mbcx_report"]
    assert len(block.asset_hashes) == 3
    assert revised.source.selected_pages == (1, 2, 3)
    assert block.references == tuple(sources.source_reference(revised.source, n) for n in (1, 2, 3))
    assert not pending_asset_indexes(block)
    assert asdict(content) == before
    assert sources.source_bytes(profile, revised.source) == raw
    assert prepare_whole_pdf(profile, revised, additions) == (revised, {})

    from app.monthly_report_docx import assemble_docx
    # The output's ordinary source identity/period checks still apply. This
    # synthetic fixture records actual known metadata, not a policy waiver.
    source = replace(revised.source, service_date="2026-09-12", facility=profile.facilities[0].key)
    from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic Editor",
        (SectionSpec("mbcx", "4", "MBCx Reports", (BlockSpec("mbcx_report", "pdf_pages"),)),),
        (block,), sources=(source,))
    result = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
        asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref))
    document = Document(BytesIO(result))
    assert len(document.inline_shapes) == 3
    captions = [p.text for p in document.paragraphs if "page/item" in p.text]
    assert captions == list(block.asset_captions)


def test_more_than_vision_limit_includes_last_page(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-long.pdf", pdf_bytes(26))
    revised, additions = prepare_whole_pdf(profile, content, {})
    assert len(additions["mbcx_report"].asset_hashes) == 26
    assert revised.source.selected_pages[-1] == 26
    assert additions["mbcx_report"].references[-1] == sources.source_reference(revised.source, 26)


def test_visually_identical_pdf_pages_remain_separate_occurrences(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with fitz.open() as pdf:
        for _ in range(2):
            pdf.new_page().insert_text((40, 50), "Synthetic equipment inspection completed.")
        raw = pdf.tobytes()
    content, _ = sources.ingest(profile, "synthetic-repeated.pdf", raw)
    _, additions = prepare_whole_pdf(profile, content, {})
    block = additions["mbcx_report"]
    assert len(block.asset_hashes) == 2 and block.asset_hashes[0] == block.asset_hashes[1]
    assert len({instance.key for instance in block.asset_instances}) == 2
    from app.monthly_report_setup import merge_blocks
    existing = ResolvedBlock("mbcx_report", "This month", text="Keep this human introduction.")
    merged = merge_blocks(existing, block)
    assert len(merged.asset_hashes) == 2 and merged.text == existing.text


@pytest.mark.parametrize("text", ["Invoice amount $500.", "", "Signature: Approved by manager"])
def test_blocked_page_never_silently_disappears(monkeypatch, tmp_path, text):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-blocked.pdf", pdf_bytes(bad_page=text))
    before = asdict(content)
    with pytest.raises(ValueError, match="complete PDF cannot be added: page 2"):
        prepare_whole_pdf(profile, content, {})
    assert asdict(content) == before


def test_budget_omission_and_prior_decisions_are_not_overridden(prepared):
    profile, content, _ = prepared
    for block, message in [
        (ResolvedBlock("mbcx_report", "Omit"), "left out"),
        (ResolvedBlock("water_reports", "This month", asset_hashes=("synthetic.png",) * 149), "room for 1"),
    ]:
        with pytest.raises(ValueError, match=message):
            prepare_whole_pdf(profile, content, {block.key: block})
    for attr in ("client_page_reviews", "client_page_exclusions"):
        changed = replace(content, source=replace(content.source,
            **{attr: ((2, page_fingerprint(content.source, 2)),)}))
        with pytest.raises(ValueError, match="saved page decisions"):
            prepare_whole_pdf(profile, changed, {})


def test_removed_or_elsewhere_pages_are_never_restored_or_duplicated(prepared):
    profile, content, _ = prepared
    revised, additions = prepare_whole_pdf(profile, content, {})
    from app.monthly_report_saved_pictures_ui import remove_saved_picture
    removed = remove_saved_picture(additions["mbcx_report"], 1)
    with pytest.raises(ValueError, match="saved page decisions"):
        prepare_whole_pdf(profile, revised, {removed.key: removed})
    elsewhere = replace(additions["mbcx_report"], key="water_reports")
    with pytest.raises(ValueError, match="another section"):
        prepare_whole_pdf(profile, revised, {elsewhere.key: elsewhere})


def test_late_render_failure_does_not_commit_partial_pages_or_reviews(prepared, monkeypatch):
    profile, content, _ = prepared
    before = asdict(content)
    original = sources.page_image
    def fail(profile, item, number, **kwargs):
        if number == 3:
            raise ValueError("Synthetic final-page failure")
        return original(profile, item, number, **kwargs)
    monkeypatch.setattr(sources, "page_image", fail)
    with pytest.raises(ValueError, match="final-page failure"):
        prepare_whole_pdf(profile, content, {})
    assert asdict(content) == before and not content.source.client_page_reviews


APP = '''
import streamlit as st
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_upload_ui import render_section_uploads
from app.monthly_report_setup import merge_blocks
from app.monthly_report_guided import _refresh_period_editors_after_commit
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
blocks = st.session_state.setdefault("blocks", {})
sources, additions, _ = render_section_uploads(synthetic_profiles()[0], st.session_state.get("period", ReportPeriod(2026, 9)),
    "synthetic", field, "mbcx_report", blocks=blocks)
st.session_state["sources"] = sources
for key, block in additions.items():
    blocks[key] = merge_blocks(blocks.get(key), block)
_refresh_period_editors_after_commit("synthetic")
'''


def app_for(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app import monthly_report_upload_ui as ui
    stream = BytesIO(pdf_bytes())
    stream.name = "synthetic-commissioning.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: [stream])
    return AppTest.from_string(APP, default_timeout=20).run()


def test_one_action_includes_whole_pdf_and_reruns_do_not_duplicate(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    assert not app.exception
    assert not any(w.label in {"Page to review", "File to review"} for w in app.selectbox)
    assert not any(w.label == "Add reviewed pages" for w in app.button)
    button = next(w for w in app.button if w.label == "Include all 3 PDF pages")
    assert not button.disabled
    button.click().run()
    assert not app.exception
    assert len(app.session_state["blocks"]["mbcx_report"].asset_hashes) == 3
    assert next(w for w in app.button if w.label == "Include all 3 PDF pages").disabled
    app.run()
    assert len(app.session_state["blocks"]["mbcx_report"].asset_hashes) == 3


def test_individual_review_remains_available(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    app.toggle[0].set_value(True).run()
    assert not app.exception
    assert any(w.label == "Page to review" for w in app.selectbox)
    assert any(w.label == "Include page" for w in app.button)
    assert not any(w.label.startswith("Include all ") for w in app.button)


def test_old_whole_document_click_cannot_approve_a_changed_report(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    button = next(w for w in app.button if w.label == "Include all 3 PDF pages")
    app.session_state["blocks"] = {"mbcx_report": ResolvedBlock("mbcx_report", "Omit")}
    button.click().run()
    assert not app.exception
    assert app.session_state["blocks"]["mbcx_report"].source == "Omit"
    assert not app.session_state["blocks"]["mbcx_report"].asset_hashes
    assert not app.session_state["sources"][0].client_page_reviews


def test_old_whole_document_click_cannot_approve_another_month(monkeypatch, tmp_path):
    app = app_for(monkeypatch, tmp_path)
    button = next(w for w in app.button if w.label == "Include all 3 PDF pages")
    app.session_state["period"] = ReportPeriod(2026, 10)
    button.click().run()
    assert not app.exception and not app.session_state["blocks"]
    assert not app.session_state["sources"][0].client_page_reviews
