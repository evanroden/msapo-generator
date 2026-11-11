"""Bounded MPO frame inventory; callers retain the original and choose frames."""
from io import BytesIO

from PIL import Image


def frame_count(raw: bytes) -> int:
    from app.ocr import _MAX_IMAGE_FRAMES, _MAX_PIXELS_PER_FRAME

    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "MPO":
                raise ValueError("This MPO file is not a readable multi-picture image. Export a fresh copy.")
            count = image.n_frames
            if not 1 <= count <= _MAX_IMAGE_FRAMES:
                raise ValueError(f"MPO contains too many frames; the maximum is {_MAX_IMAGE_FRAMES}.")
            pixels = 0
            # seek reads frame headers, not decoded rasters. Bound the complete
            # source before any frame is copied, transposed, normalized or sent.
            for number in range(count):
                image.seek(number)
                width, height = image.size
                pixels += width * height
                if width <= 0 or height <= 0 or pixels > _MAX_PIXELS_PER_FRAME:
                    raise ValueError("MPO frames are too large to decode safely. Export smaller individual images.")
            return count
    except Image.DecompressionBombError as exc:
        raise ValueError("MPO frames are too large to decode safely. Export smaller individual images.") from exc
