"""Execute the actual driver protocol with native option ownership doubles."""
import ast
import inspect
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import qa_warning_routes as qa


def selection(monkeypatch, *, target='source', active=0, invalid=None, keyboard=True):
    labels=['source','shared','ai','financial'];ids=['popup-option-'+str(i) for i in range(4)]
    events=[];state={'active':active,'expanded':False,'focused':False,'value':labels[active]}

    class Options:
        def __init__(self, indexes):self.indexes=indexes
        def get_attribute(self,name):
            assert name=='id' and len(self.indexes)==1
            return ids[self.indexes[0]]
        def evaluate_all(self,script):
            assert script=='nodes=>nodes.map(node=>node.id)'
            return ids if invalid!='duplicate-id' else [ids[0],ids[0],*ids[2:]]
        def click(self):
            events.append(('option click',labels[self.indexes[0]]));state['value']=labels[self.indexes[0]]

    class Popup:
        def get_by_role(self,role,**kwargs):
            assert role=='option'
            if not kwargs:return Options(list(range(4)))
            assert kwargs=={'name':target,'exact':True}
            indexes=[i for i,label in enumerate(labels) if label==target]
            return Options(indexes*2 if invalid=='duplicate-target' else [] if invalid=='missing-target' else indexes)

    popup=Popup()

    class Control:
        def focus(self):events.append(('focus',));state['focused']=invalid!='focus'
        def click(self):events.append(('control click',));state['expanded']=True
        def fill(self,value):
            # Original failing path: filling the selected value is a no-op;
            # existence of that option does not change the native highlight.
            events.append(('query fill',value))
            if value!=state['value']:state['value']=value
        def press(self,key):
            events.append(('key',key))
            if key=='Enter':state['value']=labels[state['active']];return
            assert key in {'ArrowDown','ArrowUp'}
            if invalid=='does-not-move' and state['expanded']:return
            state['expanded']=True
            state['active']=min(3,max(0,state['active']+(1 if key=='ArrowDown' else -1)))
        def get_attribute(self,name):
            if name=='aria-controls':return 'foreign' if invalid=='foreign-popup' else 'popup'
            assert name=='aria-activedescendant'
            return 'foreign-option' if invalid=='foreign-active' else ids[state['active']]

    control=Control()

    class Page:
        keyboard=SimpleNamespace(press=lambda key:events.append(('page key',key)))
        def locator(self,selector):
            assert selector=='[role="listbox"][id='+json.dumps('foreign' if invalid=='foreign-popup' else 'popup')+']'
            return popup
        def get_by_role(self,role,**kwargs):return popup.get_by_role(role,**kwargs)

    class Expect:
        def __init__(self,node):self.node=node
        def to_have_count(self,count):
            actual=len(self.node.indexes) if isinstance(self.node,Options) else 0 if self.node is popup and invalid=='foreign-popup' else 1
            assert actual==count
        def to_be_enabled(self):assert invalid!='disabled' or self.node is control
        def to_be_visible(self):assert self.node is popup
        def to_be_focused(self):assert state['focused']
        def to_have_attribute(self,name,value):
            actual=str(state['expanded']).lower() if name=='aria-expanded' else control.get_attribute(name)
            events.append(('assert',name,value));assert actual==value

    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    nested=next(node for node in ast.walk(ast.parse(inspect.getsource(qa.exercise)))
                if isinstance(node,ast.FunctionDef) and node.name=='select')
    namespace={'page':Page(),'keyboard':keyboard,'expect':Expect,'select_native_option':getattr(qa,'select_native_option',None)}
    exec(compile(ast.Module(body=[nested],type_ignores=[]),qa.__file__,'exec'),namespace)
    return lambda:namespace['select'](control,target),events,state


@pytest.mark.parametrize('target,active', [('source',0),('source',3),('financial',0),('shared',0)])
def test_native_keyboard_chooses_the_exact_owned_target_before_enter(monkeypatch,target,active):
    run,events,state=selection(monkeypatch,target=target,active=active);run()
    assert state['value']==target
    assert events.count(('key','Enter'))==1
    enter=events.index(('key','Enter'))
    assert events[enter-1]==('assert','aria-activedescendant','popup-option-'+str(['source','shared','ai','financial'].index(target)))
    assert not any(event[0] in {'query fill','option click','control click'} for event in events)
    assert len([event for event in events if event[0]=='key'])<=5


