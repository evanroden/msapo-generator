"""A71: complete MBCx PDF insertion with varied page geometry and atomic limits.

Synthetic-only fixtures; these tests do not assert served or authentic-source acceptance.
"""
from dataclasses import asdict, replace
from io import BytesIO

from docx import Document
import pymupdf
import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
from app.monthly_report_docx import assemble_docx
from app.monthly_report_mbcx_pdf import prepare_whole_pdf, whole_pdf_pages
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from test_monthly_report_mbcx_pdf import APP, pdf_bytes


@pytest.mark.parametrize("count", [12, 40])
def test_complete_varied_pdf_preserves_every_source_page_and_word_geometry(
    monkeypatch, tmp_path, count
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = pdf_bytes(count)
    content, _ = sources.ingest(profile, f"synthetic-mbcx-{count}.pdf", raw)
    before = asdict(content)
    pages = tuple(range(1, count + 1))
    assert whole_pdf_pages(content, {}) == pages
    revised, additions = prepare_whole_pdf(profile, content, {})
    block = additions["mbcx_report"]
    assert len(block.asset_hashes) == count
    assert len(block.asset_instances) == count
    assert revised.source.selected_pages == pages
    assert tuple(n for n, _ in revised.source.client_page_reviews) == pages
    assert block.references == tuple(
        sources.source_reference(revised.source, n) for n in pages
    )
    assert len(set(block.references)) == count
    assert asdict(content) == before
    assert sources.source_bytes(profile, revised.source) == raw

    # Same saved source and a fresh upload of identical original bytes must
    # never append duplicates or silently reapprove a removed occurrence.
    assert prepare_whole_pdf(profile, revised, additions) == (revised, {})
    reimported, _ = sources.ingest(profile, f"synthetic-mbcx-{count}.pdf", raw)
    assert prepare_whole_pdf(profile, reimported, additions) == (reimported, {})

    source = replace(revised.source, service_date="2026-09-12",
                     facility=profile.facilities[0].key)
    block = approve_all_assets(refresh_asset_source_context(block, (source,)))
    draft = ReportDraft(
        profile, ReportPeriod(2026, 9), "Synthetic Editor",
        (SectionSpec("mbcx", "4", "MBCx Reports",
                     (BlockSpec("mbcx_report", "pdf_pages"),)),),
        (block,), sources=(source,),
    )
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period).draft
    assert reopened == draft
    docx = assemble_docx(
        reopened, acknowledged_fingerprint=reopened.fingerprint,
        asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref),
    )
    word = Document(BytesIO(docx))
    assert len(word.inline_shapes) == count
    captions = [p.text for p in word.paragraphs if "page/item" in p.text]
    assert captions == list(block.asset_captions)
    with pymupdf.open(stream=raw, filetype="pdf") as original:
        assert [page.number + 1 for page in original] == list(pages)
        for number, (shape, page) in enumerate(zip(word.inline_shapes, original), 1):
            assert shape.width > 0 and shape.height > 0
            assert shape.width / shape.height == pytest.approx(
                page.rect.width / page.rect.height, rel=.015
            ), f"source page {number} lost its orientation or dimensions"
    assert sources.source_bytes(profile, source) == raw


@pytest.mark.parametrize("count,occupied,first_over", [
    (12, 145, 6),
    (40, 130, 21),
])
def test_over_limit_names_exact_uninserted_page_range_without_processing(
    monkeypatch, tmp_path, count, occupied, first_over
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, f"synthetic-{count}.pdf", pdf_bytes(count))
    before = asdict(content)
    blocks = {"water_reports": ResolvedBlock(
        "water_reports", "This month", asset_hashes=("already.png",) * occupied
    )}
    # This must fail before any expensive PDF-to-image rasterization.
    def no_raster(*args, **kwargs):
        pytest.fail("capacity failure must precede image processing")
    monkeypatch.setattr(sources, "page_image", no_raster)
    with pytest.raises(ValueError, match=rf"pages {first_over}-{count}\b"):
        prepare_whole_pdf(profile, content, blocks)
    assert asdict(content) == before
    assert len(blocks["water_reports"].asset_hashes) == occupied


def test_unreadable_mbcx_page_is_not_implicitly_approved(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-mixed.pdf", pdf_bytes(12))
    # The extraction reported page 6 as requiring vision. No human visual
    # review can be inferred from other readable pages or a whole-file click.
    content = replace(content, source=replace(
        content.source, needs_vision=(6,),
    ))
    before = asdict(content)
    with pytest.raises(ValueError, match=r"page 6"):
        prepare_whole_pdf(profile, content, {})
    assert asdict(content) == before
    assert content.source.client_page_reviews == ()


@pytest.mark.parametrize("count", [12, 40])
def test_app_has_one_complete_document_action_without_page_checkboxes(
    monkeypatch, tmp_path, count
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app import monthly_report_upload_ui as ui
    stream = BytesIO(pdf_bytes(count))
    stream.name = f"synthetic-mbcx-{count}.pdf"
    monkeypatch.setattr(ui.st, "file_uploader", lambda *args, **kwargs: [stream])
    app = AppTest.from_string(APP, default_timeout=120).run()
    assert not app.exception
    assert not any(b.label == "Add reviewed pages" for b in app.button)
    button = next(b for b in app.button if b.label == f"Include all {count} PDF pages")
    assert not button.disabled
    button.click().run()
    assert not app.exception
    assert len(app.session_state["blocks"]["mbcx_report"].asset_hashes) == count
    app.run()
    assert len(app.session_state["blocks"]["mbcx_report"].asset_hashes) == count
