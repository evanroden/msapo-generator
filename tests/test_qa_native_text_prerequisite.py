"""Actual QA helper control-flow contracts; not browser/hydration acceptance."""
import ast
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_text_hydration.py'


def helper(*, current='', pending='Saved issue', continued=True):
    calls = []
    class Field:
        value = current
        def input_value(self):
            calls.append('read'); return self.value
        def get_attribute(self, name):
            assert name == 'id'; calls.append('id'); return 'native-1'
        def fill(self, value):
            calls.append(('fill', value)); self.value = value
        def press(self, key):
            calls.append(('key', key))
        def evaluate(self, _):
            calls.append('continuity')
            return {'inputObserved':True,'sameNode':continued,'inputNodeConnected':continued}
    field = Field()
    class Page:
        def get_by_role(self, role, **kwargs):
            assert role=='textbox' and kwargs=={'name':'Issue description','exact':True}
            calls.append('locator'); return field
        def evaluate(self, script, *args):
            calls.append('cleanup' if script=='window.__enfraTextEditCleanup?.()' else 'observe')
    def expect(locator):
        assert locator is field
        def to_have_value(expected):
            calls.append(('expected', expected))
            # Simulate the browser's later controlled-value delivery; never a
            # helper action. A mismatch must stop the helper before any input.
            field.value = pending
            assert field.value == expected
        return SimpleNamespace(to_have_value=to_have_value)
    def acknowledged(page,label,value):
        calls.append('acknowledged'); assert page is target and field.value==value
    target = Page()
    live = SimpleNamespace(EVIDENCE={'phase':'Issue clear'}, event=lambda *a,**kw:calls.append('request'))
    node=next(n for n in ast.parse(SOURCE.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='commit_text')
    ns={'expect':expect,'sha256':sha256,'live':live,'await_text':acknowledged}
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),ns)
    return lambda text,expected:ns['commit_text'](target,'Issue description',text,expected_before=expected),calls


def test_pending_existing_value_is_established_before_any_native_edit_on_one_locator():
    run,calls=helper()
    run('', 'Saved issue')
    assert calls[:5]==['locator',('expected','Saved issue'),'read','request','id']
    assert calls.count('locator')==1
    assert [c for c in calls if isinstance(c,tuple)and c[0]in{'fill','key'}]==[('fill',''),('key','Tab')]
    assert calls[-3:]==['acknowledged','continuity','cleanup']


def test_missing_expected_value_stops_before_observer_and_native_action():
    run,calls=helper(pending='')
    with pytest.raises(AssertionError):run('', 'Saved issue')
    assert calls==['locator',('expected','Saved issue')]


def test_genuine_no_op_still_fails_before_native_input():
    run,calls=helper(pending='')
    with pytest.raises(AssertionError,match='must change'):run('', '')
    assert 'observe'not in calls
    assert not any(isinstance(c,tuple)and c[0]=='fill'for c in calls)


def test_replaced_input_event_node_still_fails_after_acknowledgment():
    run,calls=helper(continued=False)
    with pytest.raises(AssertionError,match='node was replaced'):run('', 'Saved issue')
    assert 'continuity'in calls and 'acknowledged'in calls
