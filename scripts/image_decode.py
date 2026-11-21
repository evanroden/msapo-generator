"""Decode the image a browser journey currently shows, across a re-render.

Kept free of Playwright imports so its unit tests run in the ordinary test
environment, which installs no browser packages.
"""

ATTEMPTS = 3


def decode_current(image, wait_ready, *, attempts=ATTEMPTS):
    """Decode the current image; return how many attempts it took.

    A preview that re-renders replaces its <img> or src while the browser is
    decoding it: the old node's decode() rejects with EncodingError, or it
    reports no natural size. `image` is a locator, so each attempt resolves
    the element on the page now. An image that is genuinely broken still fails
    after `attempts` tries.
    """
    for attempt in range(1, attempts + 1):
        wait_ready(image)
        try:
            image.evaluate("(node) => node.decode()")
        except Exception as exc:
            if "EncodingError" not in str(exc) or attempt == attempts:
                raise
            continue
        if image.evaluate("(node) => node.naturalWidth > 0 && node.naturalHeight > 0"):
            return attempt
    raise AssertionError(f"The current image decoded without a size in {attempts} attempts.")
