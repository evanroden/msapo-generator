"""Cold Review ticket path: no eager 120-page raster or downloadable vector copy.

All pages and text are synthetic. The public, downloadable draft path remains
flattened and is verified separately from the ticket-only performance path.
"""
from hashlib import sha256
from io import BytesIO

import pymupdf as fitz
import pytest

from app import monthly_report_preview as preview
from app import monthly_report_preview_images as preview_images
from app import monthly_report_designs as designs
from app import monthly_report_library as library
from app import monthly_report_render_jobs as render_jobs
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_preview_store import PreviewStore
from app.monthly_report_preview_ticket import private_ticket_pdf


def source_pdf(count):
    with fitz.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((64, 72), f"SYNTHETIC REPORT PAGE {index + 1:03d}")
        return pdf.tobytes(garbage=3, deflate=True)


@pytest.mark.parametrize("count", (1, 2, 120))
def test_private_ticket_keeps_every_page_and_exact_geometry(count):
    original = source_pdf(count)
    original_hash = sha256(original).hexdigest()
    with fitz.open(stream=original, filetype="pdf") as document:
        result = private_ticket_pdf(
            document, source_bytes=len(original),
            max_pages=150, max_bytes=25 * 1024 * 1024,
        )
    assert sha256(original).hexdigest() == original_hash
    assert result and result.startswith(b"%PDF-")
    with fitz.open(stream=result, filetype="pdf") as rendered:
        assert len(rendered) == count
        assert [tuple(p.rect) for p in rendered] == [(0.0, 0.0, 612.0, 792.0)] * count
        for index, page in enumerate(rendered):
            text = page.get_text()
            assert f"SYNTHETIC REPORT PAGE {index + 1:03d}" in text
            assert "DRAFT - REVIEW ONLY" in text
            assert "DRAFT PREVIEW - NOT A FINISHED CLIENT REPORT" in text

    store = PreviewStore()
    try:
        from app.monthly_report_preview import ReportPreview
        ticket = store.put("owner-one", ReportPreview(result, count, original_hash, "Synthetic"))
        first = store.pages("owner-one", ticket, tuple(range(min(2, count))), dpi=96)
        assert [i for i, raw in first] == list(range(min(2, count)))
        assert all(raw[:2] == bytes((255, 216)) for _, raw in first)
        assert store.pages("owner-two", ticket, (0,)) is None
        assert store.pages("owner-one", ticket, (count - 1,), dpi=96)
        assert store.stats()["raster_entries"] <= 3
        store.discard("owner-one", ticket)
        assert store.stats()["pdf_bytes"] == store.stats()["raster_bytes"] == 0
    finally:
        store.close()


def test_scanned_only_rotated_page_remains_renderable():
    from PIL import Image
    from app.monthly_report_preview import ReportPreview

    with fitz.open() as source:
        page = source.new_page(width=792, height=612)
        picture = Image.new("RGB", (400, 300), (32, 137, 184))
        data = BytesIO()
        picture.save(data, "PNG")
        page.insert_image(page.rect, stream=data.getvalue())
        page.set_rotation(90)
        original = source.tobytes(garbage=3, deflate=True)

    with fitz.open(stream=original, filetype="pdf") as doc:
        result = private_ticket_pdf(doc, source_bytes=len(original),
                                    max_pages=150, max_bytes=25 * 1024 * 1024)
    with fitz.open(stream=result, filetype="pdf") as doc:
        assert len(doc) == 1
        assert tuple(doc[0].rect) == (0.0, 0.0, 612.0, 792.0)
        assert doc[0].get_images(), "A scanned-only page is never treated as blank"
        assert "DRAFT PREVIEW" in doc[0].get_text()

    store = PreviewStore()
    try:
        ticket = store.put("owner", ReportPreview(result, 1, "synthetic-scan", "Synthetic"))
        assert store.pages("owner", ticket, (0,))[0][1].startswith(bytes((255, 216)))
    finally:
        store.close()


def test_empty_oversized_and_malformed_inputs_do_not_claim_success():
    with fitz.open() as empty:
        with pytest.raises(ValueError, match="150 pages"):
            private_ticket_pdf(empty, source_bytes=0, max_pages=150, max_bytes=1024)
    original = source_pdf(2)
    with fitz.open(stream=original, filetype="pdf") as pdf:
        assert private_ticket_pdf(pdf, source_bytes=1025, max_pages=150, max_bytes=1024) is None
    with pytest.raises((fitz.FileDataError, ValueError)):
        fitz.open(stream=b"not-a-pdf", filetype="pdf")


def _stub_review(monkeypatch, tmp_path, count):
    report = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    converted = tmp_path / "synthetic-converted.pdf"
    converted.write_bytes(source_pdf(count))
    monkeypatch.setattr(preview, "preflight", lambda draft: [])
    monkeypatch.setattr(preview, "_build_docx", lambda *args, **kwargs: b"test-docx-bytes")
    monkeypatch.setattr(preview, "rendering_docx", lambda raw, profile=None: raw)
    monkeypatch.setattr(preview_images, "write_preview_docx", lambda raw, path: path.write_bytes(raw))
    monkeypatch.setattr(designs, "render_profile_for", lambda profile: {})
    monkeypatch.setattr(library, "_root", lambda: tmp_path)
    monkeypatch.setattr(render_jobs, "convert_to_pdf", lambda path, wait_seconds: converted)
    return report


def test_current_review_120_pages_never_eagerly_decodes_an_unseen_page(monkeypatch, tmp_path):
    report = _stub_review(monkeypatch, tmp_path, 120)

    def forbidden(*args, **kwargs):
        pytest.fail("Cold Review must not eagerly rasterize all 120 pages")

    monkeypatch.setattr(fitz.Page, "get_pixmap", forbidden)
    result = preview._preview_verified_report(report, fingerprint="synthetic-current",
                                             ticket_only=True)
    assert result.pages == 120 and result.fingerprint == "synthetic-current"
    with fitz.open(stream=result.pdf, filetype="pdf") as document:
        assert "SYNTHETIC REPORT PAGE 120" in document[119].get_text()


def test_downloadable_preview_remains_flattened_low_resolution(monkeypatch, tmp_path):
    report = _stub_review(monkeypatch, tmp_path, 2)
    result = preview._preview_verified_report(report, fingerprint="synthetic-flat",
                                             ticket_only=False)
    assert result.pages == 2
    with fitz.open(stream=result.pdf, filetype="pdf") as document:
        assert "DRAFT PREVIEW - NOT A FINISHED CLIENT REPORT" in document[0].get_text()
        assert "SYNTHETIC REPORT PAGE" not in document[0].get_text()
        assert document[0].get_images(), "The downloadable preview remains a flattened image"
        assert tuple(document[0].rect) == (0.0, 0.0, 612.0, 792.0)


def test_ticket_only_falls_back_for_oversized_source(monkeypatch, tmp_path):
    report = _stub_review(monkeypatch, tmp_path, 1)
    from app import monthly_report_preview_ticket
    monkeypatch.setattr(monthly_report_preview_ticket, "private_ticket_pdf",
                        lambda *args, **kwargs: None)
    result = preview._preview_verified_report(report, fingerprint="synthetic-fallback",
                                             ticket_only=True)
    with fitz.open(stream=result.pdf, filetype="pdf") as document:
        assert "SYNTHETIC REPORT PAGE" not in document[0].get_text()
        assert document[0].get_images()
