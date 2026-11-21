"""Browser journeys reload once, on the record, only when the front end never mounts."""
import importlib
import sys

import pytest


@pytest.fixture
def blank_start(monkeypatch):
    # CI installs no browser packages: the helper must import without them.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.delitem(sys.modules, "scripts.blank_start", raising=False)
    return importlib.import_module("scripts.blank_start")


class _Locator:
    def __init__(self, page):
        self.page = page

    def wait_for(self, state, timeout):
        assert state == "attached" and timeout == self.page.module.BLANK_START_SECONDS * 1000
        if not self.page.mounted:
            raise TimeoutError("app root never attached")


class _Page:
    def __init__(self, module, mounted):
        self.module, self.mounted = module, mounted
        self.calls = []

    def goto(self, url, wait_until):
        assert (url, wait_until) == ("http://127.0.0.1:8534", "domcontentloaded")
        self.calls.append("goto")

    def locator(self, selector):
        assert selector == self.module.APP_ROOT
        return _Locator(self)

    def evaluate(self, script):
        return "complete" if "readyState" in script else 0

    def reload(self, wait_until):
        assert wait_until == "domcontentloaded"
        self.calls.append("reload")


def _clock(page):
    # Each reading notes which navigations had already happened.
    readings = []

    def clock():
        readings.append(tuple(page.calls))
        return float(len(readings))
    return clock, readings


def _diagnostics():
    return {"aborted_requests": [], "page_errors": [], "console_errors": [], "blank_starts": [],
            "failed_requests": ["GET /static/js/index.js net::ERR_EMPTY_RESPONSE"]}


def test_mounted_front_end_is_not_reloaded_and_is_timed_from_its_load(blank_start):
    page, diagnostics = _Page(blank_start, mounted=True), _diagnostics()
    clock, readings = _clock(page)
    assert blank_start.open_app(page, "http://127.0.0.1:8534", diagnostics, clock=clock) == (0, 1.0)
    assert page.calls == ["goto"] and readings == [()]
    assert diagnostics["blank_starts"] == []


def test_blank_start_reloads_once_keeps_what_the_browser_saw_and_times_from_the_reload(blank_start):
    page, diagnostics = _Page(blank_start, mounted=False), _diagnostics()
    clock, readings = _clock(page)
    reloads, started = blank_start.open_app(page, "http://127.0.0.1:8534", diagnostics, clock=clock)
    assert (reloads, page.calls) == (1, ["goto", "reload"])
    # The recovered sample's clock starts after the blank load and before the reload.
    assert started == 2.0 and readings == [(), ("goto",)]
    blank, = diagnostics["blank_starts"]
    assert blank["ready_state"] == "complete" and blank["body_children"] == 0
    assert blank["failed_requests"] == ["GET /static/js/index.js net::ERR_EMPTY_RESPONSE"]
