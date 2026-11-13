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


# ENFRA's own page furniture from an authorized current Word reference report
# (RRH Unity & USH, October 2026): the cover/heading wordmark, the full header
# wordmark, the stripes-only header mark and the plain header colour panel.
# Identities are exact file bytes and decoded pixels, keyed by pixel size.
# They are company design, never a site photograph or a client's logo, so a
# master/starting report keeps them and an import never asks what they are.
_COMPANY_ARTWORK_BYTES = frozenset({
    'e9a5d18d3808765485b394afb679cab493371e3608358f0cfef86b952d734c8a',  # 497x80 wordmark
    '8d845a1bf7a61d6324fbf72e7c1f296a8ea14aab5fd4600c92af05b7c52b7240',  # 1800x290 wordmark
    'f7a01ee3f5a54e6afda693e9a1dcb2eb92e1b9dd6b99c51db251b91c46af4c94',  # 146x81 mark
    'b083f80cf6173b44ba5049e451f1a72c1de40b922c291f7bf01b02906b0f3a7f',  # 200x200 panel
})
_COMPANY_ARTWORK_PIXELS = {
    (497, 80): '48ea24dd2faccecc45718ec2f27a340ea632f0d8524228b1fbc0f37d90da3cab',
    (1800, 290): '8a115470b356ca2a302a1c1795fa21cd819532e0bc704b331f7e9b1c631c9f51',
    (146, 81): '9e01c947b9dc69fd0c47c2573a5bf6e56a273e619bc685f1f28a11221dea53fa',
    (200, 200): 'e55a7f99ebf49cc0d92448f3cb8f2ebf08691bb66bd3f933a9954956879547de',
}


def is_company_artwork_digest(digest):
    """Exact ENFRA furniture bytes, as recorded by Word import inspection."""
    return bool(digest) and digest in _COMPANY_ARTWORK_BYTES


def is_company_artwork_blob(raw):
    """The same ENFRA furniture, also after a lossless re-save of the PNG."""
    if not raw or len(raw) > 131072:
        return False
    if hashlib.sha256(raw).hexdigest() in _COMPANY_ARTWORK_BYTES:
        return True
    try:
        with Image.open(BytesIO(raw)) as image:
            expected = _COMPANY_ARTWORK_PIXELS.get(image.size)
            if expected is None:
                return False
            image.load()
            return hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest() == expected
    except (OSError, ValueError, zlib.error, EOFError, Image.DecompressionBombError):
        return False
