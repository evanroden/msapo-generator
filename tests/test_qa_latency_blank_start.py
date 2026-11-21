"""The latency journey reloads once, on the record, only when the front end never mounts."""
import importlib
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def journey(monkeypatch):
    # The QA scripts import their siblings by bare name, as when run directly.
    monkeypatch.syspath_prepend(str(SCRIPTS))
    return importlib.import_module("scripts.qa_monthly_preview_browser_latency")


class _Locator:
    def __init__(self, page):
        self.page = page

    def wait_for(self, state, timeout):
        assert state == "attached" and timeout == self.page.journey.BLANK_START_SECONDS * 1000
        self.page.waits += 1
        if not self.page.mounted:
            raise TimeoutError("app root never attached")


class _Page:
    def __init__(self, journey, mounted):
        self.journey, self.mounted = journey, mounted
        self.waits = self.reloads = self.gotos = 0

    def goto(self, url, wait_until):
        assert (url, wait_until) == (self.journey.URL, "domcontentloaded")
        self.gotos += 1

    def locator(self, selector):
        assert selector == self.journey.APP_ROOT
        return _Locator(self)

    def evaluate(self, script):
        return "complete" if "readyState" in script else 0

    def reload(self, wait_until):
        assert wait_until == "domcontentloaded"
        self.reloads += 1


def _diagnostics():
    return {"aborted_requests": [], "page_errors": [], "failed_requests": ["GET /static/js/index.js net::ERR_EMPTY_RESPONSE"],
            "console_errors": [], "blank_starts": []}


def test_mounted_front_end_is_not_reloaded(journey):
    page, diagnostics = _Page(journey, mounted=True), _diagnostics()
    assert journey._open_app(page, diagnostics) == 0
    assert (page.gotos, page.reloads) == (1, 0)
    assert diagnostics["blank_starts"] == []


def test_blank_start_reloads_once_and_keeps_what_the_browser_saw(journey):
    page, diagnostics = _Page(journey, mounted=False), _diagnostics()
    assert journey._open_app(page, diagnostics) == 1
    assert (page.gotos, page.reloads) == (1, 1)
    blank, = diagnostics["blank_starts"]
    assert blank["ready_state"] == "complete" and blank["body_children"] == 0
    assert blank["failed_requests"] == ["GET /static/js/index.js net::ERR_EMPTY_RESPONSE"]
