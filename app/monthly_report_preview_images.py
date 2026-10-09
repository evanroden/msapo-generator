"""Reduce pixels only in disposable preview inputs, without changing geometry."""
from io import BytesIO
from pathlib import Path
import math
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image


MAX_PIXELS = 2_500_000
MAX_EDGE = 1800


def _smaller_image(data):
    with Image.open(BytesIO(data)) as image:
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
        image.save(output, format=image.format, **options)
        return output.getvalue()


def write_preview_docx(raw, path):
    """Stream the preview copy to disk; never hold a second whole ZIP in RAM."""
    with ZipFile(BytesIO(raw)) as source, ZipFile(Path(path), 'w', ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith('word/media/') and Path(info.filename).suffix.lower() in ('.png', '.jpg', '.jpeg'):
                try:
                    data = _smaller_image(data)
                except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
                    raise ValueError('A picture cannot be read safely for this preview.') from exc
            target.writestr(info, data)
