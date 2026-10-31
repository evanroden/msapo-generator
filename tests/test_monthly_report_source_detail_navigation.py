"""Date/site warning receipts cannot be rebound to another source revision."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from app import monthly_report_source_detail_navigation as ui
from app import monthly_report_guided as guided
from app.monthly_report_correction_targets import source_target
from app.monthly_report_checks import preflight
from test_monthly_report_ai_correction_targets import fixture

P='details'


def prepared(monkeypatch):
    draft=fixture();source=replace(draft.sources[0],facility='',service_date='',classification='Vendor service')
    draft=replace(draft,sources=(source,));content=SimpleNamespace(source=source)
    target=source_target(draft,source)
    state={P+'_draft':draft,P+'_evidence':(content,),P+'_evidence_selected':'old',P+'_source_active_selected':'old'}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    return state,draft,content,target


@pytest.mark.parametrize('code',['source_facility','source_date_unknown','source_period'])
def test_exact_preflight_metadata_and_native_selection_only_after_commit(monkeypatch,code):
    state,draft,content,target=prepared(monkeypatch)
    if code=='source_period':
        content.source=replace(content.source,service_date='2026-01-01');draft=replace(draft,sources=(content.source,))
        state[P+'_draft']=draft;target=source_target(draft,content.source)
    check=next(c for c in preflight(draft) if c.code==code)
    assert check.targets==(target,)
    ui.queue_navigation(P,target,code,'scope')
    assert state[P+'_evidence_selected']=='old'
    ui.finish_navigation(P,draft,'scope')
    assert state[P+'_evidence_selected']=='old'
    ui.consume_navigation(P,draft,'scope')
    assert state[P+'_evidence_selected']==content.source.id and state[P+'_source_active_selected']==content.source.id
    assert state[P+'_draft']==draft and state[P+'_evidence']==(content,)
    assert not any(k.endswith(('_source_details_site','_source_details_date')) for k in state)
    snapshot=dict(state);ui.consume_navigation(P,draft,'scope');ui.finish_navigation(P,draft,'scope')
    assert state==snapshot


@pytest.mark.parametrize('phase',['queued','ready'])
@pytest.mark.parametrize('change',['scope','hash','site','date','caption_no_journal','missing','duplicate','unavailable','duplicate_original','report'])
def test_delayed_stale_detail_destination_never_mutates_selected_owner(monkeypatch,phase,change):
    state,draft,content,target=prepared(monkeypatch)
    ui.queue_navigation(P,target,'source_facility','scope')
    if phase=='ready':ui.finish_navigation(P,draft,'scope')
    scope='scope'
    if change=='scope':scope='new'
    elif change=='missing':draft=replace(draft,sources=())
    elif change=='duplicate':draft=replace(draft,sources=(*draft.sources,*draft.sources))
    elif change=='unavailable':state[P+'_evidence']=()
    elif change=='duplicate_original':state[P+'_evidence']=(content,content)
    elif change=='report':draft=replace(draft,profile=replace(draft.profile,key='other'))
    else:
        updates={'hash':{'sha256':'changed'},'site':{'facility':'Another site'},'date':{'service_date':'2026-09-01'},'caption_no_journal':{'captions':((1,'Changed'),)}}[change]
        content=SimpleNamespace(source=replace(content.source,**updates));draft=replace(draft,sources=(content.source,));state[P+'_evidence']=(content,)
    (ui.finish_navigation if phase=='queued' else ui.consume_navigation)(P,draft,scope)
    assert state[P+'_evidence_selected']=='old' and state[P+'_source_active_selected']=='old'
    assert P+'_source_detail_navigation_open' not in state
    assert 'changed' in state[P+'_source_detail_navigation_notice']


def test_only_journal_proven_caption_change_renews_same_source_identity(monkeypatch):
    state,draft,content,target=prepared(monkeypatch)
    ui.queue_navigation(P,target,'source_date_unknown','scope')
    revised=replace(content.source,captions=((1,'Delivered old native caption'),))
    updated=replace(draft,sources=(revised,));state[P+'_evidence']=(SimpleNamespace(source=revised),)
    state[P+'_source_native_changes']={revised.id:(content.source,revised)}
    ui.finish_navigation(P,updated,'scope');ui.consume_navigation(P,updated,'scope')
    assert state[P+'_source_detail_navigation_open']['target'].source_revision==revised.fingerprint
    assert updated.sources[0].service_date=='' and updated.sources[0].facility==''
