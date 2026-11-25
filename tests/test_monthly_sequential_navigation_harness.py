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

def test_adaptive_entry_scrolls_once_before_strict_sequential_journey():
    """Setup may start above the workspace; traversal itself cannot rescue."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path('scripts/qa_monthly_adaptive.py').read_text())
    exercise = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'exercise')
    calls = sorted((node for node in ast.walk(exercise) if isinstance(node, ast.Call)), key=lambda node: node.lineno)
    scrolls = [node for node in calls if getattr(node.func, 'attr', '') == 'scroll_into_view_if_needed']
    assert len(scrolls) == 1
    scroll = scrolls[0]
    assert ast.literal_eval(scroll.func.value.args[0]) == '.epc-section-navigation'
    setup = next(node for node in calls if getattr(node.func, 'id', '') == 'exercise_site_selection')
    first_navigation = next(node for node in calls if getattr(node.func, 'id', '') == 'navigate_sections')
    assert setup.lineno < scroll.lineno < first_navigation.lineno
    helper = ast.parse(Path('scripts/monthly_sequential_navigation.py').read_text())
    assert not any(isinstance(node, ast.Call) and 'scroll' in getattr(node.func, 'attr', '') for node in ast.walk(helper))
