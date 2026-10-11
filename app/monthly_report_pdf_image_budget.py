"""Bound JPEG photos in a disposable Word-to-PDF conversion copy only.

The original editable Word file and all its source-media bytes are unchanged.
Only high-resolution JPEGs *identical to media in the pinned native design*
may be reduced, never newly uploaded diagrams or customer photos. This avoids
the Word assembler's decoded-image heap overlapping a hungry LibreOffice
converter on the 512 MiB single-instance production service.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import ctypes
import gc
import sys


MAX_EDGE = 1400
MIN_AREA = 2_000_000
MAX_SOURCE_MEDIA = 100


def _photograph(name: str) -> bool:
    return name.startswith("word/media/") and name.lower().endswith((".jpg", ".jpeg"))


@lru_cache(maxsize=8)
def _original_jpeg_hashes(source_path: str) -> frozenset[str]:
    """Immutable, already content-verified Word design; cache *hashes* only."""
    with ZipFile(source_path) as archive:
        names = [n for n in archive.namelist() if _photograph(n)]
        if len(names) > MAX_SOURCE_MEDIA:
            raise ValueError("The native design has too many photos to optimize safely.")
        # One compressed entry at a time; do not decode or retain old clients'
        # source photographs. Never inspect the unrelated current-report assets.
        return frozenset(sha256(archive.read(name)).hexdigest() for name in names)


def compact_native_photos_for_pdf(raw: bytes, *, pinned_source: Path,
                                   max_edge: int = MAX_EDGE) -> bytes:
    """Reduce JPEGs matching the pinned master, and nothing else.

    Existing page geometry, font drawing, native Word table grids, and names
    remain untouched. This disposable copy is used ONLY for PDF conversion.
    No JPEG in the master: return the exact original bytes.
    """
    from PIL import Image, UnidentifiedImageError

    if not 600 <= max_edge <= 2500:
        raise ValueError("Invalid bounded PDF photograph dimension.")
    allowed = _original_jpeg_hashes(str(pinned_source))
    if not allowed:
        return raw
    changed = False
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(output, "w") as converted:
        for info in original.infolist():
            data = original.read(info.filename)
            if (_photograph(info.filename) and sha256(data).hexdigest() in allowed):
                try:
                    with Image.open(BytesIO(data)) as source:
                        width, height = source.size
                        if (max(width, height) > max_edge and width * height >= MIN_AREA
                                and width * height <= 40_000_000
                                and source.getexif().get(274, 1) == 1):
                            # Only bounded RGB photographs are eligible. JPEG
                            # schematics with a panoramic ratio remain sharp.
                            ratio = width / height
                            if 0.5 <= ratio <= 3:
                                image = source.convert("RGB")
                                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                                dst = BytesIO()
                                image.save(dst, "JPEG", quality=88, optimize=True)
                                reduced = dst.getvalue()
                                if len(reduced) < len(data):
                                    data = reduced
                                    changed = True
                except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                    # Unreadable images remain byte-identical; the original
                    # editable DOCX was never modified, and no source is lost.
                    pass
            converted.writestr(info, data)
    return output.getvalue() if changed else raw


def release_transient_word_memory() -> None:
    """Release temporary OOXML allocations *before* starting LibreOffice.

    Only Linux glibc supports malloc_trim; it is an optional, no-fail
    optimization after Python references have already been released.
    """
    gc.collect()
    if sys.platform != "linux":
        return
    try:
        libc = ctypes.CDLL(None)
        trim = getattr(libc, "malloc_trim", None)
        if trim is not None:
            trim(0)
    except (OSError, AttributeError):
        pass
