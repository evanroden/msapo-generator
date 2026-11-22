"""Decode the image a browser journey currently shows, across a re-render.

Kept free of Playwright imports so its unit tests run in the ordinary test
environment, which installs no browser packages.
"""

ATTEMPTS = 3

# Decode one element, then read that same element's size and source in the
# same call. Separate calls each resolve the locator again: a re-render in
# between swaps the element, and the later read can see a new image that has
# not loaded yet (main d662220d, 21 Nov: a WebKit row recorded a decoded image
# with height 0, another with width 0).
DECODE_AND_MEASURE = """async (node) => {
    await node.decode();
    return {width: node.naturalWidth, height: node.naturalHeight,
            src: node.getAttribute('src') || ''};
}"""


def decode_current(image, wait_ready, *, attempts=ATTEMPTS):
    """Decode the current image; return its size, source and the attempts taken.

    A preview that re-renders replaces its <img> or src while the browser is
    decoding it: the old node's decode() rejects with EncodingError, or it
    reports no natural size. `image` is a locator, so each attempt resolves
    the element on the page now. The size and source returned are those of
    the element that was decoded, never of a later lookup. An image that is
    genuinely broken still fails after `attempts` tries.
    """
    for attempt in range(1, attempts + 1):
        wait_ready(image)
        try:
            measured = image.evaluate(DECODE_AND_MEASURE)
        except Exception as exc:
            if "EncodingError" not in str(exc) or attempt == attempts:
                raise
            continue
        if measured["width"] > 0 and measured["height"] > 0:
            return {"attempts": attempt, "width": measured["width"],
                    "height": measured["height"], "src": measured["src"]}
    raise AssertionError(f"The current image decoded without a size in {attempts} attempts.")