@pytest.mark.parametrize('invalid',['foreign-popup','foreign-active','duplicate-id','duplicate-target','missing-target','disabled','focus','does-not-move'])
def test_invalid_native_keyboard_owner_or_failed_key_route_never_enters_or_retries(monkeypatch,invalid):
    run,events,state=selection(monkeypatch,invalid=invalid)
    with pytest.raises(AssertionError):run()
    assert ('key','Enter') not in events
    assert not any(event[0] in {'option click','control click','query fill'} for event in events)
    assert len([event for event in events if event[0]=='key'])<=2


def test_pointer_selection_keeps_one_existing_native_click_per_control_and_option(monkeypatch):
    run,events,state=selection(monkeypatch,target='financial',keyboard=False);run()
    assert state['value']=='financial'
    assert events==[('control click',),('option click','financial'),('page key','Escape')]


def test_installed_scenario_is_acknowledged_before_any_source_or_report_edit():
    source=inspect.getsource(qa.exercise)
    assert "assert initial['scenario']==scenario" in source
    assert source.index("assert initial['scenario']==scenario") < source.index("navigate_sections(page,'monthly_activity'")
    assert len(qa.required_cases())==16


def caption_boundary(monkeypatch, *, initial='old', actual='old', receipt_owner='old',
                     sequence=4, invalid=None, keyboard=True, receipt_initial=None):
    """Execute the driver's actual before-fill block, not a test-only protocol.

    The native and receipt owners are independent, as in the archived financial
    trace: an old idle receipt can coexist with the new target's native editor.
    """
    prefix='report_guided_exact';old={'id':'old-id','filename':'old.pdf'}
    filenames={'old':'old.pdf','target':'target.pdf'}
    key=prefix+'_evidence_selected';events=[];state={'selected':initial,'acted':False}

    class Caption:
        def __init__(self,owner):self.owner=owner
        def fill(self,text):events.append(('fill',self.owner,text))

    class Owner:
        def __init__(self,selector):self.selector=selector
        def get_by_role(self,role,**kwargs):
            assert role=='textbox' and kwargs=={'name':'Page caption','exact':True}
            return Caption('old')
        def locator(self,selector):
            assert selector=='xpath=ancestor-or-self::*[@data-stale="true"]'
            return SimpleNamespace(count=1 if invalid=='stale-body' else 0)

    class Choose:
        def input_value(self):return filenames[state['selected']]

    choose=Choose()

    class Manager:
        def get_by_role(self,role,**kwargs):
            if role=='combobox':
                assert kwargs=={'name':'File to review','exact':True};return choose
            assert role=='textbox' and kwargs=={'name':'Page caption','exact':True}
            return Caption(state['selected'])
        def locator(self,selector):
            assert selector=='.st-key-'+prefix+'_evidence_old-id_caption_1'
            return Owner(selector)

    manager=Manager()

    class Page:
        def locator(self,selector):
            assert selector=='.st-key-'+prefix+'_source_manager_panel';return manager
        def wait_for_function(self,script,*,arg,timeout):
            assert '.sequence>old' in script and timeout==120000
            events.append(('fresh-receipt',arg));assert sequence>arg,'Stale source-selection receipt'

    page=Page()

    def read_receipt(page_arg,expected=None):
        assert page_arg is page
        owner=receipt_owner if state['acted'] else (receipt_initial or initial)
        result={'sequence':sequence if state['acted'] else 3,'selected':{key:owner+'-id'}}
        events.append(('receipt',result['sequence'],owner))
        if expected:assert expected=={'selected.'+key:owner+'-id'}
        return result

    def select(page_arg,control,label,*,keyboard=False):
        assert page_arg is page and control is choose and label==old['filename']
        events.append(('select',keyboard));state.update(selected=actual,acted=True)

    class Expect:
        def __init__(self,node):self.node=node
        def to_have_count(self,count):
            if isinstance(self.node,Owner):
                actual_count=2 if invalid=='duplicate-owner' else 0 if invalid in {'missing-owner','wrong-report','wrong-page'} or state['selected']!='old' else 1
            else:actual_count=getattr(self.node,'count',1)
            assert actual_count==count
        def to_be_visible(self):assert not isinstance(self.node,Caption) or invalid!='hidden-caption'
        def to_be_enabled(self):assert not isinstance(self.node,Caption) or invalid!='disabled-caption'
        def to_have_value(self,value):
            events.append(('native-value',self.node.input_value()));assert self.node.input_value()==value

    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    monkeypatch.setattr(qa,'receipt',read_receipt)
    monkeypatch.setattr(qa,'select_native_option',select)
    # Keep the regression connected to the actual call site, including the fill.
    body=next(node for node in ast.parse(inspect.getsource(qa.exercise)).body[0].body if isinstance(node,ast.Try)).body
    start=next(i for i,node in enumerate(body) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='manager' for t in node.targets))
    end=next(i for i,node in enumerate(body) if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call)
             and isinstance(node.value.func,ast.Attribute) and node.value.func.attr=='fill'
             and any(isinstance(arg,ast.Constant) and arg.value=='Synthetic pending old-source caption' for arg in node.value.args))
    namespace={'page':page,'prefix':prefix,'old':old,'keyboard':keyboard,'receipt':read_receipt,
               'select':lambda control,label:select(page,control,label,keyboard=keyboard),
               'select_source_caption':getattr(qa,'select_source_caption',None)}
    return lambda:exec(compile(ast.Module(body=body[start:end+1],type_ignores=[]),qa.__file__,'exec'),namespace),events


