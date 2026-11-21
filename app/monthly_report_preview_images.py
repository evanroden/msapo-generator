"""Reduce pixels only in disposable preview inputs, without changing geometry."""
from io import BytesIO
from hashlib import sha256
from pathlib import Path
import math
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image

from app.image_open import open_image
from app.monthly_report_media_privacy import clear_transparent_png_rgb, strip_image_metadata


MAX_PIXELS = 2_500_000
MAX_EDGE = 1800
# One disposable DOCX conversion owns this local cache. No cross-report,
# cross-site, cross-user or persistent decoded-pixel cache is permitted.
MAX_RENDITION_CACHE_BYTES = 8 * 1024 * 1024
MAX_RENDITION_ENTRY_BYTES = 2 * 1024 * 1024


def _smaller_image(data):
    with open_image(BytesIO(data), formats=("JPEG", "PNG")) as image:
        if image.format not in ('JPEG', 'PNG'):
            return data
        width, height = image.size
        if width * height <= MAX_PIXELS and max(width, height) <= MAX_EDGE:
            return data
        if width * height > 40_000_000:
            raise ValueError('This picture is too large to prepare a preview safely.')
        scale = min(1, MAX_EDGE / width, MAX_EDGE / height, math.sqrt(MAX_PIXELS / (width * height)))
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        # JPEG draft decoding avoids first expanding a phone photograph to its
        # full resolution. Retain format, alpha and orientation semantics.
        image.draft(image.mode, size)
        image.thumbnail(size, Image.Resampling.LANCZOS)
        output = BytesIO()
        options = {'quality': 86, 'optimize': False} if image.format == 'JPEG' else {'compress_level': 3}
        if image.info.get('exif'):
            options['exif'] = image.info['exif']
        if image.info.get('dpi'):
            options['dpi'] = image.info['dpi']
        # Color profiles survive the privacy pass and must survive resizing.
        if image.info.get('icc_profile'):
            options['icc_profile'] = image.info['icc_profile']
        image.save(output, format=image.format, **options)
        return output.getvalue()


def write_preview_docx(raw, path):
    """Stream a disposable conversion copy with a bounded, package-owned cache.

    Only already encoded *preview* renditions are cached, never decoded Pillow
    rasters or full-resolution print assets. A fresh invocation has a fresh
    cache, so identical content from a different report/owner cannot be reused
    or become visible across source identities.
    """
    renditions: dict[bytes, bytes] = {}
    cache_bytes = 0
    with ZipFile(BytesIO(raw)) as source, ZipFile(Path(path), 'w', ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith('word/media/') and Path(info.filename).suffix.lower() in ('.png', '.jpg', '.jpeg'):
                # Hash before opening/decoding so repeated media parts share
                # one conversion. The key is scoped to this source package.
                key = sha256(data).digest()
                if key in renditions:
                    data = renditions[key]
                else:
                    try:
                        data = _smaller_image(data)
                        # Do not rely on the upstream privacy pass alone:
                        # direct callers must not expose embedded author/device
                        # metadata or the RGB hidden behind transparent pixels.
                        data = clear_transparent_png_rgb(strip_image_metadata(data))
                    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
                        raise ValueError('A picture cannot be read safely for this preview.') from exc
                    if (len(data) <= MAX_RENDITION_ENTRY_BYTES
                            and cache_bytes + len(data) <= MAX_RENDITION_CACHE_BYTES):
                        renditions[key] = data
                        cache_bytes += len(data)
            target.writestr(info, data)
