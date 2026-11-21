"""Browser journeys decode the image the page shows now, even after a re-render."""
import importlib
import sys

import pytest


@pytest.fixture
def image_decode(monkeypatch):
    # CI installs no browser packages: the helper must import without them.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.delitem(sys.modules, "scripts.image_decode", raising=False)
    return importlib.import_module("scripts.image_decode")


class _Image:
    """A locator whose element is replaced by re-renders; outcomes run in order."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.current = None
        self.ready = 0

    def evaluate(self, script):
        if "decode()" in script:
            self.current = self.outcomes.pop(0)
            if self.current == "swapped":
                raise RuntimeError("Locator.evaluate: EncodingError: The source image cannot be decoded.")
            if self.current == "error":
                raise RuntimeError("Locator.evaluate: TypeError: node.decode is not a function")
            return None
        return self.current == "sized"


def _ready(image):
    image.ready += 1


def test_decoded_image_with_a_size_takes_one_attempt(image_decode):
    image = _Image(["sized"])
    assert image_decode.decode_current(image, _ready) == 1
    assert image.ready == 1


def test_image_swapped_mid_decode_is_decoded_again(image_decode):
    image = _Image(["swapped", "empty", "sized"])
    assert image_decode.decode_current(image, _ready) == 3
    assert image.ready == 3


def test_an_image_that_never_decodes_still_fails(image_decode):
    with pytest.raises(RuntimeError, match="EncodingError"):
        image_decode.decode_current(_Image(["swapped"] * 3), _ready)
    with pytest.raises(AssertionError, match="without a size"):
        image_decode.decode_current(_Image(["empty"] * 3), _ready)


def test_other_errors_are_not_retried(image_decode):
    image = _Image(["error", "sized"])
    with pytest.raises(RuntimeError, match="TypeError"):
        image_decode.decode_current(image, _ready)
    assert image.ready == 1
