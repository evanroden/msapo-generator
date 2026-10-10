"""Only independently identified company artwork may survive master reuse.

Pixel identities below come from inspected, authorized ENFRA Word/PDF reference
pairs. They are not guesses from aspect ratio, filename or document position.
No source pictures or font binaries are embedded in public application code.
"""
from functools import lru_cache
import hashlib
from io import BytesIO
from pathlib import Path
import re
import zlib
from zipfile import ZipFile, BadZipFile

from PIL import Image

# Two variants of the same 409x37 ENFRA Create/Sustain/Empower wordmark from
# actual historical Word reference reports. Approved as *company page furniture*,
# never as a new site's client logo, cover art, or site-specific photograph.
_APPROVED_WORDMARK_PIXELS = frozenset({
    '76ca9aa78b5c3fc04778c1f4c5d1571fae3b96535ac633f36a1e53978454c38b',
    '6c315f2625837a13e7c319a6e527b269b56cb6b47c2a99041491b4efbc4f8f3a',
})


@lru_cache(maxsize=64)
def _fingerprint(source_path: str, source_sha256: str, image_part: str) -> str:
    if not re.fullmatch(r'word/media/[A-Za-z0-9_.-]{1,100}', image_part):
        return ''
    try:
        with ZipFile(Path(source_path)) as archive:
            info = archive.getinfo(image_part)
            if not 0 < info.file_size <= 65536:
                return ''
            raw = archive.read(image_part)
        with Image.open(BytesIO(raw)) as image:
            if image.size != (409, 37):
                return ''
            image.load()
            return hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()
    except (OSError, ValueError, KeyError, BadZipFile, zlib.error, EOFError, Image.DecompressionBombError):
        return ''


def is_approved_company_slogan(source_path, source_sha256, item):
    if item.image_width != 409 or item.image_height != 37:
        return False
    return _fingerprint(str(source_path), source_sha256, item.image_part) in _APPROVED_WORDMARK_PIXELS
