"""Hosted harness action ordering; not browser acceptance evidence."""
import sys
from types import ModuleType

import pytest

from scripts import monthly_sequential_navigation as qa


@pytest.mark.parametrize('keyboard', [False, True])
def test_every_intervening_step_is_activated_once_and_verified(monkeypatch, keyboard):
    events = []
    entries = [{'id': key, 'title': key} for key in ('cover', 'activity', 'final', 'report_review')]

    class Page:
        index = 0

        def locator(self, selector):
            return Control(self, selector)

    class Control:
        def __init__(self, page, selector):
            self.page, self.selector = page, selector

        def get_attribute(self, name):
            assert name == 'data-section'
            return entries[self.page.index]['id']

        def click(self):
            events.append(('click', self.selector))
            self.page.index += 1 if self.selector.endswith('next') else -1

        def press(self, key):
            assert key == 'Enter'
            events.append(('press', self.selector))
            self.page.index += 1 if self.selector.endswith('next') else -1

        def to_have_attribute(self, name, value):
            if isinstance(value, str):
                assert value == entries[self.page.index]['id']
                events.append(('arrival', value))

        def to_have_text(self, text):
            if self.selector.endswith('progress'):
                assert text == f"{self.page.index + 1} of 4 · {entries[self.page.index]['title']}"

        def __getattr__(self, action):
            return lambda *args, **kwargs: events.append((action, self.selector))

    sync_api = ModuleType('playwright.sync_api')
    sync_api.expect = lambda control: control
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', sync_api)
    monkeypatch.setattr(qa, 'section_order', lambda page: entries)
    page = Page()
    qa.navigate_sections(page, 'report_review', keyboard=keyboard)
    qa.navigate_sections(page, 'cover', keyboard=keyboard)
    assert [event[1] for event in events if event[0] == 'arrival'] == [
        'activity', 'final', 'report_review', 'final', 'activity', 'cover']
    activations = [event for event in events if event[0] in ('click', 'press')]
    assert activations == [(('press' if keyboard else 'click'), '.epc-section-next')] * 3 + [
        (('press' if keyboard else 'click'), '.epc-section-back')] * 3
    assert ('to_be_disabled', '.epc-section-next') in events
    assert ('to_be_disabled', '.epc-section-back') in events
