"""Harness contracts only; these do not claim real browser acceptance."""
import inspect
import sys
from types import ModuleType

from scripts import qa_shared_fixture_testing as qa


def test_review_journey_never_precommits_or_retries_the_native_click(monkeypatch):
    events = []

    class Control:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, action):
            return lambda *args: events.append((self.name, action, *args))

    class Page:
        def get_by_role(self, role, *, name, exact):
            assert exact
            return Control(name)

        def locator(self, selector):
            return Control(selector)

    # Unit-test our action ordering without requiring a browser installation.
    sync_api = ModuleType("playwright.sync_api")
    sync_api.expect = lambda control: control
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)
    monkeypatch.setattr(qa, "idle", lambda page: events.append(("idle",)))
    monkeypatch.setattr(qa, "check", lambda *args: events.append(("check", args[1])))

    def durable(page, root, expected):
        assert root == "isolated-root" and expected == qa.REVIEW_TEXT
        events.append(("durable", expected))
        return {"revision": 2}

    monkeypatch.setattr(qa, "durable_activity", durable)
    monkeypatch.setattr(qa, "section_order", lambda page: [
        {'id': 'monthly_cover'}, {'id': 'monthly_activity'}, {'id': 'monthly_final'}, {'id': 'report_review'}])
    monkeypatch.setattr(qa, "navigate_sections", lambda page, target, **kwargs:
                        events.append(("navigate", target, kwargs)))
    qa.sequential_review_journey(Page(), "isolated-root", "synthetic-engine")
    fill = events.index(("Activity summary", "fill", qa.REVIEW_TEXT))
    click = events.index((".epc-section-next", "click"))
    durable_index = events.index(("durable", qa.REVIEW_TEXT))
    focus = events.index(("#report-review", "to_be_focused"))
    assert events[fill + 1:click] == [("Activity summary", "to_be_focused")]
    assert fill < click < durable_index < focus
    assert events.count((".epc-section-next", "click")) == 2
    assert events.count((".epc-section-next", "press", "Enter")) == 1
    assert len([event for event in events if event[:2] == ("navigate", "monthly_activity")]) == 3
    assert events.count(("Activity summary", "to_have_value", qa.REVIEW_TEXT)) == 2
    assert events.count(("durable", qa.REVIEW_TEXT)) == 3
    keyboard = events.index((".epc-section-next", "press", "Enter"))
    assert events[keyboard - 2:keyboard] == [
        (".epc-section-back", "press", "Tab"), (".epc-section-next", "to_be_focused")]


def test_continue_acceptance_requires_cover_before_sequential_activity():
    source = inspect.getsource(qa)
    start = source.index('phase["name"] = "enter ordered report/editor after import"')
    end = source.index('capture(page, name, "imported-current-report")', start)
    entry = source[start:end]
    assert '.st-key-epc_pair_monthly_cover' in entry
    assert entry.index('Continue starts directly at Cover') < entry.index('navigate_sections(page, "monthly_activity")')
    assert 'select_option' not in entry
    assert 'coverSection.contains(document.activeElement)' in entry
