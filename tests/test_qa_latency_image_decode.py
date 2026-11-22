"""Browser journeys decode the image the page shows now, even after a re-render."""
import importlib
import sys

import pytest


def _browser_free(monkeypatch, name):
    # CI installs no browser packages: the helpers must import without them.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.delitem(sys.modules, name, raising=False)
    return importlib.import_module(name)


@pytest.fixture
def image_decode(monkeypatch):
    return _browser_free(monkeypatch, "scripts.image_decode")


@pytest.fixture
def click_retry(monkeypatch):
    return _browser_free(monkeypatch, "scripts.click_retry")


SIZED = {"width": 1020, "height": 1320, "src": "data:image/png;base64,current"}
EMPTY = {"width": 0, "height": 0, "src": "data:image/png;base64,loading"}


class _Image:
    """A locator whose element is replaced by re-renders; outcomes run in order.

    After each call the page re-renders: a further lookup would find a new
    element that has not loaded yet, so any second read returns no size.
    """

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.ready = 0
        self.calls = []

    def evaluate(self, script):
        self.calls.append(script)
        if "decode()" not in script:
            return dict(EMPTY)  # A later, separate lookup sees the swapped element.
        current = self.outcomes.pop(0)
        if current == "swapped":
            raise RuntimeError("Locator.evaluate: EncodingError: The source image cannot be decoded.")
        if current == "error":
            raise RuntimeError("Locator.evaluate: TypeError: node.decode is not a function")
        return dict(SIZED if current == "sized" else EMPTY)


def _ready(image):
    image.ready += 1


def test_decoded_image_with_a_size_takes_one_attempt(image_decode):
    image = _Image(["sized"])
    assert image_decode.decode_current(image, _ready) == {
        "attempts": 1, "width": 1020, "height": 1320, "src": SIZED["src"]}
    assert image.ready == 1


def test_size_and_source_come_from_the_decoded_element_in_the_same_call(image_decode):
    # main d662220d, 21 Nov: separate reads after decoding recorded height 0
    # for a decoded WebKit image, because a re-render had swapped the element.
    image = _Image(["sized"])
    measured = image_decode.decode_current(image, _ready)
    assert len(image.calls) == 1
    assert "decode()" in image.calls[0] and "naturalWidth" in image.calls[0]
    assert "naturalHeight" in image.calls[0] and "src" in image.calls[0]
    assert measured["width"] > 0 and measured["height"] > 0


def test_image_swapped_mid_decode_is_decoded_again(image_decode):
    image = _Image(["swapped", "empty", "sized"])
    assert image_decode.decode_current(image, _ready)["attempts"] == 3
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


class _Control:
    """A harmless control whose first `lost` clicks never take effect."""

    def __init__(self, lost):
        self.lost = lost
        self.clicks = 0

    def click(self):
        self.clicks += 1

    def shown(self):
        return self.clicks > self.lost


def test_a_click_whose_result_appears_is_not_repeated(click_retry):
    control, lines = _Control(lost=0), []
    assert click_retry.click_until_shown(control.click, control.shown, report=lines.append) == 1
    assert control.clicks == 1 and lines == []


def test_a_lost_click_is_retried_and_reported(click_retry):
    # 21 Nov, capped Chromium on main 8a6cd19b and on #955: the Preview button
    # was still on screen, unclicked, and the caption never appeared.
    control, lines = _Control(lost=1), []
    assert click_retry.click_until_shown(control.click, control.shown, report=lines.append) == 2
    assert control.clicks == 2
    assert lines == ["RETRY click: its result did not appear after click 1"]


def test_a_result_that_never_appears_still_fails(click_retry):
    control, lines = _Control(lost=99), []
    with pytest.raises(AssertionError, match="did not appear after 3 clicks"):
        click_retry.click_until_shown(control.click, control.shown, report=lines.append)
    assert control.clicks == 3 and len(lines) == 2