@pytest.mark.parametrize('keyboard',[False,True])
@pytest.mark.parametrize('initial,sequence',[('old',3),('target',4)])
def test_caption_fill_requires_exact_native_owner_and_current_receipt(monkeypatch,keyboard,initial,sequence):
    run,events=caption_boundary(monkeypatch,keyboard=keyboard,initial=initial,sequence=sequence);run()
    assert events[-1]==('fill','old','Synthetic pending old-source caption')
    assert events.count(('select',keyboard))==1
    assert ('native-value','old.pdf') in events
    assert ('fresh-receipt',3) in events if initial=='target' else not any(e[0]=='fresh-receipt' for e in events)
    assert ('receipt',sequence,'old') in events


@pytest.mark.parametrize('keyboard',[False,True])
def test_stale_old_receipt_never_authorizes_caption_fill_on_native_target(monkeypatch,keyboard):
    # The historical financial failure: the old ACK is still valid-looking,
    # but Enter has selected target and the visible caption belongs to target.
    run,events=caption_boundary(monkeypatch,keyboard=keyboard,actual='target',sequence=3)
    with pytest.raises(AssertionError):run()
    assert not any(e[0]=='fill' for e in events)
    assert events.count(('select',keyboard))==1


def test_changed_native_selection_requires_new_receipt_before_caption_fill(monkeypatch):
    run,events=caption_boundary(monkeypatch,initial='target',sequence=3)
    with pytest.raises(AssertionError,match='Stale source-selection receipt'):run()
    assert not any(e[0]=='fill' for e in events)
    assert events.count(('select',True))==1


def test_current_receipt_with_wrong_source_never_authorizes_caption_fill(monkeypatch):
    run,events=caption_boundary(monkeypatch,receipt_owner='target')
    with pytest.raises(AssertionError,match='another source'):run()
    assert not any(e[0]=='fill' for e in events)


@pytest.mark.parametrize('invalid',['missing-owner','duplicate-owner','wrong-report','wrong-page','hidden-caption','disabled-caption','stale-body'])
def test_caption_owner_negative_controls_refuse_before_typing(monkeypatch,invalid):
    run,events=caption_boundary(monkeypatch,invalid=invalid)
    with pytest.raises(AssertionError):run()
    assert not any(e[0]=='fill' for e in events)
    assert events.count(('select',True))==1


def test_caption_ack_adds_no_retry_timeout_or_hidden_input_shortcut():
    source=inspect.getsource(qa.select_source_caption)
    tree=ast.parse(source)
    assert not any(isinstance(node,(ast.For,ast.While)) for node in ast.walk(tree))
    assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                   and node.func.attr in {'fill','click','evaluate','evaluate_all','wait_for_function','wait_for_timeout'} for node in ast.walk(tree))
    assert 'timeout=' not in source and 'force=' not in source
    assert len(qa.required_cases())==16


@pytest.mark.parametrize('initial,receipt_initial',[('target','old'),('old','target')])
def test_disagreeing_preselection_native_or_receipt_owner_requires_fresh_ack(monkeypatch,initial,receipt_initial):
    run,events=caption_boundary(monkeypatch,initial=initial,receipt_initial=receipt_initial,sequence=3)
    with pytest.raises(AssertionError,match='Stale source-selection receipt'):run()
    assert not any(e[0]=='fill' for e in events)
    assert events.count(('select',True))==1
