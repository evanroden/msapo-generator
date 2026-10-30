"""Late native owner contracts: offline protocol replay, not browser geometry."""
import ast
from copy import deepcopy
from dataclasses import replace
import inspect
import json
import sys
from types import SimpleNamespace

import pytest

from scripts import qa_warning_routes as qa


def exercise_nodes(start,end):
    nodes=next(n for n in ast.walk(ast.parse(inspect.getsource(qa.exercise)))
               if isinstance(n,ast.Try)).body
    # Nested scenario branches are still original driver statements.
    all_nodes=[n for n in ast.walk(ast.Module(body=nodes,type_ignores=[]))
               if isinstance(n,ast.stmt)]
    first=next(n for n in all_nodes if start(n))
    stop=next(n for n in all_nodes if end(n))
    lines=inspect.getsource(qa.exercise).splitlines()
    import textwrap
    return ast.parse(textwrap.dedent('\n'.join(lines[first.lineno-1:stop.lineno-1]))).body


def run_nodes(nodes,namespace):
    exec(compile(ast.Module(body=nodes,type_ignores=[]),qa.__file__,'exec'),namespace)


class Native:
    def __init__(self,kind,count=1,**attrs):self.kind=kind;self.count=count;self.attrs=attrs


class Expect:
    def __init__(self,node):self.node=node
    def to_have_count(self,count):assert self.node.count==count,(self.node.kind,self.node.count,count)
    def to_be_visible(self):assert self.node.attrs.get('visible',True)
    def to_have_attribute(self,key,value):assert self.node.attrs[key]==value
    def not_to_be_checked(self):assert not self.node.attrs.get('checked',False)


@pytest.fixture(autouse=True)
def native_expect(monkeypatch):
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))


def disclosure(*,label='Help write this summary',opened=False,invalid=None):
    events=[]
    details=Native('details',0 if invalid=='missing-details' else 2 if invalid=='duplicate-details' else 1)
    summary=Native('own summary',0 if invalid=='missing-summary' else 1)
    owner=Native('expander',0 if invalid=='missing-owner' else 2 if invalid=='duplicate-owner' else 1)
    details.attrs['open']='' if opened else None
    details.evaluate=lambda script: details.attrs['open']==''
    details.locator=lambda selector: summary if selector==':scope > summary' else (_ for _ in ()).throw(AssertionError(selector))
    summary.get_by_text=lambda text,exact: Native('own label',int(exact and text==label and invalid!='wrong-label'))
    def locate(selector):
        if selector==':scope > details':return details
        if selector=='summary':return Native('all descendant summaries',4)
        raise AssertionError(selector)
    owner.locator=locate
    owner.evaluate=lambda script: details.attrs['open']==''
    def activate(node):
        Expect(node).to_have_count(1);assert node is summary
        events.append('native own summary');details.attrs['open']=''
    return owner,activate,events


def ai_open(owner,activate):
    page=SimpleNamespace(get_by_test_id=lambda name:SimpleNamespace(filter=lambda **kwargs:owner),
                         locator=lambda selector:SimpleNamespace(get_by_text=lambda *a,**kw:None))
    nodes=exercise_nodes(lambda n:isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='drafting',
                         lambda n:isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='files' and 'drafting' in ast.unparse(n.value))
    run_nodes(nodes,{'page':page,'activate':activate,'open_native_expander':getattr(qa,'open_native_expander',None)})


def test_actual_ai_callsite_opens_one_own_summary_despite_three_nested_summaries():
    owner,activate,events=disclosure();ai_open(owner,activate)
    assert events==['native own summary']


def test_already_open_help_needs_no_extra_gesture():
    owner,activate,events=disclosure(opened=True);ai_open(owner,activate);assert events==[]


@pytest.mark.parametrize('invalid',['missing-owner','duplicate-owner','missing-details','duplicate-details','missing-summary','wrong-label'])
def test_help_missing_duplicate_or_wrong_direct_owner_never_activates(invalid):
    owner,activate,events=disclosure(invalid=invalid)
    with pytest.raises(AssertionError):ai_open(owner,activate)
    assert events==[]


