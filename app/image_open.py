"""Constrain Pillow decoder selection before untrusted image headers are parsed.

Call sites explicitly choose the formats they already accept; formats are
passed to Pillow at open time rather than checked after plugin selection.
"""

from __future__ import annotations

from PIL import Image

_FORMAT_BY_SUFFIX = {
    ".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
    ".gif": "GIF", ".webp": "WEBP",
    # Pillow recognizes MPO files through its JPEG opener.
    ".mpo": "JPEG",
    ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF",
    ".heic": "HEIF", ".heif": "HEIF", ".hif": "HEIF",
}
_WORD_VECTOR_SUFFIXES = {".emf": "WMF", ".wmf": "WMF"}
_COVER_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".hif"})
_ALLOWED_FORMATS = frozenset(_FORMAT_BY_SUFFIX.values()) | {"WMF"}


def image_formats_for_suffix(
    suffix: str, *, cover_photo: bool = False, word_media: bool = False
) -> tuple[str, ...]:
    """Return one format from a validated upload/Word-media suffix.

    Only Word-media callers can select Pillow's WMF plugin, which handles EMF
    headers as well. This never enables vectors for ordinary image uploads.
    """
    normalized = suffix.casefold() if isinstance(suffix, str) else ""
    image_format = _FORMAT_BY_SUFFIX.get(normalized)
    if image_format is None and word_media:
        image_format = _WORD_VECTOR_SUFFIXES.get(normalized)
    if image_format is None or (cover_photo and normalized not in _COVER_SUFFIXES):
        raise ValueError("Unsupported image format for this upload.")
    return (image_format,)


def open_image(source, *, formats: tuple[str, ...]):
    """Open using only caller-authorized decoders, before identifying the image."""
    if (not isinstance(formats, tuple) or not formats
            or any(fmt not in _ALLOWED_FORMATS for fmt in formats)):
        raise ValueError("An explicit supported image-format allowlist is required.")
    return Image.open(source, formats=formats)
