"""The observer must never change browser launch settings or swallow QA failures."""
from types import SimpleNamespace
import json

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


@pytest.mark.parametrize("stage", ["start", "stop"])
@pytest.mark.parametrize("journey_fails", [False, True])
def test_trace_failure_is_recorded_without_changing_journey_result(tmp_path, stage, journey_fails):
    context = Context()
    def fail(**kwargs):
        raise RuntimeError("Synthetic tracing unavailable")
    setattr(context.tracing, stage, fail)
    class Browser:
        browser_type=SimpleNamespace(name="webkit")
        def new_context(self, **kwargs):
            return context
    def journey():
        with observe(tmp_path, Browser, Context):
            opened=Browser().new_context(viewport={"width":390,"height":844})
            assert opened is context
            try:
                if journey_fails:
                    raise AssertionError("Original journey failure")
            finally:
                opened.close(reason="journey completed")
    if journey_fails:
        with pytest.raises(AssertionError,match="Original journey failure"):
            journey()
    else:
        journey()
    assert context.events[-1]==("close",{"reason":"journey completed"})
    rows=[json.loads(line) for line in next(tmp_path.glob("*-events.jsonl")).read_text().splitlines()]
    errors=[row for row in rows if row["kind"]=="diagnostic-error"]
    assert len(errors)==1
    assert errors[0]["detail"]["stage"]==stage
    assert "Synthetic tracing unavailable" in errors[0]["detail"]["error"]
    if stage=="start":
        assert not any(name=="trace-stop" for name,_ in context.events)


def test_actual_context_creation_failure_is_not_suppressed(tmp_path):
    class Browser:
        def new_context(self,**kwargs):
            raise RuntimeError("Actual browser context failure")
    with pytest.raises(RuntimeError,match="Actual browser context failure"):
        with observe(tmp_path,Browser,Context):
            Browser().new_context()


def test_explicit_history_fixture_port_keeps_both_socket_observers_attached(tmp_path):
    from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
    from scripts.workspace_wire_observations import WireObservations

    class Socket:
        url = 'ws://127.0.0.1:8542/_stcore/stream'
        def __init__(self):
            self.listeners = {}
        def on(self, event, listener):
            self.listeners.setdefault(event, []).append(listener)

    class Page:
        def __init__(self):
            self.listeners = {}
        def on(self, event, listener):
            self.listeners.setdefault(event, []).append(listener)

    class HistoryContext(Context):
        def on(self, event, listener):
            super().on(event, listener)
            if event == 'page':
                self.page_listener = listener

    class HistoryBrowser(Browser):
        def new_context(self, **kwargs):
            return HistoryContext()

    with observe(tmp_path, HistoryBrowser, HistoryContext, widget_ports=(8542,)):
        context = HistoryBrowser().new_context()
        page = Page()
        context.page_listener(page)
        wire = WireObservations(8542)
        wire.attach(page)
        socket = Socket()
        for listener in page.listeners['websocket']:
            listener(socket)
        payload = ForwardMsg(script_finished=ForwardMsg.FINISHED_SUCCESSFULLY).SerializeToString()
        for listener in socket.listeners['framereceived']:
            listener(payload)
        context.close()
    rows = [json.loads(line) for line in next(tmp_path.glob('*-events.jsonl')).read_text().splitlines()]
    assert [row['detail']['kind'] for row in rows if row['kind'] == 'widget-wire'] == ['script_finished']
    assert wire.snapshot()['total_events'] == 1