def save_boundary(*,opened=False,invalid=None):
    prefix='report_guided_exact';owner,open_summary,events=disclosure(label='Shared report history',opened=opened,invalid=invalid)
    history=Native('keyed history',0 if invalid=='foreign-history' else 1)
    history.locator=lambda selector:owner if selector==':scope > [data-testid="stExpander"]' else None
    def button(role,**kw):
        assert role=='button' and kw=={'name':'Save shared version','exact':True}
        return Native('owned save',int(owner.evaluate('node=>node.open'))*(2 if invalid=='duplicate-save' else 1))
    history.get_by_role=button
    page=SimpleNamespace(locator=lambda selector:history if selector=='.st-key-'+prefix+'_history_open' else Native('foreign',0),
                         get_by_role=button)
    def commit(node):
        Expect(node).to_have_count(1)
        if node.kind=='own summary':open_summary(node);events.append('settled open ACK');return {'sequence':2}
        assert node.kind=='owned save';events.append('native owned save');return {'shared':{'fingerprint':'saved'}}
    nodes=[next(n for n in ast.walk(ast.parse(inspect.getsource(qa.exercise))) if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='saved')]
    ns={'page':page,'prefix':prefix,'commit':commit,'save_shared_version':getattr(qa,'save_shared_version',None)}
    return lambda:run_nodes(nodes,ns),events,ns


def test_actual_save_callsite_opens_keyed_history_then_ack_then_exact_save():
    run,events,ns=save_boundary();run()
    assert events==['native own summary','settled open ACK','native owned save']
    assert ns['saved']['shared']['fingerprint']=='saved'


def test_already_open_history_saves_without_toggling_it_closed():
    run,events,_=save_boundary(opened=True);run();assert events==['native owned save']


@pytest.mark.parametrize('invalid',['foreign-history','missing-owner','duplicate-owner','wrong-label','duplicate-save'])
def test_invalid_history_or_save_owner_does_not_save(invalid):
    run,events,_=save_boundary(invalid=invalid)
    with pytest.raises(AssertionError):run()
    assert 'native owned save' not in events


@pytest.fixture(scope='module')
def shared_states(tmp_path_factory):
    from app import monthly_report_testing as testing,monthly_report_picture_batch_ui as batch
    from app.monthly_report_content_policy import page_fingerprint
    from scripts.workspace_warning_routes import prepare_scenario,_snapshot
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('EPC_DATA_DIR',str(tmp_path_factory.mktemp('warning-picture-group')))
        with testing.isolated('c'*32):
            draft=prepare_scenario('shared');source=draft.sources[1]
            source=replace(source,client_page_reviews=((1,page_fingerprint(source,1)),))
            draft=replace(draft,sources=(draft.sources[0],source))
            draft,entries,identity=batch._manifest(draft,'exact-review')
            chosen,images,fallback=batch._choose(draft,{},entries,())
            assert [(e[0],e[1]) for e in chosen]==[('improvements',0),('vendor_reports',0)]
            assert len(images)==2 and not fallback and chosen[0][2]!=chosen[1][2]
            approved=batch._apply(draft,{},'exact-review',{'identity':identity,'entries':chosen,'left':()})
            def state(value):
                snapshot=json.loads(json.dumps(_snapshot(value)))
                return {'scenario':'shared','working':snapshot,'durable':deepcopy(snapshot),
                        'originals':{s.id:s.sha256 for s in value.sources}}
            return state(draft),state(approved)


def picture_boundary(before,after,*,invalid=None):
    source=before['working']['sources'][1];prefix='report_guided_exact';events=[]
    progress=Native('progress',**{'data-section':'report_review'})
    owner=Native('owned picture component',0 if invalid=='foreign-owner' else 2 if invalid=='duplicate-owner' else 1)
    form=Native('picture form');figures=Native('figures',3 if invalid=='extra-picture' else 2)
    pictures=Native('images',2)
    def figure(title):
        number=int(title[0]);caption=qa.CAPTIONS[number-1]
        f=Native('figure',0 if invalid=='wrong-title' else 1)
        f.get_by_text=lambda context,exact: Native('context',int(exact and context==' · '.join((caption,source['filename'],source['facility'],source['service_date'])) and invalid!='wrong-caption'))
        def role(role,**kw):
            if role=='img':
                assert kw=={'name':title,'exact':True};image=Native('picture',1,visible=invalid!='hidden-picture')
                image.evaluate=lambda script: invalid!='undecoded'
                image.get_attribute=lambda name:'/media/exact.png' if invalid!='other-image' or number==1 else '/media/other.png'
                return image
            assert role=='checkbox' and kw=={'name':'Leave '+title+' for correction','exact':True}
            return Native('opt out',checked=invalid=='left-for-correction')
        f.get_by_role=role;return f
    figures.filter=lambda **kw:figure(kw['has'])
    form.locator=lambda selector:figures if selector=='figure' else pictures if selector=='img' else None
    def confirm(role,**kw):
        assert role=='button'
        return Native('confirm',1 if kw=={'name':'Confirm these 2 pictures are ready (except those left for correction)','exact':True} else 0)
    form.get_by_role=confirm
    owner.locator=lambda selector:form if selector=='.picture-review' else Native('stale ancestors',int(invalid=='stale-owner'))
    def locate(selector):
        if selector=='.epc-section-progress':return progress
        if selector=='[class*="st-key-'+prefix+'_picture_component_"]':return owner
        # Old per-section singular action cannot be fulfilled by central group.
        return SimpleNamespace(get_by_role=confirm,locator=lambda selector:None)
    page=SimpleNamespace(locator=locate,get_by_role=lambda role,**kw:kw['name'])
    def commit(node):
        Expect(node).to_have_count(1);events.append('explicit group consent');return deepcopy(after)
    return page,prefix,source,commit,events


