"""Bound JPEG photos in a disposable Word-to-PDF conversion copy only.

The editable Word file is unchanged by this PDF-only compaction.
Only high-resolution JPEGs identical to media in the pinned native design,
or to their exact metadata-sanitized copies, may be reduced, never unrelated
uploaded diagrams or customer photos. This avoids
the Word assembler's decoded-image heap overlapping a hungry LibreOffice
converter on the 512 MiB single-instance production service.
"""
from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from app.image_open import open_image
import ctypes
import gc
import sys


MAX_EDGE = 1400
MIN_AREA = 2_000_000
MAX_SOURCE_MEDIA = 100


def _photograph(name: str) -> bool:
    return name.startswith("word/media/") and name.lower().endswith((".jpg", ".jpeg"))


def _source_revision(source_path: Path) -> tuple[int, int, int, int, int]:
    """Filesystem identity for a pinned, possibly replaced native design.

    A path alone is not an immutable cache key. Track both atomic replacement
    (device/inode) and in-place writes (size/timestamps); ctime distinguishes
    rewrites even when a caller restores the original mtime.
    """
    stat = source_path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


@lru_cache(maxsize=8)
def _original_jpeg_hashes(source_path: str, revision: tuple[int, int, int, int, int]) -> frozenset[str]:
    """Cache only approved media digests for one pinned file revision, not its path."""
    from app.monthly_report_media_privacy import strip_image_metadata

    with ZipFile(source_path) as archive:
        names = [n for n in archive.namelist() if _photograph(n)]
        if len(names) > MAX_SOURCE_MEDIA:
            raise ValueError("The native design has too many photos to optimize safely.")
        # One compressed entry at a time; do not decode or retain old clients'
        # source photographs. Never inspect the unrelated current-report assets.
        hashes = set()
        for name in names:
            data = archive.read(name)
            hashes.add(sha256(data).hexdigest())
            # Export privacy removes metadata before PDF conversion. Recognize
            # only that exact derivative of a verified pinned image, keeping
            # the same source allowlist without admitting unrelated uploads.
            hashes.add(sha256(strip_image_metadata(data)).hexdigest())
        return frozenset(hashes)


def compact_native_photos_for_pdf(raw: bytes, *, pinned_source: Path,
                                   max_edge: int = MAX_EDGE) -> bytes:
    """Reduce RGB JPEGs matching the pinned master, and nothing else.

    Existing page geometry, font drawing, native Word table grids, and names
    remain untouched. This disposable copy is used ONLY for PDF conversion.
    Keep color profiles and exactly encodable density; other modes or unusual
    densities retain their original bytes instead of changing interpretation.
    No JPEG in the master: return the exact original bytes.
    """
    from PIL import Image, UnidentifiedImageError

    if not 600 <= max_edge <= 2500:
        raise ValueError("Invalid bounded PDF photograph dimension.")
    # A design may be replaced without moving its installed path. Invalidate
    # the hash allowlist for every new revision rather than authorizing old
    # images or silently missing new ones. Fail/retry if it changes mid-read.
    revision = _source_revision(pinned_source)
    allowed = _original_jpeg_hashes(str(pinned_source), revision)
    if _source_revision(pinned_source) != revision:
        raise ValueError("The pinned Word design changed during PDF preparation. Retry generation.")
    if not allowed:
        return raw
    changed = False
    # Repeated occurrences of the same immutable photo within one DOCX need
    # only one decode/resize. Keep derivatives local to this conversion; a
    # cross-session media cache would retain other clients' image data.
    reduced_cache: dict[str, bytes] = {}
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as original, ZipFile(output, "w") as converted:
        for info in original.infolist():
            data = original.read(info.filename)
            media_digest = sha256(data).hexdigest() if _photograph(info.filename) else ""
            if media_digest and media_digest in allowed:
                if media_digest in reduced_cache:
                    data = reduced_cache[media_digest]
                    changed = True
                    converted.writestr(info, data)
                    continue
                try:
                    with open_image(BytesIO(data), formats=("JPEG",)) as source:
                        width, height = source.size
                        dpi = source.info.get("dpi")
                        # The JPEG writer rounds density to 16-bit integer DPI.
                        # Preserve unusual densities rather than round or wrap.
                        density_encodable = not dpi or all(
                            0 < value <= 65535 and int(value) == value for value in dpi)
                        if (source.mode == "RGB" and density_encodable
                                and max(width, height) > max_edge and width * height >= MIN_AREA
                                and width * height <= 40_000_000
                                and source.getexif().get(274, 1) == 1):
                            # Only bounded RGB photographs are eligible. JPEG
                            # schematics with a panoramic ratio remain sharp.
                            ratio = width / height
                            if 0.5 <= ratio <= 3:
                                image = source.copy()
                                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                                dst = BytesIO()
                                # Carry permitted display metadata with the same
                                # RGB interpretation; do not copy author metadata.
                                options = {}
                                if source.info.get("icc_profile"):
                                    options["icc_profile"] = source.info["icc_profile"]
                                if dpi:
                                    options["dpi"] = dpi
                                image.save(dst, "JPEG", quality=88, optimize=True, **options)
                                reduced = dst.getvalue()
                                if len(reduced) < len(data):
                                    data = reduced
                                    changed = True
                                    # At most four <= 2 MiB derivatives per
                                    # conversion (8 MiB total), never global.
                                    if len(reduced_cache) < 4 and len(reduced) <= 2 * 1024 * 1024:
                                        reduced_cache[media_digest] = reduced
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
