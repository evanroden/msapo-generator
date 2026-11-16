"""Constrain Pillow decoder selection to the formats authorized by each caller.

A filename suffix establishes whether a source is an eligible upload or Word
media part. It does not prove the bytes' format; Pillow identifies those bytes
using only the decoders allowed by that context.
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
_RASTER_FORMATS = ("JPEG", "PNG", "GIF", "WEBP", "BMP", "TIFF", "HEIF")
_COVER_FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")
_WORD_MEDIA_FORMATS = (*_RASTER_FORMATS, "WMF")
_ALLOWED_FORMATS = frozenset(_WORD_MEDIA_FORMATS)
_HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"})


def image_formats_for_suffix(
    suffix: str, *, cover_photo: bool = False, word_media: bool = False
) -> tuple[str, ...]:
    """Return a context allowlist, not a decoder chosen by an untrusted suffix.

    Cover photos admit only supported photographic codecs. General source
    images and receipts retain their raster decoders; WMF/EMF are Word-only.
    Unsupported suffixes are still rejected at the upload boundary.
    """
    normalized = suffix.casefold() if isinstance(suffix, str) else ""
    if cover_photo:
        if normalized not in _COVER_SUFFIXES:
            raise ValueError("Unsupported image format for this upload.")
        return _COVER_FORMATS
    if normalized not in _FORMAT_BY_SUFFIX and not (
        word_media and normalized in _WORD_VECTOR_SUFFIXES
    ):
        raise ValueError("Unsupported image format for this upload.")
    return _WORD_MEDIA_FORMATS if word_media else _RASTER_FORMATS


def _register_heif_from_header(source) -> None:
    """Admit a supported HEIF file even when its filename has another suffix."""
    try:
        offset = source.tell()
        try:
            header = source.read(12)
        finally:
            source.seek(offset)
    except (AttributeError, OSError, ValueError):
        return
    if (len(header) >= 12 and header[4:8] == b"ftyp"
            and header[8:12] in _HEIF_BRANDS):
        from pillow_heif import register_heif_opener
        register_heif_opener(thumbnails=False)


def open_image(source, *, formats: tuple[str, ...]):
    """Open with explicitly authorized decoders before Pillow identifies bytes."""
    if (not isinstance(formats, tuple) or not formats
            or any(fmt not in _ALLOWED_FORMATS for fmt in formats)):
        raise ValueError("An explicit supported image-format allowlist is required.")
    if "HEIF" in formats:
        _register_heif_from_header(source)
    return Image.open(source, formats=formats)