def test_actual_shared_callsite_reviews_both_occurrences_in_one_current_group(shared_states):
    before,after=shared_states;page,prefix,source,commit,events=picture_boundary(before,after)
    # Run the real statements AFTER Include page, not a test-only alternate flow.
    tree=ast.parse(inspect.getsource(qa.exercise))
    branch=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="scenario == 'shared'")
    body=branch.body
    include=next(i for i,n in enumerate(body) if 'commit(manager.get_by_role' in ast.unparse(n))
    end=next(i for i,n in enumerate(body) if isinstance(n,ast.For) and 'zip' in ast.unparse(n.iter))
    ns={'page':page,'prefix':prefix,'target':source,'keyboard':False,'expect':Expect,
        'receipt':lambda page:deepcopy(before),'commit':commit,
        'navigate_sections':lambda page,section,**kw:events.append(('navigate',section)),
        'confirm_shared_pictures':getattr(qa,'confirm_shared_pictures',None)}
    run_nodes(body[include+1:end],ns)
    assert events==[('navigate','report_review'),'explicit group consent']
    assert ns['state']==after


@pytest.mark.parametrize('invalid',['foreign-owner','duplicate-owner','extra-picture','wrong-title','wrong-caption','hidden-picture','undecoded','other-image','left-for-correction','stale-owner'])
def test_wrong_hidden_stale_or_unreviewed_picture_display_never_confirms(shared_states,invalid):
    before,after=shared_states;page,prefix,source,commit,events=picture_boundary(before,after,invalid=invalid)
    with pytest.raises(AssertionError):qa.confirm_shared_pictures(page,prefix,source,deepcopy(before),commit)
    assert events==[]


@pytest.mark.parametrize('bad',['wrong-source','wrong-page','wrong-caption','extra-occurrence','missing-review','cross-block-review','changed-occurrence'])
def test_each_destination_occurrence_and_source_page_receipt_is_independent(shared_states,bad):
    before,after=deepcopy(shared_states);source=before['working']['sources'][1]
    expected=qa.shared_picture_occurrences(before,source,reviewed=False)
    block=after['working']['blocks']['vendor_reports']
    if bad=='wrong-source':block['asset_instances'][0]['references'][0]='other:1:'+'f'*64
    elif bad=='wrong-page':block['asset_instances'][0]['references'][0]=source['id']+':2:'+'f'*64
    elif bad=='wrong-caption':block['asset_captions']=[qa.CAPTIONS[0]]
    elif bad=='extra-occurrence':block['asset_instances']*=2
    elif bad=='missing-review':block['client_asset_reviews']=[]
    elif bad=='cross-block-review':block['client_asset_reviews']=after['working']['blocks']['improvements']['client_asset_reviews']
    else:block['asset_instances'][0]['key']='changed-occurrence'
    with pytest.raises(AssertionError):assert qa.shared_picture_occurrences(after,source,reviewed=True)==expected


def test_all_sixteen_and_strict_original_navigation_saved_reopen_outputs_remain():
    text=inspect.getsource(qa.exercise)
    assert len(qa.required_cases())==16
    for fragment in ("expect(visible).to_be_in_viewport(ratio=1)","expect(back).to_have_count(1)",
                     "assert reopened['working']==saved['working']", "verify_outputs(output,scenario,final",
                     "assert not [c for c in corrected['working']['checks'] if c['blocking']]",
                     "saved['shared']['fingerprint']==saved['working']['fingerprint']"):
        assert fragment in text
