"""Offline native/receipt sequence doubles, never browser acceptance."""
import ast
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import qa_reviewed_work_orders as qa


def predicate_matches(predicate, value):
    """Exercise the actual read-only receipt predicate outside any browser."""
    result = subprocess.run(['node', '-e',
        "const [p,v]=JSON.parse(require('fs').readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(Function('v','return ('+p+')(v)')(v)));"],
        input=json.dumps([predicate, value]), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def sequence(monkeypatch, *, initially_settled=False, initially_open=False, invalid=None):
    events=[]
    native={'running':not initially_settled, 'epoch':1 if initially_settled else 0, 'open':initially_open}
    final={'working':{'sources':[{'id':sha256(qa.CSV).hexdigest()}], 'reviews':0}, 'originals_unchanged':True}
    if invalid=='wrong-owner':final['working']['sources'][0]['id']='other-source'
    if invalid=='missing-owner':final['working']['sources']=[]
    if invalid=='duplicate-owner':final['working']['sources']*=2
    if invalid=='changed-original':final['originals_unchanged']=False
    if invalid=='preapproved-review':final['working']['reviews']=1

    class Facility:
        def scroll_into_view_if_needed(self):
            events.append(('scroll',native['epoch']));assert native['open']
        def press(self,key):
            events.append(('press',key,native['epoch']))
            assert key=='ArrowDown' and native['open'], 'Source facility hidden after upload remount'

    facility=Facility()
    class Summary:
        def click(self):
            events.append(('open',native['epoch']));native['open']=True
    class Panel:
        def filter(self,*,has):assert has is facility;return self
        def evaluate(self,expression):
            assert expression=="n=>(n.matches('details')?n:n.querySelector('details')).open"
            events.append(('inspect-open',native['epoch']));return native['open']
        def locator(self,selector):assert selector=='summary';return Summary()
    panel=Panel()
    class Upload:
        def set_input_files(self,payload):
            assert payload=={'name':'synthetic-cmms.csv','mimeType':'text/csv','buffer':qa.CSV}
            events.append(('upload',))
    class Option:
        def click(self):
            assert native['open'];events.append(('option-click',native['epoch']))
    start=object()
    class Page:
        def locator(self,selector):assert selector=='input[type="file"]';return Upload()
        def get_by_role(self,role,**kwargs):
            assert kwargs['exact'] is True
            if role=='button':assert kwargs['name']=='Review and correct imported rows';return start
            if role=='combobox':assert kwargs['name']=='Source facility';return facility
            assert role=='option' and kwargs['name']=='Demonstration North Facility';return Option()
        def get_by_test_id(self,testid):assert testid=='stExpander';return panel
    page=Page()

    def settled(page_arg,predicate):
        assert page_arg is page
        events.append(('settle',predicate,native['epoch']))
        # The original trace's streaming upload replaces the opened initial
        # form when it settles. No additional user gesture occurs here.
        if native['running']:
            native.update(running=False,epoch=1,open=False)
        assert predicate_matches(predicate,final), 'Upload receipt did not acknowledge exact source'
        return deepcopy(final)

    class Expect:
        def __init__(self,node):self.node=node
        def to_have_count(self,count):
            assert self.node is facility and count==1
            events.append(('facility-count',native['epoch']))
        def to_be_visible(self,**kwargs):
            if self.node is start:assert kwargs=={'timeout':25000};events.append(('start-visible',native['epoch']))
            else:
                assert self.node is facility and native['open']
                events.append(('facility-visible',native['epoch']))
        def to_be_enabled(self):assert self.node is facility

    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    monkeypatch.setattr(qa,'settled',settled)
    body=next(n for n in ast.parse(inspect.getsource(qa.exercise)).body[0].body if isinstance(n,ast.Try)).body
    begin=next(i for i,n in enumerate(body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
               and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='set_input_files')
    end=next(i for i,n in enumerate(body) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
             and isinstance(n.value.func,ast.Name) and n.value.func.id=='select')
    namespace={'page':page,'CSV':qa.CSV,'expect':Expect,'select':qa.select,
               'uploaded_source_ready':getattr(qa,'uploaded_source_ready',None)}
    return lambda:exec(compile(ast.Module(body=body[begin:end+1],type_ignores=[]),qa.__file__,'exec'),namespace),events


def test_streamed_upload_is_acknowledged_before_first_details_gesture(monkeypatch):
    run,events=sequence(monkeypatch);run()
    assert events[-1]==('option-click',1)
    assert [e for e in events if e[0]=='open']==[('open',1)]
    assert [e for e in events if e[0]=='press']==[('press','ArrowDown',1)]
    exact=next(i for i,e in enumerate(events) if e[0]=='settle' and e[1]!='v=>true')
    assert exact < next(i for i,e in enumerate(events) if e[0]=='facility-count')
    assert exact < next(i for i,e in enumerate(events) if e[0]=='inspect-open')


@pytest.mark.parametrize('initially_open',[False,True])
def test_already_settled_webkit_path_needs_no_duplicate_open(monkeypatch,initially_open):
    run,events=sequence(monkeypatch,initially_settled=True,initially_open=initially_open);run()
    assert [e for e in events if e[0]=='open']==([] if initially_open else [('open',1)])
    assert events[-1]==('option-click',1)


@pytest.mark.parametrize('invalid',['wrong-owner','missing-owner','duplicate-owner','changed-original','preapproved-review'])
def test_invalid_upload_ack_refuses_before_inspection_or_scope_edit(monkeypatch,invalid):
    run,events=sequence(monkeypatch,initially_settled=True,invalid=invalid)
    with pytest.raises(AssertionError,match='exact source'):run()
    assert not any(e[0] in {'facility-count','inspect-open','open','press','option-click'} for e in events)


def test_ack_revalidates_the_returned_receipt_not_only_wait_predicate(monkeypatch):
    monkeypatch.setattr(qa,'settled',lambda page,predicate:{'working':{'sources':[{'id':'foreign'}],'reviews':0},'originals_unchanged':True})
    with pytest.raises(AssertionError):qa.uploaded_source_ready(object())


def test_exact_owner_is_the_original_csv_digest_and_no_new_timing_or_input_shortcut():
    assert sha256(qa.CSV).hexdigest()=='0ab8edb2703a5499ce91c7e1ab213e557f3002a1f37e4028b3aa48c37a45b277'
    source=inspect.getsource(qa.uploaded_source_ready)
    assert 'timeout' not in source and 'sleep' not in source and 'force' not in source
    assert not any(isinstance(n,(ast.For,ast.While)) for n in ast.walk(ast.parse(source)))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in
                   {'click','press','evaluate','fill','check','dispatch_event','wait_for_function'} for n in ast.walk(ast.parse(source)))
    driver=Path(qa.__file__).read_text()
    assert 'os.environ.get("REVIEWED_ROW_BROWSERS", "chromium,webkit")' in driver
