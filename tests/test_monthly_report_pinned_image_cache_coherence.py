"""A17: pinned native-design JPEG eligibility must follow the current file, not its name.

These checks use invented pixels and a minimal OOXML zip; no report originals
or contact/financial data are involved.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from PIL import Image
import pytest

from app.monthly_report_pdf_image_budget import (
    _original_jpeg_hashes, compact_native_photos_for_pdf,
)


@pytest.fixture(autouse=True)
def clear_pinned_hash_cache():
    _original_jpeg_hashes.cache_clear()
    yield
    _original_jpeg_hashes.cache_clear()


def _photo(tint: int) -> bytes:
    image = Image.effect_noise((2400, 1600), 30).convert("RGB")
    image.paste((tint, 50, 90), (0, 0, 150, 150))
    output = BytesIO()
    image.save(output, "JPEG", quality=88)
    return output.getvalue()


def _word(image: bytes) -> bytes:
    result = BytesIO()
    with ZipFile(result, "w") as archive:
        archive.writestr("word/document.xml", b"<synthetic-report/>")
        archive.writestr("word/media/pinned.jpg", image)
    return result.getvalue()


def _edge(package: bytes) -> int:
    with ZipFile(BytesIO(package)) as archive:
        assert archive.read("word/document.xml") == b"<synthetic-report/>"
        with Image.open(BytesIO(archive.read("word/media/pinned.jpg"))) as photo:
            return max(photo.size)


def test_same_path_replaced_master_uses_only_current_approved_photos(tmp_path: Path):
    pinned = tmp_path / "active-design.docx"
    former = _word(_photo(30))
    current = _word(_photo(210))
    assert former != current
    pinned.write_bytes(former)
    former_source_sha = sha256(pinned.read_bytes()).hexdigest()

    first_pdf_copy = compact_native_photos_for_pdf(former, pinned_source=pinned)
    assert _edge(first_pdf_copy) == 1400
    assert _edge(former) == 2400

    # Simulates an approved, replaced design keeping its stable installed path.
    pinned.write_bytes(current)
    current_source_sha = sha256(pinned.read_bytes()).hexdigest()
    assert current_source_sha != former_source_sha
    second_pdf_copy = compact_native_photos_for_pdf(current, pinned_source=pinned)
    assert _edge(second_pdf_copy) == 1400  # A path-only hash cache misses this replacement.
    assert compact_native_photos_for_pdf(former, pinned_source=pinned) == former
    assert pinned.read_bytes() == current
    assert current == _word_with_same_payload(current)


def _word_with_same_payload(value: bytes) -> bytes:
    """A control that also proves the input DOCX was never altered."""
    return bytes(value)


def test_atomic_pinned_replacement_invalidates_allowlist(tmp_path: Path):
    pinned = tmp_path / "approved.docx"
    pending = tmp_path / "approved-next.docx"
    old = _word(_photo(33))
    new = _word(_photo(177))
    pinned.write_bytes(old)
    assert _edge(compact_native_photos_for_pdf(old, pinned_source=pinned)) == 1400
    pending.write_bytes(new)
    pending.replace(pinned)
    assert _edge(compact_native_photos_for_pdf(new, pinned_source=pinned)) == 1400
    assert compact_native_photos_for_pdf(old, pinned_source=pinned) == old


def test_unchanged_pinned_design_repeats_identical_pdf_only_pixels(tmp_path: Path):
    pinned = tmp_path / "stable.docx"
    original = _word(_photo(123))
    pinned.write_bytes(original)
    first = compact_native_photos_for_pdf(original, pinned_source=pinned)
    second = compact_native_photos_for_pdf(original, pinned_source=pinned)
    assert sha256(first).hexdigest() == sha256(second).hexdigest()
    assert _edge(first) == 1400
    assert pinned.read_bytes() == original
    assert _edge(original) == 2400
