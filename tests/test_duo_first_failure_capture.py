"""Evidence is captured before browser teardown; failures never become retries."""
from pathlib import Path
import ast
from contextlib import contextmanager
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'scripts/qa_duo_compact_portrait.py').read_text())
helper=next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name=='capture_first_failure')
namespace={'contextmanager':contextmanager, 'OUT':None}
exec(compile(ast.Module(body=[helper], type_ignores=[]), '<capture-helper>', 'exec'), namespace)
duo=SimpleNamespace(**namespace)

class Page:
    def __init__(self, broken=False): self.calls=[]; self.broken=broken
    def screenshot(self, **kw):
        self.calls.append(kw)
        if self.broken: raise RuntimeError('capture failed')
    def content(self): return '<html>invented fixture</html>'
class Trace:
    def __init__(self): self.paths=[]
    def stop(self, **kw): self.paths.append(kw)
class Context:
    def __init__(self): self.tracing=Trace()

@pytest.mark.parametrize('broken', [False, True])
def test_original_failure_reraised_and_trace_retained(tmp_path, monkeypatch, broken):
    monkeypatch.setitem(namespace, 'OUT', tmp_path)
    page, context, record = Page(broken), Context(), {}
    original=AssertionError('native preview missing')
    with pytest.raises(AssertionError) as caught:
        with duo.capture_first_failure(page, context, record): raise original
    assert caught.value is original
    assert record['first_failure']['type']=='AssertionError'
    assert len(page.calls)==1 and page.calls[0]['full_page']
    assert context.tracing.paths==[{'path':str(tmp_path/'trace.zip')}]
    if broken: assert record['capture_error']=='RuntimeError'
    else: assert (tmp_path/'first-failure.html').read_text().startswith('<html>')

def test_success_keeps_trace_without_failure_artifacts(tmp_path, monkeypatch):
    monkeypatch.setitem(namespace, 'OUT', tmp_path)
    page, context, record = Page(), Context(), {}
    with duo.capture_first_failure(page, context, record): pass
    assert record=={} and page.calls==[] and len(context.tracing.paths)==1
