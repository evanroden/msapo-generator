"""Image decoder admission is explicit for every application and QA caller."""
from __future__ import annotations

import ast
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, UnidentifiedImageError

from app.image_open import image_formats_for_suffix, open_image
from app.monthly_report_docx import normalize_report_image

ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("app", "scripts", "pages", "runtime")


@pytest.mark.parametrize("disguised", ["TIFF", "EPS", "BMP"])
def test_disguised_photo_rejected_before_disallowed_decoder(monkeypatch, disguised):
    raw = BytesIO()
    Image.new("RGB", (16, 12), "blue").save(raw, format=disguised)
    Image.init()
    factory, accept = Image.OPEN[disguised]

    def forbidden_decoder(*args, **kwargs):
        pytest.fail(f"{disguised} decoder was selected before photo admission")

    monkeypatch.setitem(Image.OPEN, disguised, (forbidden_decoder, accept))
    with pytest.raises((UnidentifiedImageError, ValueError, OSError)):
        normalize_report_image(raw.getvalue(), ".jpg")
    assert Image.OPEN[disguised][0] is forbidden_decoder


@pytest.mark.parametrize(
    ("suffix", "format_name"), [(".jpg", "JPEG"), (".png", "PNG"),
                                (".gif", "GIF"), (".webp", "WEBP"),
                                (".bmp", "BMP"), (".tiff", "TIFF"), (".mpo", "JPEG")]
)
def test_existing_admitted_formats_keep_explicit_decoder_mapping(suffix, format_name):
    assert image_formats_for_suffix(suffix) == (format_name,)


def test_mpo_detection_uses_jpeg_plugin_without_rejecting_real_phone_frames():
    buffer = BytesIO()
    Image.new("RGB", (20, 12), "red").save(
        buffer, "MPO", save_all=True, append_images=[Image.new("RGB", (20, 12), "blue")]
    )
    with open_image(BytesIO(buffer.getvalue()), formats=image_formats_for_suffix(".mpo")) as image:
        assert image.format == "MPO"
        assert image.n_frames == 2


def test_word_vectors_only_in_word_context_and_photo_formats_stay_narrow():
    assert image_formats_for_suffix(".emf", word_media=True) == ("WMF",)
    assert image_formats_for_suffix(".wmf", word_media=True) == ("WMF",)
    for suffix in (".emf", ".wmf", ".eps", ".tiff", ".bmp", ".gif", ".mpo"):
        with pytest.raises(ValueError):
            image_formats_for_suffix(suffix, cover_photo=True)
    with pytest.raises(ValueError):
        image_formats_for_suffix(".wmf")


def _unrestricted_opens(tree: ast.AST) -> list[int]:
    """AST guard: no Image.open and no imported PIL.Image.open aliases."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "PIL.Image":
            if any(name.name == "open" for name in node.names):
                found.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (node.func.attr == "open" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "Image"):
                found.append(node.lineno)
    return sorted(set(found))


def test_only_shared_helper_calls_pillow_image_open():
    direct = []
    for folder in CODE_DIRS:
        directory = ROOT / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.py")):
            if path == ROOT / "app" / "image_open.py":
                continue
            for line in _unrestricted_opens(ast.parse(path.read_text(encoding="utf-8"))):
                direct.append(f"{path.relative_to(ROOT)}:{line}")
    assert not direct, "Use app.image_open.open_image with explicit formats: " + ", ".join(direct)


def test_multipage_tiff_receipts_still_use_their_supported_decoder():
    """Only the receipt pipeline retains TIFF, without enabling TIFF for photos."""
    from app.expense_report import receipt_attachment_pages

    buffer = BytesIO()
    Image.new("RGB", (24, 16), "white").save(
        buffer, "TIFF", save_all=True,
        append_images=[Image.new("RGB", (24, 16), "blue")],
    )
    pages = receipt_attachment_pages(buffer.getvalue(), "synthetic-receipt.tiff")
    assert len(pages) == 2
    for raw in pages:
        with open_image(BytesIO(raw), formats=("JPEG",)) as preview:
            assert preview.format == "JPEG"


def test_guard_detects_direct_pillow_open():
    assert _unrestricted_opens(ast.parse("from PIL import Image\nImage.open(b'photo')\n")) == [2]
    assert _unrestricted_opens(ast.parse("from PIL.Image import open as other\n")) == [1]


def test_open_helper_passes_restriction_to_pillow(monkeypatch):
    seen = {}
    def fake_open(source, *, formats):
        seen["formats"] = formats
        return "opened"
    monkeypatch.setattr(Image, "open", fake_open)
    assert open_image(BytesIO(b""), formats=("PNG",)) == "opened"
    assert seen["formats"] == ("PNG",)
    with pytest.raises(ValueError):
        open_image(BytesIO(b""), formats=())
