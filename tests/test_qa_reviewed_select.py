"""The reviewed-work-orders journey scrolls the combobox that a finished run rendered."""
import importlib
import sys

import pytest

DETACHED = RuntimeError("Locator.scroll_into_view_if_needed: Element is not attached to the DOM")


@pytest.fixture
def journey(monkeypatch):
    # CI installs no browser packages: the helper must import without them.
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.delitem(sys.modules, "scripts.qa_reviewed_work_orders", raising=False)
    module = importlib.import_module("scripts.qa_reviewed_work_orders")
    events = []
    monkeypatch.setattr(module, "settled", lambda page, predicate: events.append(("settled", predicate)))
    return module, events


class _Control:
    def __init__(self, events, errors):
        self.events, self.errors = events, list(errors)

    def scroll_into_view_if_needed(self):
        self.events.append(("scroll",))
        if self.errors:
            raise self.errors.pop(0)


def test_each_attempt_waits_for_the_run_and_a_replaced_control_is_scrolled_again(journey):
    module, events = journey
    assert module.scroll_to_control(object(), _Control(events, [DETACHED])) == 2
    assert events == [("settled", "v=>true"), ("scroll",), ("settled", "v=>true"), ("scroll",)]


def test_any_other_scroll_error_fails_at_once(journey):
    module, events = journey
    with pytest.raises(TimeoutError):
        module.scroll_to_control(object(), _Control(events, [TimeoutError("Timeout 30000ms exceeded")]))
    assert events == [("settled", "v=>true"), ("scroll",)]


def test_a_control_replaced_on_every_attempt_still_fails(journey):
    module, events = journey
    with pytest.raises(RuntimeError, match="not attached"):
        module.scroll_to_control(object(), _Control(events, [DETACHED] * 3))
    assert events.count(("scroll",)) == 3
