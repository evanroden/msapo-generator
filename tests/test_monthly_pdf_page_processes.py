"""A27: synthetic two-process raster fidelity, resource gates and cleanup."""
from dataclasses import replace
import hashlib
import multiprocessing
from pathlib import Path
import shutil

import pymupdf as fitz
import pytest

from app import monthly_report_parallel_pages as parallel, monthly_report_sources as sources
from app import monthly_report_library as library, ocr
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_content_policy import page_fingerprint


def synthetic_pdf(count, marks=8):
    with fitz.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((40, 40), f"Synthetic completed inspection DEMO-01 page {index + 1}")
            for mark in range(marks):
                x = 35 + (mark % 9) * 55
                y = 70 + (mark // 9) * 35
                page.draw_rect(fitz.Rect(x, y, x + 22, y + 15),
                               color=(0.1, 0.2, 0.5), fill=(0.6, 0.7, 0.8))
            if index % 3 == 1:
                page.set_rotation(90)
        return pdf.tobytes(no_new_id=True)


def serial_images(raw, numbers):
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        for number in numbers:
            page = pdf[number - 1]
            png = page.get_pixmap(dpi=150, alpha=False).tobytes("png")
            yield number, normalize_report_image(png, ".png", line_art=True, dpi=150)


def result_fingerprints(results):
    return tuple((n, img.width, img.height, img.extension,
                  hashlib.sha256(img.data).hexdigest()) for n, img in results)


@pytest.mark.parametrize("count", [24, 96])
def test_independent_workers_match_serial_byte_hashes_and_rotated_geometry(tmp_path, count):
    raw = synthetic_pdf(count)
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(raw)
    pages = tuple(range(1, count + 1))
    reference = result_fingerprints(serial_images(raw, pages))
    delivered = result_fingerprints(parallel.parallel_pages(
        path, hashlib.sha256(raw).hexdigest(), pages, dpi=150,
        max_pixels=ocr._MAX_PIXELS_PER_FRAME, max_source_bytes=30 * 1024 * 1024))
    assert delivered == reference
    assert delivered[0][1] < delivered[0][2]
    assert delivered[1][1] > delivered[1][2]  # Real PDF rotation, unchanged.


def test_realistic_resource_gates_and_visible_preview_are_serial(monkeypatch):
    monkeypatch.setattr(parallel, "resource_limits",
                        lambda: (3 * 1024 ** 3, 4 * 1024 ** 3, 4))
    assert parallel.eligible(96)
    assert not parallel.eligible(24)
    assert not parallel.eligible(48)
    assert not parallel.eligible(2)  # PreviewStore remains exactly two visible pages.
    monkeypatch.setattr(parallel, "resource_limits",
                        lambda: (320 * 1024 ** 2, 512 * 1024 ** 2, 0.5))
    assert not parallel.eligible(96)  # 512-MiB / 0.5-CPU control.
    monkeypatch.setattr(parallel, "resource_limits",
                        lambda: (3 * 1024 ** 3, 4 * 1024 ** 3, 0.5))
    assert not parallel.eligible(96)
    monkeypatch.setattr(parallel, "resource_limits",
                        lambda: (100 * 1024 ** 2, 4 * 1024 ** 3, 4))
    assert not parallel.eligible(96)  # Near memory exhaustion is serial.


def test_pool_closes_after_cancelled_and_corrupt_or_missing_inputs(tmp_path):
    raw = synthetic_pdf(4)
    path = tmp_path / "fixture.pdf"
    path.write_bytes(raw)
    def run(numbers, p=path, digest=hashlib.sha256(raw).hexdigest()):
        return parallel.parallel_pages(
            p, digest, numbers, dpi=150,
            max_pixels=ocr._MAX_PIXELS_PER_FRAME, max_source_bytes=30 * 1024 * 1024)
    before = {p.pid for p in multiprocessing.active_children()}
    iterator = run((1, 2, 3, 4))
    assert next(iterator)[0] == 1
    iterator.close()  # Browser/view request superseded after first useful page.
    assert not ({p.pid for p in multiprocessing.active_children()} - before)

    path.write_bytes(b"%PDF-broken")
    with pytest.raises((ValueError, RuntimeError, fitz.FileDataError)):
        list(run((1,)))
    assert not ({p.pid for p in multiprocessing.active_children()} - before)

    path.unlink()
    with pytest.raises(OSError):
        list(run((1,)))
    assert not ({p.pid for p in multiprocessing.active_children()} - before)


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    value = synthetic_profiles()[0]
    library.save_profile(value, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return value


def test_large_approved_pdf_batch_keeps_captions_order_and_assets(profile, monkeypatch):
    # The exact same reviewed original is used by both serial and process runs.
    raw = synthetic_pdf(96, marks=80)
    content, _ = sources.ingest(profile, "synthetic.pdf", raw)
    pages = tuple(range(1, 97))
    with_captions = replace(content.source, selected_pages=pages,
                            captions=((2, "Reviewed rotated page"),))
    source = replace(with_captions, client_page_reviews=tuple(
        (number, page_fingerprint(with_captions, number)) for number in pages))
    content = replace(content, source=source)
    monkeypatch.setattr(parallel, "eligible", lambda count: False)
    serial = sources.prepare_pages(profile, (content,), ((source.id, "vendor_reports"),))
    prepared = sources._path(profile, source.sha256, ".pdf").parent / "prepared" / source.sha256
    shutil.rmtree(prepared)  # Only disposable derivatives, not the immutable original.
    monkeypatch.setattr(parallel, "eligible", lambda count: count >= 64)
    used = []
    original = parallel.parallel_pages
    def observed(*args, **kwargs):
        used.append(True)
        yield from original(*args, **kwargs)
    monkeypatch.setattr(parallel, "parallel_pages", observed)
    concurrent = sources.prepare_pages(profile, (content,), ((source.id, "vendor_reports"),))
    assert used
    assert tuple((block.key, block.asset_hashes, block.asset_captions, block.references)
                 for block in serial) == tuple(
                     (block.key, block.asset_hashes, block.asset_captions, block.references)
                     for block in concurrent)
    assert serial[0].asset_captions[1] == "Reviewed rotated page"
    assert len(serial[0].asset_hashes) == 96
    assert all(library.read_asset(profile.contract, profile.key, ref)
               for ref in concurrent[0].asset_hashes)
    # No process changed original bytes or source identity.
    assert sources.source_bytes(profile, source) == raw


def test_foreign_profile_cannot_raster_another_sites_original(profile):
    other = synthetic_profiles()[1]
    content, _ = sources.ingest(profile, "synthetic.pdf", synthetic_pdf(2))
    with pytest.raises((OSError, ValueError)):
        sources.page_image(other, content, 1, preview=True)
