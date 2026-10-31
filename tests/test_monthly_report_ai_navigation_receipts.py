"""Delayed AI warning receipts never become authority for a changed owner."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from app import monthly_report_ai_correction_ui as ui
from app import monthly_report_guided as guided
from app.monthly_report_ai_correction_targets import paragraph_target
from test_monthly_report_ai_correction_targets import fixture

P='ai_receipt'

@pytest.mark.parametrize('phase',['queued','ready'])
@pytest.mark.parametrize('change',['scope','source_bytes','fact','missing','omitted','duplicate_block','duplicate_source','paragraph','reordered'])
def test_stale_receipts_fail_closed_without_source_or_page_mutation(monkeypatch,phase,change):
    draft=fixture(); block=draft.blocks[0]
    second=replace(block.ai_paragraphs[0],text='Different retained paragraph.')
    block=replace(block,ai_paragraphs=(*block.ai_paragraphs,second))
    draft=replace(draft,blocks=(block,))
    state={P+'_draft':draft,P+'_ai_source':'previous-source',P+'_ai_read_pages_previous-source':[2]}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    target=paragraph_target(draft,block,0,'evidence')
    ui.queue_navigation(P,target,'scope')
    assert P+'_ai_correction_pending' in state
    if phase=='ready':ui.finish_navigation(P,draft,'scope')
    scope='scope'
    if change=='scope':scope='new-scope'
    elif change=='missing':draft=replace(draft,blocks=())
    elif change=='omitted':draft=replace(draft,blocks=(replace(block,source='Omit'),))
    elif change=='duplicate_block':draft=replace(draft,blocks=(block,block))
    elif change=='duplicate_source':draft=replace(draft,sources=(*draft.sources,*draft.sources))
    elif change=='source_bytes':draft=replace(draft,sources=(replace(draft.sources[0],sha256='different'),))
    elif change=='fact':draft=replace(draft,sources=(replace(draft.sources[0],facts=(replace(draft.sources[0].facts[0],quote='Changed'),)),))
    elif change=='paragraph':draft=replace(draft,blocks=(replace(block,ai_paragraphs=(replace(block.ai_paragraphs[0],text='Changed'),second)),))
    elif change=='reordered':draft=replace(draft,blocks=(replace(block,ai_paragraphs=tuple(reversed(block.ai_paragraphs))),))
    unchanged=draft
    (ui.finish_navigation if phase=='queued' else ui.consume_navigation)(P,draft,scope)
    assert P+'_ai_correction_open' not in state
    assert P+'_ai_correction_ready' not in state
    assert state[P+'_ai_source']=='previous-source'
    assert state[P+'_ai_read_pages_previous-source']==[2]
    assert 'changed' in state[P+'_ai_correction_notice']
    assert draft==unchanged


def test_repeated_callbacks_replace_receipt_and_delivery_is_one_shot(monkeypatch):
    draft=fixture();block=draft.blocks[0];target=paragraph_target(draft,block,0,'evidence')
    state={P+'_draft':draft}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    ui.queue_navigation(P,target,'scope');old=state[P+'_ai_correction_pending']['nonce']
    ui.queue_navigation(P,target,'scope')
    assert state[P+'_ai_correction_pending']['nonce']!=old
    ui.finish_navigation(P,draft,'scope');ui.consume_navigation(P,draft,'scope')
    assert P+'_ai_correction_open' in state
    assert P+'_ai_correction_pending' not in state and P+'_ai_correction_ready' not in state
    snapshot=dict(state)
    ui.finish_navigation(P,draft,'scope');ui.consume_navigation(P,draft,'scope')
    assert state==snapshot and state[P+'_draft']==draft


@pytest.mark.parametrize('kind',['absent','duplicate','changed'])
def test_fact_page_requires_exact_available_original_without_reading_selection_change(monkeypatch,kind):
    draft=fixture();source=draft.sources[0]
    source=replace(source,facts=(replace(source.facts[0],date='2026-09-25'),))
    draft=replace(draft,sources=(source,));block=draft.blocks[0]
    target=paragraph_target(draft,block,0,'date',fact_id=source.facts[0].id,source_id=source.id,page=1)
    content=SimpleNamespace(source=source)
    contents=() if kind=='absent' else (content,content) if kind=='duplicate' else (SimpleNamespace(source=replace(source,filename='Changed')),)
    state={P+'_draft':draft,P+'_evidence':contents,P+'_ai_source':'previous',P+'_ai_read_pages_'+source.id:[]}
    monkeypatch.setattr(ui,'st',SimpleNamespace(session_state=state))
    monkeypatch.setattr(guided,'_rich_text_scope',lambda prefix:'scope')
    ui.queue_navigation(P,target,'scope',True);ui.finish_navigation(P,draft,'scope');ui.consume_navigation(P,draft,'scope')
    assert P+'_ai_correction_open' not in state
    assert state[P+'_ai_source']=='previous'
    assert state[P+'_ai_read_pages_'+source.id]==[]
    assert 'unavailable' in state[P+'_ai_correction_notice']
