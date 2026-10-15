"""The observer must never change browser launch settings or swallow QA failures."""
from types import SimpleNamespace

import pytest

from scripts.qa_browser_diagnostics import observe, target_path


class Context:
    def __init__(self):
        self.events = []
        self.tracing = SimpleNamespace(start=lambda **kw: self.events.append(('trace-start', kw)),
                                       stop=lambda **kw: self.events.append(('trace-stop', kw)))

    def add_init_script(self, script):
        self.events.append(('script', script))

    def on(self, event, fn):
        self.events.append(('listener', event))

    def close(self, **kwargs):
        self.events.append(('close', kwargs))


class Browser:
    browser_type = SimpleNamespace(name='webkit')

    def new_context(self, **kwargs):
        self.received = kwargs
        self.context = Context()
        return self.context


def test_only_existing_synthetic_scripts_are_accepted():
    assert target_path('qa_monthly_adaptive.py').name == 'qa_monthly_adaptive.py'
    assert target_path('qa_shared_fixture_testing.py').name == 'qa_shared_fixture_testing.py'
    for name in ('https://example.invalid', '../run_web.py', 'qa_monthly_live.py'):
        with pytest.raises(ValueError):
            target_path(name)


def test_observation_preserves_context_options_and_close(tmp_path):
    original = Browser.new_context
    browser = Browser()
    with observe(tmp_path, Browser, Context):
        ctx = browser.new_context(viewport={'width': 390, 'height': 844})
        assert browser.received == {'viewport': {'width': 390, 'height': 844}}
        ctx.close(reason='normal')
    assert Browser.new_context is original
    assert ctx.events[-2][0] == 'trace-stop'
    assert ctx.events[-1] == ('close', {'reason': 'normal'})
    assert len(list(tmp_path.glob('*-events.jsonl'))) == 1


def test_original_assertion_is_not_swallowed_and_context_is_cleaned(tmp_path):
    browser = Browser()
    with pytest.raises(AssertionError, match='original failed gate'):
        with observe(tmp_path, Browser, Context):
            ctx = browser.new_context()
            raise AssertionError('original failed gate')
    assert ctx.events[-1][0] == 'close'
