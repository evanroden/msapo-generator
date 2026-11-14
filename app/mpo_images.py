"""Bounded MPO frame inventory; callers retain the original and choose frames."""
from io import BytesIO

from PIL import Image


def frame_count(raw: bytes) -> int:
    from app.ocr import _MAX_IMAGE_FRAMES, _MAX_PIXELS_PER_FRAME

    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "MPO":
                raise ValueError("This MPO file is not a readable multi-picture image. Export a fresh copy.")
            try:
                count = image.n_frames
            except (TypeError, AttributeError) as exc:
                raise ValueError("MPO frame information could not be read. Export a fresh copy.") from exc
            if type(count) is not int or count < 1:
                raise ValueError("MPO frame information could not be read. Export a fresh copy.")
            if count > _MAX_IMAGE_FRAMES:
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
    except (OSError, EOFError, SyntaxError) as exc:
        # Opening and seeking MPO frames may fail in Pillow before raster decode.
        # A malformed in-memory original is a file rejection, not a disk outage.
        raise ValueError("MPO image data is damaged or truncated. Export a fresh copy.") from exc
