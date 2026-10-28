"""Synthetic checks for damaged disposable static-chart raster caches.

No genuine report, contract, source file, or installed master is used.
Refs #467 and #270.
"""

from io import BytesIO
import os

import pytest
from PIL import Image

from app.monthly_report_metafile_cache import cached_vector_png


def png(size=(64, 48), color="navy"):
    result = BytesIO()
    Image.new("RGB", size, color).save(result, "PNG")
    return result.getvalue()


def test_valid_cached_png_exact_bytes_and_repeat(tmp_path):
    file = tmp_path / "review.png"
    raw = png()
    file.write_bytes(raw)
    assert cached_vector_png(file) == raw
    assert cached_vector_png(file) == raw
    assert file.read_bytes() == raw


@pytest.mark.parametrize("failure", [
    b"", b"not png", b"\x89PNG\r\n\x1a\ninvalid",
    png()[:-12], png()[:32],
])
def test_incomplete_or_non_png_cache_is_a_miss(tmp_path, failure):
    file = tmp_path / "review.png"
    file.write_bytes(failure)
    assert cached_vector_png(file) is None
    assert file.read_bytes() == failure


def test_valid_other_image_format_is_not_a_png_cache(tmp_path):
    file = tmp_path / "review.png"
    out = BytesIO()
    Image.new("RGB", (32, 32), "green").save(out, "JPEG")
    file.write_bytes(out.getvalue())
    assert cached_vector_png(file) is None


def test_oversized_bytes_are_not_accepted_even_if_valid_png(tmp_path):
    file = tmp_path / "review.png"
    raw = png()
    file.write_bytes(raw)
    assert len(raw) > 16
    assert cached_vector_png(file, limit=16) is None
    assert cached_vector_png(file) == raw


def test_valid_png_with_wrong_geometry_is_rejected(tmp_path):
    file = tmp_path / "review.png"
    file.write_bytes(png((2500, 4)))
    assert cached_vector_png(file) is None
    file.write_bytes(png((2400, 2400)))
    assert cached_vector_png(file) is None
    file.write_bytes(png((1400, 1800)))
    assert cached_vector_png(file) == file.read_bytes()


def test_replaced_symlink_cannot_read_another_reports_cache(tmp_path):
    other = tmp_path / "other-private-image.png"
    raw = png(color="purple")
    other.write_bytes(raw)
    file = tmp_path / "review.png"
    file.symlink_to(other)
    assert cached_vector_png(file) is None
    assert other.read_bytes() == raw
    assert file.is_symlink()


def test_unavailable_and_directory_paths_are_cache_misses(tmp_path):
    assert cached_vector_png(tmp_path / "gone.png") is None
    assert cached_vector_png(tmp_path) is None


def test_no_block_on_special_fifo_file(tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO not supported")
    file = tmp_path / "fifo.png"
    os.mkfifo(file)
    assert cached_vector_png(file) is None


@pytest.mark.parametrize("limit", [0, -1, "100", 24 * 1024 * 1024 + 1, 1.5])
def test_invalid_external_size_limit_is_refused(tmp_path, limit):
    with pytest.raises(ValueError, match="size limit"):
        cached_vector_png(tmp_path / "review.png", limit=limit)


def test_rendered_pdf_png_is_accepted_without_altering_bytes(tmp_path):
    import pymupdf as fitz
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(0, 0, 300, 400), fill=(.2, .2, .2), color=(.2, .2, .2))
        raw = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72),
                              clip=fitz.Rect(0, 0, 300, 400), alpha=False).tobytes("png")
    file = tmp_path / "word-static-chart.png"
    file.write_bytes(raw)
    assert cached_vector_png(file) == raw


