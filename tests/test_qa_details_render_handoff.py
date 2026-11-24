"""Open actual QA disclosure only after native fixture render replaces it."""
import ast
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path('scripts/qa_monthly_live.py')


def helper():
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'open_qa_details')
    namespace = {'re': __import__('re'), 'time': __import__('time'),
                 'BrowserTimeout': TimeoutError}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['open_qa_details']


def test_render_finishes_before_opening_replacement_disclosure():
    events = []
    state = {'rendering': True, 'open': True}
    class Locator:
        @property
        def first(self):
            return self
        def wait_for(self, **kwargs):
            events.append('visible')
        def scroll_into_view_if_needed(self, **kwargs):
            events.append('scroll')
        def is_visible(self):
            return state['open']
        def evaluate(self, expression):
            return state['open']
        def click(self):
            assert not state['rendering']
            events.append('open')
            state['open'] = True
    class Page:
        def wait_for_function(self, expression, **kwargs):
            assert 'notRunning' in expression
            events.append('finish-render')
            state.update(rendering=False, open=False)
        def get_by_text(self, *args, **kwargs):
            return Locator()
    helper()(Page())
    assert events == ['finish-render', 'visible', 'scroll', 'open', 'visible']
    assert state['open']


def test_already_open_disclosure_is_not_toggled_closed():
    calls = []
    status = SimpleNamespace(is_visible=lambda: True)
    label = SimpleNamespace(wait_for=lambda **kwargs: None, scroll_into_view_if_needed=lambda **kwargs: None, click=lambda: calls.append('click'))
    page = SimpleNamespace(wait_for_function=lambda *a, **k: calls.append('idle'),
        get_by_text=lambda text, **kwargs: SimpleNamespace(first=label if isinstance(text, str) else status))
    helper()(page)
    assert calls == ['idle']


def test_requested_committed_state_precedes_idle_and_disclosure_open():
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'await_fixture_state')
    guarded = next(n for n in node.body if isinstance(n, ast.Try))
    calls = guarded.body
    assert isinstance(calls[0].value, ast.Call)
    assert calls[0].value.func.attr == 'to_have_text'
    assert calls[1].value.func.id == 'open_qa_details'
    assert calls[2].value.func.attr == 'wait_for'
    assert calls[3].value.func.attr == 'to_have_text'


def test_scroll_restoration_cannot_turn_open_action_into_close():
    state = {'open': False}
    clicks = []
    def restore(**kwargs):
        state['open'] = True
    label = SimpleNamespace(wait_for=lambda **kwargs: None,
        scroll_into_view_if_needed=restore, click=lambda: clicks.append('wrong-close'))
    status = SimpleNamespace(is_visible=lambda: state['open'])
    page = SimpleNamespace(wait_for_function=lambda *a, **k: None,
        get_by_text=lambda text, **kwargs: SimpleNamespace(first=label if isinstance(text, str) else status))
    helper()(page)
    assert state['open'] and not clicks


def test_open_disclosure_hidden_by_rerun_is_not_clicked_closed():
    """An open disclosure whose status is not painted yet must not be toggled."""
    clicks, waits = [], []
    state = {'painted': False}
    def wait_status(timeout=None):
        waits.append(timeout)
        if len(waits) == 1:
            raise TimeoutError('not painted yet')
        state['painted'] = True
    label = SimpleNamespace(wait_for=lambda **kwargs: None,
        scroll_into_view_if_needed=lambda **kwargs: None,
        evaluate=lambda expression: True, click=lambda: clicks.append('wrong-close'))
    status = SimpleNamespace(is_visible=lambda: state['painted'], wait_for=wait_status)
    page = SimpleNamespace(wait_for_function=lambda *a, **k: None,
        get_by_text=lambda text, **kwargs: SimpleNamespace(first=label if isinstance(text, str) else status))
    helper()(page)
    assert state['painted'] and not clicks and waits == [3000, 3000]
