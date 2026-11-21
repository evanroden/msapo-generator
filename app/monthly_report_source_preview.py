"""Bounded source thumbnails stay available for their native image lifetime."""
from base64 import b64encode


def source_thumbnail_uri(image):
    # page_image(preview=True) already verifies and normalizes these bytes.
    # Keep only that small displayed image in its native element, so advancing
    # the review cannot retire its media URL before a delayed browser read.
    # Originals, print assets and the report preview cache are unchanged.
    mime = {"png": "image/png", "jpg": "image/jpeg"}.get(image.extension)
    if (mime is None or not image.data or len(image.data) > 2 * 1024 * 1024
            or any(type(size) is not int or not 0 < size <= 1056
                   for size in (image.width, image.height))):
        raise ValueError("This source preview could not be prepared within its image limit. "
                         "Re-upload a smaller, readable copy of this page.")
    return "data:" + mime + ";base64," + b64encode(image.data).decode("ascii")
