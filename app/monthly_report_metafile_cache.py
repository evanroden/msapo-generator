"""Read only intact, bounded disposable PNG previews of reviewed Word vectors.

The renderer's original EMF/WMF input and the rendered Word package are not
modified here. An unusable derived file is a cache miss, never source approval.
"""

from io import BytesIO
import os
import stat
import warnings

from PIL import Image

MAX_CACHED_VECTOR_PNG_BYTES = 24 * 1024 * 1024
MAX_CACHED_VECTOR_PNG_EDGE = 2400
MAX_CACHED_VECTOR_PNG_PIXELS = 5_000_000


def cached_vector_png(path, *, limit=MAX_CACHED_VECTOR_PNG_BYTES):
    """Return verified PNG bytes, or None so the original can be rerendered.

    Limit the *actual* read, require a regular non-symlink file, and validate
    the PNG CRC plus the expected 200-dpi chart-preview pixel envelope. A
    corrupted/missing derivative is not proof that the original is corrupt.
    """
    if type(limit) is not int or limit < 1 or limit > MAX_CACHED_VECTOR_PNG_BYTES:
        raise ValueError("Invalid cached chart preview size limit.")
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            data = stream.read(limit + 1)
    except (OSError, ValueError):
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > limit:
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                width, height = picture.size
                if (picture.format != "PNG" or not 0 < width <= MAX_CACHED_VECTOR_PNG_EDGE
                        or not 0 < height <= MAX_CACHED_VECTOR_PNG_EDGE
                        or width * height > MAX_CACHED_VECTOR_PNG_PIXELS):
                    return None
                picture.verify()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning,
            Image.DecompressionBombError):
        return None
    return data
