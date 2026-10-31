import ast
import json
from pathlib import Path
import subprocess
import pytest
from scripts.qa_navigation_observations import observe_navigation, _bounded_result, MAX_BYTES


def payload():
    return dict(schema=1, limits={'records':256,'bytes':MAX_BYTES}, dropped=0, errors=0, disposed=True, records=[])

@pytest.mark.parametrize('extra', [{'text':'secret'}, {'url':'https://private.example'}, {'source':'private'}, {'target':float('nan')}, {'records':[None]*257}])
def test_reject_unknown_payload(extra):
    data=payload(); data['records']=[extra]
    assert _bounded_result(data,True)['schema_rejected']

def test_accept_minimal_payload():
    assert _bounded_result(payload(),True)['installation_completed']

@pytest.mark.parametrize('install_fail,stop_fail',[(False,False),(True,False),(False,True),(True,True)])
def test_cleanup_preserves_original_exception(install_fail,stop_fail):
    class Page:
        calls=0
        def evaluate(self, script):
            self.calls+=1
            if (self.calls==1 and install_fail) or (self.calls==2 and stop_fail):raise RuntimeError('private exception')
            return {'installed':True} if self.calls==1 else payload()
    page=Page();evidence={}
    with pytest.raises(ValueError,match='original'):
        with observe_navigation(page,evidence):raise ValueError('original')
    assert page.calls==2
    assert 'private exception' not in json.dumps(evidence)

def test_native_contract():
    subprocess.run(['node','--test','tests/navigation_observations_test.cjs'],check=True)

def test_context_preserves_original_gesture_order():
    tree=ast.parse(Path('scripts/qa_monthly_text_hydration.py').read_text())
    context=next(n for n in ast.walk(tree) if isinstance(n,ast.With) and any(isinstance(x.context_expr,ast.Call) and getattr(x.context_expr.func,'id','')=='observe_navigation' for x in n.items))
    assert len(context.body)==2
    calls=[n.value for n in context.body]
    assert calls[0].func.attr=='set_viewport_size'
    assert ast.literal_eval(calls[0].args[0])=={'width':390,'height':844}
    assert calls[1].func.id=='correct_issue_warning'
    assert [(k.arg,ast.literal_eval(k.value)) for k in calls[1].keywords]==[('keyboard',True)]


def test_evidence_write_failure_preserves_original():
    class Reject(dict):
        def __setitem__(self,key,value): raise RuntimeError('write failed')
    class Page:
        def evaluate(self,script): return payload()
    with pytest.raises(ValueError,match='original'):
        with observe_navigation(Page(),Reject()): raise ValueError('original')
