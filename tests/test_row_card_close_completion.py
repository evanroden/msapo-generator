"""A structural Close must acknowledge its own render, not the previous idle receipt."""
import ast
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_report_row_cards.py'


def helper(namespace):
    tree = ast.parse(SOURCE.read_text())
    function = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == 'close_proposal'), None)
    assert function is not None, 'Close needs its own structural completion acknowledgement'
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace['close_proposal'], function


def test_previous_idle_receipt_is_not_a_close_acknowledgement():
    _, function = helper({})
    expression = next(n.value for n in ast.walk(function) if isinstance(n, ast.Constant)
                      and isinstance(n.value, str) and '=>' in n.value)
    tree = ast.parse(SOURCE.read_text())
    receipt = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'receipt')
    old_expression = next(n.value for n in ast.walk(receipt) if isinstance(n, ast.Constant)
                          and isinstance(n.value, str) and 'wanted =>' in n.value)
    script = r'''
const assert=require('node:assert/strict');
const [freshSource,oldSource]=JSON.parse(require('fs').readFileSync(0,'utf8'));
const predicate=eval('('+freshSource+')'),old=eval('('+oldSource+')');
let token='old',state='notRunning';
global.document={querySelectorAll:()=>[{dataset:{enfraRowReceipt:JSON.stringify({working:{rows:{}},durable:{rows:{}}})}}],
 querySelector:s=>s.includes('stApp')?
 {getAttribute:()=>state}:{dataset:{epcFullRender:token}}};
// Captured failing order: old durable==working and idle, then running old,
// then a new completed render. Only the last is an acknowledgement.
assert.equal(old({field:null}),true);assert.equal(predicate('old'),false);
state='running';assert.equal(predicate('old'),false);
token='new';assert.equal(predicate('old'),false);
state='notRunning';assert.equal(predicate('old'),true);
token='';assert.equal(Boolean(predicate('old')),false);
'''
    subprocess.run(['node', '-e', script], input=json.dumps([expression,old_expression]), text=True,
                   capture_output=True, check=True, timeout=10)


@pytest.mark.parametrize('blocked', [None, 'render', 'editor', 'read card'])
def test_one_native_close_waits_for_fresh_render_and_exact_closed_ui(blocked):
    page, panel = Mock(), Mock()
    events=[]
    page.locator.return_value.get_attribute.side_effect=lambda name: events.append('before') or 'old'
    close=Mock()
    def role(role, *, name, exact):
        assert exact
        return close if name=='Close editing' else (role,name)
    panel.get_by_role.side_effect=role
    close.click.side_effect=lambda: events.append('click')
    def wait(expression, *, arg, timeout):
        assert events==['before','click'] and arg=='old' and timeout==30000
        events.append('fresh')
        if blocked=='render':raise AssertionError('render')
    page.wait_for_function.side_effect=wait
    def expect(locator):
        assertion=Mock()
        def count(n):
            assert n==0 and 'fresh' in events
            if blocked=='editor':raise AssertionError('editor')
            events.append('closed')
        def visible():
            assert locator==('button','Edit proposal') and events.count('closed')==3
            if blocked=='read card':raise AssertionError('read card')
            events.append('ready')
        assertion.to_have_count.side_effect=count
        assertion.to_be_visible.side_effect=visible
        return assertion
    run,_=helper({})
    if blocked:
        with pytest.raises(AssertionError,match=blocked):run(page,panel,expect)
        assert 'ready' not in events
    else:
        run(page,panel,expect);assert events[-1]=='ready'
    assert close.click.call_count==1


def test_all_proposal_closes_use_ack_without_changing_request_gestures():
    tree=ast.parse(SOURCE.read_text())
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
    closes=[n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='close_proposal']
    assert len(closes)==3
    assert all(len(n.args)==3 and isinstance(n.args[-1],ast.Name) and n.args[-1].id=='expect' for n in closes)
    source=SOURCE.read_text()
    assert source.count("requests.get_by_role('button',name='Add request',exact=True).click()") == 2
    assert "expect(requests.get_by_role('textbox',name='Requested item',exact=True)).to_be_focused()" in source


def test_rapid_onsite_to_proposal_transition_stays_native_and_uninterrupted():
    source = SOURCE.read_text()
    start = source.index("onsite.get_by_role('button',name='Close editing',exact=True).click()", source.index("# Retain the original rapid"))
    end = source.index("expect(proposal.get_by_role('textbox',name='Status'", start)
    assert source[start:end].strip().splitlines() == [
        "onsite.get_by_role('button',name='Close editing',exact=True).click()",
        "        proposal=page.locator(PROPOSALS)",
        "        proposal.get_by_role('button',name='Edit proposal',exact=True).click()"]
