"""Matching heading text must not hide source artwork on the opening page."""
from io import BytesIO

from PIL import Image
import pymupdf
import pytest

from app.monthly_report_model import default_sections
from app.monthly_report_preview import ReportPreview, section_initial_page
from app.monthly_report_preview_store import PreviewStore


@pytest.mark.parametrize("artwork", [
    "photo", "inline_photo", "small_brand_mark", "vector_chart", "tiny_vector_chart", "divider_background",
])
def test_heading_with_unclassified_artwork_keeps_first_page_and_original_bytes(artwork):
    section = next(item for item in default_sections() if item.key == "training")
    with pymupdf.open() as pdf:
        first = pdf.new_page()
        if artwork == "divider_background":
            first.draw_rect(first.rect, color=(0, .2, .3), fill=(0, .2, .3))
        first.insert_text((50, 60), "Section " + section.number + "\n" + section.title)
        if artwork == "inline_photo":
            xref = first.get_contents()[0]
            pdf.update_stream(xref, pdf.xref_stream(xref) +
                              b"\nq\n100 0 0 100 100 100 cm\nBI /W 1 /H 1 /BPC 8 /CS /RGB ID \xff\x00\x00 EI\nQ\n")
            assert not first.get_images()  # Inline images have no image resource.
            assert len(first.get_image_info()) == 1
        elif artwork in {"photo", "small_brand_mark"}:
            raw = BytesIO()
            Image.new("RGB", (400, 300), "navy").save(raw, "PNG")
            rect = (pymupdf.Rect(50, 100, 450, 400) if artwork == "photo"
                    else pymupdf.Rect(50, 100, 70, 115))
            first.insert_image(rect, stream=raw.getvalue())
        elif artwork in {"vector_chart", "tiny_vector_chart"}:
            rect = (pymupdf.Rect(50, 100, 450, 400) if artwork == "vector_chart"
                    else pymupdf.Rect(50, 100, 52, 102))
            first.draw_rect(rect, color=(0, 0, 1), fill=(0, 0, 1))
        pdf.new_page().insert_text((50, 60), "Following source page")
        before = pdf.tobytes(no_new_id=True)
        first_pixels = pdf[0].get_pixmap().samples
        assert section_initial_page(pdf, section) == 0
        assert len(pdf) == 2
        assert pdf.tobytes(no_new_id=True) == before
        assert pdf[0].get_pixmap().samples == first_pixels

    # Unknown branding is retained and opens first; it is never inferred to be
    # expendable from its position, size, or similarity to a divider background.
    store = PreviewStore()
    try:
        ticket = store.put("synthetic-owner", ReportPreview(before, 2, artwork, "Sep", 0))
        assert ticket.pages == 2 and ticket.initial_page == 0
        assert [index for index, _ in store.pages("synthetic-owner", ticket, (0, 1), dpi=96)] == [0, 1]
    finally:
        store.close()
