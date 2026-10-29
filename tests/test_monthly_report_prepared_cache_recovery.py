"""Damaged disposable page caches recover without relaxing original integrity.

Synthetic PDFs only; no saved report, private source, or installed master used.
Refs #284, #462, #270.
"""

from io import BytesIO
import json
from pathlib import Path

import pymupdf as fitz
from PIL import Image
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    return profile


def _pdf(marker):
    with fitz.open() as pdf:
        for page in range(2):
            item = pdf.new_page()
            item.insert_text((72, 72), f"Synthetic {marker} service report page {page + 1}")
        return pdf.tobytes()


def _image():
    output = BytesIO()
    Image.new("RGB", (120, 100), "green").save(output, "PNG")
    return output.getvalue()


def _replace_synthetic_file(path, raw):
    # Content-addressed originals/rasters are intentionally read-only. Replace
    # this test-created inode to simulate corruption, retaining its file mode.
    mode = path.stat().st_mode & 0o777
    path.unlink()
    path.write_bytes(raw)
    path.chmod(mode)


def _setup(profile, marker="A", *, suffix=".pdf"):
    raw = _pdf(marker) if suffix == ".pdf" else _image()
    content, _ = sources.ingest(profile, f"synthetic-{marker}{suffix}", raw)
    result = sources.page_image(profile, content, 1, preview=True)
    folder = sources._path(profile, content.source.sha256, suffix).parent / "prepared" / content.source.sha256
    cache = folder / "1-preview.json"
    saved = library._read(cache)
    asset = folder / saved["asset"]
    return content, raw, result, cache, asset


@pytest.mark.parametrize("failure", ["missing", "tampered", "malformed_json", "invalid_pointer",
                                     "missing_metadata", "invalid_dimensions", "wrong_extension"])
def test_bad_disposable_pdf_cache_is_rebuilt_from_untouched_original(profile, failure):
    content, raw, first, cache, asset = _setup(profile)
    original = sources._path(profile, content.source.sha256, ".pdf")
    if failure == "missing":
        asset.unlink()
    elif failure == "tampered":
        _replace_synthetic_file(asset, b"damaged cached JPEG")
    elif failure == "malformed_json":
        cache.write_text("{not valid json", encoding="utf-8")
    else:
        saved = library._read(cache)
        if failure == "invalid_pointer":
            saved["asset"] = "../outside.png"
        elif failure == "missing_metadata":
            del saved["width"]
        elif failure == "invalid_dimensions":
            saved["height"] = False
        elif failure == "wrong_extension":
            saved["extension"] = "png" if saved["extension"] == "jpg" else "jpg"
        library._atomic_write(cache, library._json(saved))
    rebuilt = sources.page_image(profile, content, 1, preview=True)
    assert rebuilt == first
    assert original.read_bytes() == raw
    saved = library._read(cache)
    assert (cache.parent / saved["asset"]).read_bytes() == first.data
    assert saved["width"] == first.width and saved["height"] == first.height
    assert saved["extension"] == first.extension


def test_valid_cache_still_bypasses_rendering(profile, monkeypatch):
    content, _, first, _, _ = _setup(profile)
    monkeypatch.setattr(sources.fitz, "open", lambda *a, **k: pytest.fail("healthy cache rerendered"))
    assert sources.page_image(profile, content, 1, preview=True) == first


def test_png_preview_cache_rebuild_and_same_source_other_purpose_unchanged(profile):
    content, raw, first, cache, asset = _setup(profile, "png", suffix=".png")
    print_page = sources.page_image(profile, content, 1, preview=False)
    print_cache = cache.parent / "1-print.json"
    print_before = print_cache.read_bytes()
    cache.write_text('[]', encoding="utf-8")
    assert sources.page_image(profile, content, 1, preview=True) == first
    assert print_cache.read_bytes() == print_before
    assert sources.page_image(profile, content, 1, preview=False) == print_page
    assert sources._path(profile, content.source.sha256, ".png").read_bytes() == raw


def test_original_corruption_is_not_hidden_by_a_bad_cached_page(profile):
    content, _, _, cache, asset = _setup(profile)
    original = sources._path(profile, content.source.sha256, ".pdf")
    _replace_synthetic_file(original, b"synthetic corrupted original")
    _replace_synthetic_file(asset, b"synthetic corrupted cache")
    prior_cache = cache.read_bytes()
    with pytest.raises(ValueError, match="integrity"):
        sources.page_image(profile, content, 1, preview=True)
    assert cache.read_bytes() == prior_cache
    assert original.read_bytes() == b"synthetic corrupted original"


def test_bad_cache_does_not_rewrite_healthy_sibling_source_or_page(profile):
    content, original, first, cache, asset = _setup(profile, "A")
    other, other_raw, other_first, other_cache, other_asset = _setup(profile, "B")
    second_page = sources.page_image(profile, content, 2, preview=True)
    second_cache = cache.parent / "2-preview.json"
    other_before = (other_cache.read_bytes(), other_asset.read_bytes(), second_cache.read_bytes())
    asset.unlink()
    assert sources.page_image(profile, content, 1, preview=True) == first
    assert sources.page_image(profile, content, 2, preview=True) == second_page
    assert sources.page_image(profile, other, 1, preview=True) == other_first
    assert (other_cache.read_bytes(), other_asset.read_bytes(), second_cache.read_bytes()) == other_before
    assert sources._path(profile, other.source.sha256, ".pdf").read_bytes() == other_raw
    assert sources._path(profile, content.source.sha256, ".pdf").read_bytes() == original


def test_actual_cached_read_is_bounded_even_if_file_was_replaced(profile, monkeypatch):
    content, original, first, cache, asset = _setup(profile)
    # Lower the existing 60 MiB ceiling for a small deterministic race test:
    # old code reads the full replacement and returns/rejects it, whereas this
    # code makes a bounded read and then rederives the valid source.
    monkeypatch.setattr(sources, "MAX_CACHED_PAGE_IMAGE_BYTES", 16)
    actual_open = Path.open
    observed = []

    class Watched:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, amount=-1):
            observed.append(amount)
            return self.stream.read(amount)

    def watched_open(path, *args, **kwargs):
        stream = actual_open(path, *args, **kwargs)
        if path == asset and args and args[0] == "rb":
            return Watched(stream)
        return stream

    monkeypatch.setattr(Path, "open", watched_open)
    # No extra storage required: even a normally valid cached page is over
    # this intentionally reduced cap and must be read only up to cap + 1.
    assert sources.page_image(profile, content, 1, preview=True) == first
    assert observed == [17]
    assert sources._path(profile, content.source.sha256, ".pdf").read_bytes() == original

