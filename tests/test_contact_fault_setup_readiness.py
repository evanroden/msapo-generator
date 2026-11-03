"""A delivered fixture-control click is not proof that the fault was armed."""
import ast
import copy
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_compact_contact_journey.py'


def helper():
    return next(n for n in ast.parse(SOURCE.read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'await_synthetic_fault_armed')


def test_predicate_rejects_unarmed_stale_consumed_and_busy_receipts():
    expression = next(n.value for n in ast.walk(helper())
                      if isinstance(n, ast.Constant) and isinstance(n.value, str) and '=>' in n.value)
    script = r'''
const assert=require('node:assert/strict');
const ready=eval('('+JSON.parse(require('fs').readFileSync(0,'utf8'))+')');
let receipt={sequence:23,fault:{mode:'',armed:0,consumed:0},working:{},durable:{}};
let idle='notRunning',present=true;
global.document={querySelectorAll:()=>present?[{dataset:{enfraContactReceipt:JSON.stringify(receipt)}}]:[],
 querySelector:()=>({getAttribute:()=>idle})};
const expected={after:22,mode:'before',armed:1,consumed:0};
assert.equal(ready(expected),false); // Recorded failing case: native click, never armed.
receipt.fault={mode:'before',armed:1,consumed:0};assert.equal(ready(expected),true);
for(const patch of [{mode:'after'},{armed:0},{armed:2},{consumed:1}]){
 const saved={...receipt.fault};Object.assign(receipt.fault,patch);
 assert.equal(ready(expected),false);receipt.fault=saved;
}
receipt.sequence=22;assert.equal(ready(expected),false);receipt.sequence=23;
idle='running';assert.equal(ready(expected),false);idle='notRunning';
receipt.durable={changed:true};assert.equal(ready(expected),false);receipt.durable={};
present=false;assert.equal(ready(expected),false);
'''
    subprocess.run(['node', '-e', script], input=json.dumps(expression), text=True,
                   capture_output=True, check=True, timeout=10)


@pytest.mark.parametrize('changed', [None, 'working', 'directory', 'attempts', 'scope', 'generation', 'saved_revision'])
def test_setup_is_read_only_and_preserves_canonical_state(changed):
    previous = dict(sequence=22, fault=dict(mode='', armed=0, consumed=0),
                    working={}, directory={}, attempts=[], scope='isolated', generation='g', saved_revision=1)
    armed = copy.deepcopy(previous)
    armed.update(sequence=23, fault=dict(mode='before', armed=1, consumed=0))
    if changed:
        armed[changed] = 'changed'
    namespace = dict(json=json, SELECTOR='[data-enfra-contact-receipt]')
    exec(compile(ast.Module(body=[helper()], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    page = Mock()
    page.locator.return_value.last.get_attribute.return_value = json.dumps(armed)
    if changed:
        with pytest.raises(AssertionError, match=changed):
            namespace['await_synthetic_fault_armed'](page, previous, 'before')
    else:
        assert namespace['await_synthetic_fault_armed'](page, previous, 'before') == armed
    page.wait_for_function.assert_called_once()
    assert page.wait_for_function.call_args.kwargs == dict(
        arg=dict(after=22, mode='before', armed=1, consumed=0), timeout=30000)
    text = ast.unparse(helper())
    for forbidden in ['click(', 'sleep(', 'wait_for_timeout', 'dispatchEvent', '.focus(', 'scrollTo(']:
        assert forbidden not in text


def test_only_ordinary_fault_setup_waits_and_held_challenge_is_preserved():
    source = SOURCE.read_text()
    assert source.count('await_synthetic_fault_armed(page,') == 2
    branch = source[source.index("if held_recovery and fault == 'after':"):source.index("contacts.get_by_role('textbox',name='Phone',exact=True).fill(phone)")]
    assert branch.index('else:') < branch.index('await_synthetic_fault_armed') < branch.index("name='Edit contact'")
    held = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == 'edit_contact_during_recovery_rerun')
    text = ast.unparse(held)
    assert 'await_synthetic_fault_armed' not in text
    assert text.index('page.mouse.down()') < text.index('gate.release()') < text.index('page.mouse.up()')
    assert "assert state['attempts'][-1]['mode'] == fault" in source
    assert "'consumed': prior['fault']['armed'] + 1" in source
