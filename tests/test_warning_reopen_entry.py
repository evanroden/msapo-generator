"""One intentional cold-entry wheel is not permission to repair in-flow jumps."""
import ast
from copy import deepcopy
import inspect
import sys
from types import SimpleNamespace

import pytest
from scripts import qa_warning_routes as qa


def boundary(monkeypatch,*,visible=False,invalid=None):
    events=[];viewport={'width':390,'height':844};box={'x':16,'y':60 if visible else 1250,'width':358,'height':53}
    saved={'sequence':12,'scope':'exact-report','generation':'same-device',
           'working':{'fingerprint':'saved-report','fields':{'caption':'kept'}},
           'shared':{'fingerprint':'saved-report'},'originals':{'source':'immutable'}}
    reopened={**deepcopy(saved),'sequence':1};state=deepcopy(reopened)
    if invalid=='in-flow':reopened['sequence']=saved['sequence']
    if invalid=='changed-report':reopened['working']['fingerprint']='changed'
    if invalid=='changed-original':reopened['originals']['source']='changed'
    if invalid=='foreign-scope':reopened['scope']='other'
    if invalid=='wrong-shared':reopened['shared']['fingerprint']='other'
    if invalid=='stale-receipt':state['working']['fingerprint']='other'
    if invalid=='foreign-current':state['scope']='other'
    class Node:
        def __init__(self,name):self.name=name
        def locator(self,selector):
            if self.name=='workspace':
                assert selector in ('.st-key-monthly_report_navigation','xpath=ancestor::*[@data-testid="stMain"]')
                return nodes['nav' if selector.startswith('.') else 'port']
            assert self.name=='nav'
            return nodes[{'.epc-section-progress':'progress','.epc-section-next':'next','.epc-section-back':'back'}[selector]]
        def bounding_box(self):
            if self.name=='nav':return None if invalid=='missing-box' else deepcopy(box)
            assert self.name=='port';return {'x':0,'y':0,'width':390,'height':844}
        def evaluate(self,script,point):
            assert self.name=='port' and script=='(node,p)=>node.contains(document.elementFromPoint(p.x,p.y))'
            assert point=={'x':195,'y':422};return invalid!='obscured-port'
    nodes={name:Node(name) for name in ('workspace','nav','progress','next','back','port')}
    class Expect:
        def __init__(self,node):self.node=node
        def to_have_count(self,count):
            actual=2 if invalid=='duplicate-owner' and self.node.name=='workspace' else 1
            assert actual==count
        def to_have_attribute(self,key,value):
            actual={'data-test-scroll-behavior':'normal','data-epc-confined':'true' if invalid=='confined' else 'false',
                    'data-section':'monthly_activity' if invalid=='non-cover' else 'monthly_cover'}[key]
            assert actual==value
        def to_have_text(self,value):assert value=='1 of 14 · Cover'
        def to_be_disabled(self):assert self.node.name=='back' and invalid!='back-enabled'
        def to_be_in_viewport(self,ratio):
            assert ratio==1 and self.node.name in ('progress','next')
            events.append(('strict-viewport',self.node.name))
            assert box['y']>=0 and box['y']+box['height']<=844
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    class Mouse:
        def move(self,x,y):assert (x,y)==(195,422);events.append(('native-move',x,y))
        def wheel(self,x,y):
            assert x==0 and y==854.5;events.append(('native-wheel',x,y))
            if invalid!='wheel-no-effect':box['y']-=y
            if invalid=='changed-after':state['working']['fields']['caption']='changed'
            if invalid=='foreign-after':state['scope']='other'
    page=SimpleNamespace(viewport_size=viewport,mouse=Mouse(),
        locator=lambda selector:nodes['workspace'] if selector=='.st-key-epc_workspace_monthly' else None,
        reload=lambda **kw:events.append(('reload',kw)))
    monkeypatch.setattr(qa,'receipt',lambda page:deepcopy(state))
    return page,saved,reopened,events,box,Expect


def test_actual_callsite_reenters_only_after_exact_cold_reopen_equality(monkeypatch):
    page,saved,reopened,events,box,Expect=boundary(monkeypatch)
    tree=ast.parse(inspect.getsource(qa.exercise))
    body=next(n.body for n in ast.walk(tree) if isinstance(n,ast.Try) and any(isinstance(x,ast.Expr) and ast.unparse(x.value).startswith('page.reload(') for x in n.body))
    start=next(i for i,n in enumerate(body) if isinstance(n,ast.Expr) and ast.unparse(n.value).startswith('page.reload('))
    stop=next(i for i,n in enumerate(body[start+1:],start+1) if isinstance(n,ast.Expr) and ast.unparse(n.value).startswith('navigate_sections('))
    def navigate(page,target,**kw):
        assert target=='report_review' and kw=={'keyboard':True}
        events.append(('unchanged-sequential',));assert box['y']+box['height']<=844
    ns={'page':page,'saved':saved,'record':{},'receipt':lambda p:deepcopy(reopened),
        'resume_reopened_workspace':getattr(qa,'resume_reopened_workspace',None),'navigate_sections':navigate,'keyboard':True}
    exec(compile(ast.Module(body=body[start:stop+1],type_ignores=[]),qa.__file__,'exec'),ns)
    assert ns['record']=={'reopen_verified':True}
    assert [e[0] for e in events]==['reload','native-move','native-wheel','strict-viewport','strict-viewport','unchanged-sequential']


def test_already_visible_reopened_cover_does_not_scroll_or_focus(monkeypatch):
    page,saved,reopened,events,_,_=boundary(monkeypatch,visible=True)
    qa.resume_reopened_workspace(page,saved,reopened)
    assert events==[('strict-viewport','progress'),('strict-viewport','next')]


@pytest.mark.parametrize('invalid',['in-flow','non-cover','changed-report','changed-original','foreign-scope','wrong-shared','stale-receipt','foreign-current','confined','duplicate-owner','back-enabled','missing-box','obscured-port'])
def test_no_gesture_for_in_flow_wrong_report_or_unowned_entry(monkeypatch,invalid):
    page,saved,reopened,events,_,_=boundary(monkeypatch,invalid=invalid)
    with pytest.raises(AssertionError):qa.resume_reopened_workspace(page,saved,reopened)
    assert not events


@pytest.mark.parametrize('invalid',['wheel-no-effect','changed-after','foreign-after'])
def test_failed_entry_or_changed_state_is_not_retried_or_tolerated(monkeypatch,invalid):
    page,saved,reopened,events,_,_=boundary(monkeypatch,invalid=invalid)
    with pytest.raises(AssertionError):qa.resume_reopened_workspace(page,saved,reopened)
    assert len([e for e in events if e[0]=='native-wheel'])==1


def test_helper_has_one_postreload_callsite_and_no_inflow_navigation_changes():
    tree=ast.parse(inspect.getsource(qa.exercise))
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='resume_reopened_workspace']
    assert len(calls)==1
    helper=inspect.getsource(qa.resume_reopened_workspace)
    assert helper.count('page.mouse.wheel(')==1 and 'scrollIntoView' not in helper and '.focus(' not in helper
    assert 'sleep(' not in helper and 'timeout=' not in helper and 'while ' not in helper
    assert len(qa.required_cases())==16
    source=inspect.getsource(qa.exercise)
    assert "expect(visible).to_be_in_viewport(ratio=1)" in source
    assert "commit(warning_action(code,block,source_page=source_page,ordinal=ordinal));focus_proof(control)" in source
