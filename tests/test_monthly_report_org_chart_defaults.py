from dataclasses import replace
from io import BytesIO
import pytest
from PIL import Image
from app import monthly_report_org_chart_defaults as charts, monthly_report_library as library
from app.monthly_report_asset_review import approve_all_assets
from app.monthly_report_model import Facility, ReportPeriod, ResolvedBlock, synthetic_profiles, OrgChartNode
from app.monthly_report_guided import _initial_draft
from app.monthly_report_setup import new_month_draft

@pytest.fixture
def scopes(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    base=synthetic_profiles()[0]
    a1=replace(base,contract='Synthetic A',key='a1',facilities=(Facility('a1','A1'),))
    a2=replace(a1,key='a2',facilities=(Facility('a2','A2'),))
    b1=replace(a1,contract='Synthetic B',key='b1')
    multi=replace(a1,key='multi',facilities=(*a1.facilities,*a2.facilities),scope_type='multi_site')
    for p in (a1,a2,b1,multi):
        library.save_profile(p,expected_revision=0,actor='Synthetic Tester',confirmed=True)
    return a1,a2,b1,multi

def fresh(p):
    return replace(_initial_draft(library.load_profile(p.contract,p.key),ReportPeriod(2026,10),'Synthetic Tester'),synthetic=False)

def chart(d): return next(b for b in d.blocks if b.key=='org_chart')
def with_chart(d,b): return replace(d,blocks=tuple(b if v.key=='org_chart' else v for v in d.blocks))
def picture(color):
    out=BytesIO();Image.new('RGB',(12,12),color).save(out,'PNG');raw=out.getvalue();ref=library.asset_reference(raw,'png')
    return approve_all_assets(ResolvedBlock('org_chart','This month',asset_hashes=(ref,))),{ref:raw}
def publish(p,color='red',scope='contract',revision=0):
    b,a=picture(color);d=with_chart(fresh(p),b)
    charts.save_default(d,b,a,scope=scope,expected_revision=revision,expected_fingerprint=b.fingerprint,confirmed=True)
    return d,b,a

def test_contract_site_precedence_and_no_cross_contract(scopes):
    a1,a2,b1,multi=scopes
    _,red,_=publish(a1)
    _,blue,_=publish(a1,'blue','site',1)
    _,green,_=publish(a2,'green','site',2)
    for p,expected in ((a1,blue),(a2,green),(multi,red)):
        assets={};resolved=charts.apply_defaults(fresh(p),assets)
        assert chart(resolved).asset_hashes==expected.asset_hashes
        assert set(assets)==set(expected.asset_hashes)
    assert charts.apply_defaults(fresh(b1),{})==fresh(b1)
    assert charts.load_defaults(b1.contract).revision==0
    with pytest.raises(library.LibraryError):publish(multi,'blue','site',3)

@pytest.mark.parametrize('kind',['omit','manual','excluded'])
def test_populated_omitted_and_excluded_do_not_hydrate(scopes,kind):
    a1,_,_,_=scopes;publish(a1);d=fresh(a1)
    if kind=='omit':d=with_chart(d,replace(chart(d),source='Omit'))
    if kind=='manual':d=with_chart(d,replace(chart(d),text='Only this report'))
    if kind=='excluded':d=replace(d,sections=tuple(replace(s,included=False) if s.key=='organization' else s for s in d.sections))
    assert charts.apply_defaults(d,{})==d


def test_explicit_refresh_preserves_notes_and_rollover_snapshot(scopes):
    a1,_,_,_=scopes
    d,red,assets=publish(a1)
    library.save_snapshot(d,expected_revision=0,assets=tuple(assets.items()))
    path=library._profile_path(a1.contract,a1.key,snapshots=True)/'2026-10.json';before=path.read_bytes()
    _,blue,_=publish(a1,'blue',revision=1)
    carried=new_month_draft(d,ReportPeriod(2026,11))
    assert chart(charts.apply_defaults(carried,{})).asset_hashes==red.asset_hashes
    block=replace(chart(carried),text='Report-specific notes');carried=with_chart(carried,block)
    refreshed=charts.use_default(carried,block,{},expected_revision=2,expected_fingerprint=block.fingerprint)
    assert refreshed.asset_hashes==blue.asset_hashes and refreshed.text==block.text
    assert path.read_bytes()==before
    assert chart(library.load_snapshot(a1.contract,a1.key,d.period).draft).asset_hashes==red.asset_hashes
    assert charts.read_asset(a1.contract,red.asset_hashes[0])==assets[red.asset_hashes[0]]

@pytest.mark.parametrize('change',['unconfirmed','stale','fingerprint','omit','unreviewed','synthetic','source'])
def test_publish_refuses_unapproved_changed_or_stale_actions(scopes,change):
    a1,_,_,_=scopes;d,b,a=publish(a1);revision=1;fp=b.fingerprint;confirmed=True
    if change=='unconfirmed':confirmed=False
    if change=='stale':revision=0
    if change=='fingerprint':fp='old'
    if change=='omit':b=replace(b,source='Omit')
    if change=='unreviewed':b=replace(b,client_asset_reviews=(),client_reviewed_fingerprint='')
    if change=='synthetic':d=replace(d,synthetic=True)
    if change=='source':b=approve_all_assets(replace(b,references=('missing:1:'+('a'*64),),asset_provenance=(),asset_instances=()))
    if change in ('omit','unreviewed','source'):d=with_chart(d,b);fp=b.fingerprint
    before=(charts._path(a1.contract)/'manifest.json').read_bytes()
    with pytest.raises((ValueError,OSError)):
        charts.save_default(d,b,a,scope='contract',expected_revision=revision,expected_fingerprint=fp,confirmed=confirmed)
    assert (charts._path(a1.contract)/'manifest.json').read_bytes()==before


def test_read_never_adopts_legacy_profile_chart(scopes):
    a1,a2,_,_=scopes;b,a=picture('red')
    library.replace_block(a1.contract,a1.key,'org_chart',b,label='Local',expected_revision=1,actor='Synthetic Tester',confirmed=True,assets=tuple(a.items()))
    assert charts.load_defaults(a1.contract).revision==0
    assert charts.apply_defaults(fresh(a2),{})==fresh(a2)
    assert not charts._path(a1.contract).exists()


def test_node_chart_and_asset_corruption(scopes):
    a1,a2,_,_=scopes
    b=ResolvedBlock('org_chart','This month',org_nodes=(OrgChartNode('lead','Synthetic Lead','Lead'),))
    d=with_chart(fresh(a1),b)
    charts.save_default(d,b,{},scope='contract',expected_revision=0,expected_fingerprint=b.fingerprint,confirmed=True)
    assert chart(charts.apply_defaults(fresh(a2),{})).org_nodes==b.org_nodes
    _,b,_=publish(a1,revision=1)
    path=charts._path(a1.contract)/'assets'/b.asset_hashes[0]
    replacement=path.with_suffix('.replacement');replacement.write_bytes(b'corrupt');replacement.replace(path)
    with pytest.raises(library.LibraryError):charts.apply_defaults(fresh(a2),{})

@pytest.mark.parametrize('nodes',[
    (OrgChartNode('one','One',reports_to='two'),OrgChartNode('two','Two',reports_to='one')),
    (OrgChartNode('one','One',reports_to='missing'),),
    (OrgChartNode('one','One'),OrgChartNode('one','Duplicate')),
])
def test_invalid_graph_cannot_be_published(scopes,nodes):
    a1,_,_,_=scopes
    b=ResolvedBlock('org_chart','This month',org_nodes=nodes);d=with_chart(fresh(a1),b)
    with pytest.raises(library.LibraryError):
        charts.save_default(d,b,{},scope='contract',expected_revision=0,expected_fingerprint=b.fingerprint,confirmed=True)
    assert charts.load_defaults(a1.contract).revision==0


def test_fresh_profile_chart_does_not_shadow_explicit_contract_default(scopes):
    a1,a2,_,_=scopes
    local,local_assets=picture('green')
    state=library.replace_block(a2.contract,a2.key,'org_chart',local,label='Legacy local chart',expected_revision=1,actor='Synthetic Tester',confirmed=True,assets=tuple(local_assets.items()))
    _,default,_=publish(a1,'red')
    assets={}
    draft=_initial_draft(state,ReportPeriod(2026,11),'Synthetic Tester',assets=assets)
    assert chart(draft).asset_hashes==default.asset_hashes
    assert library.load_profile(a2.contract,a2.key).block('org_chart')==local
    assert charts.load_defaults(a2.contract).revision==1

@pytest.mark.parametrize('mode',['site_override','no_default','omitted','imported_copy','carried_copy'])
def test_legacy_profile_seed_precedence_preserves_explicit_report_choices(scopes,mode):
    a1,a2,_,_=scopes;local,local_assets=picture('green')
    if mode=='omitted':local=replace(local,source='Omit')
    state=library.replace_block(a2.contract,a2.key,'org_chart',local,label='Local',expected_revision=1,actor='Synthetic Tester',confirmed=True,assets=tuple(local_assets.items()))
    expected=local
    if mode!='no_default':publish(a1,'red')
    if mode=='site_override':_,expected,_=publish(a2,'blue',scope='site',revision=1)
    assets={}
    if mode in ('imported_copy','carried_copy'):
        d=_initial_draft(state,ReportPeriod(2026,10),'Synthetic Tester')
        if mode=='carried_copy':d=new_month_draft(d,ReportPeriod(2026,11))
        d=charts.apply_defaults(d,assets)
    else:
        d=_initial_draft(state,ReportPeriod(2026,11),'Synthetic Tester',assets=assets)
    assert chart(d).asset_hashes==expected.asset_hashes
    if mode=='omitted':assert chart(d).source=='Omit'
    assert library.load_profile(a2.contract,a2.key).block('org_chart')==local
