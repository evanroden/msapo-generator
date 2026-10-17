"""Ordinary section uploads keep external reading behind an exact native action."""
from concurrent.futures import Future
from dataclasses import replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_ai as ai, monthly_report_structured_uploads as structured
from app import monthly_report_upload_ui as ui, receipt_jobs, monthly_report_library as library
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, default_sections, synthetic_profiles

APP = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_upload_ui import render_structured_uploads
from app.monthly_report_ui import _field
draft = st.session_state['test_draft']
blocks = {b.key:b for b in draft.blocks}
sources, additions, specs = render_structured_uploads(draft.profile,draft.period,'section_read',_field,
    st.session_state['destination'],blocks=blocks)
blocks.update(additions)
st.session_state['test_draft'] = replace(draft,blocks=tuple(blocks.values()),sources=sources)
st.session_state['section_read_draft'] = st.session_state['test_draft']
'''


def upload(raw=b'Completed synthetic pump inspection.', name='synthetic-section.txt'):
    stream=BytesIO(raw);stream.name=name
    return stream


def setup(monkeypatch,tmp_path,destination='activity_summary',*,pending=False,cache=None):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(ai,'ANTHROPIC_API_KEY','synthetic-not-a-real-key')
    uploads=[[upload()]]
    monkeypatch.setattr(ui.st,'file_uploader',lambda *a,**kw:uploads[0])
    calls={'start':0,'prepare':0,'reserve':0,'worker':0,'cache':0}
    futures=[]
    monkeypatch.setattr(ai,'cached',lambda *a:cache)
    monkeypatch.setattr(ai,'save_cache',lambda *a:calls.__setitem__('cache',calls['cache']+1))
    monkeypatch.setattr(ai,'reserve_call',lambda *a:calls.__setitem__('reserve',calls['reserve']+1))
    def batches(*a,**kw):
        calls['prepare']+=1
        return [[{'type':'text','text':'invented local request'}]]
    monkeypatch.setattr(structured,'reader_batches',batches)
    def worker(payload):
        calls['worker']+=1
        return {'items':[]}
    monkeypatch.setattr(structured,'read_batches',worker)
    def start(prepare,read):
        calls['start']+=1
        value=read(prepare())
        future=Future()
        if pending:future.set_running_or_notify_cancel()
        else:future.set_result(value)
        futures.append(future)
        return future
    monkeypatch.setattr(receipt_jobs,'start_receipt',start)
    draft=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Synthetic editor',default_sections(),
                      (ResolvedBlock(destination,'This month',text='Kept manual wording.'),),synthetic=True)
    app=AppTest.from_string(APP,default_timeout=15)
    app.session_state['test_draft']=draft
    app.session_state['destination']=destination
    return app,calls,uploads,futures


def read(app):
    return next(b for b in app.button if b.label=='Read selected files')


@pytest.mark.parametrize('destination',['activity_summary','capital_renewal','proposals'])
def test_upload_and_neutral_rerun_keep_native_content_without_any_external_call(monkeypatch,tmp_path,destination):
    app,calls,_,_=setup(monkeypatch,tmp_path,destination)
    app.run();app.run()
    assert not app.exception
    assert calls=={'start':0,'prepare':0,'reserve':0,'worker':0,'cache':0}
    current=app.session_state['test_draft']
    assert ui.sources.source_bytes(current.profile,current.sources[0]) == b'Completed synthetic pump inspection.'
    assert any('external document reader' in x.value and 'Charges may apply' in x.value for x in app.caption)
    read(app).click().run()
    assert not app.exception
    assert calls=={'start':1,'prepare':1,'reserve':1,'worker':1,'cache':1}
    app.run()
    assert calls['start']==1
    assert not any(b.label=='Read selected files' for b in app.button)


@pytest.mark.parametrize('change',['source','profile','month','incarnation','qa_generation','shared_revision'])
def test_held_read_cannot_spend_on_a_changed_source_scope_or_shared_base(monkeypatch,tmp_path,change):
    app,calls,uploads,_=setup(monkeypatch,tmp_path)
    app.run();old=read(app)
    draft=app.session_state['test_draft']
    if change=='source':uploads[0]=[upload(b'Completed another synthetic inspection.')]
    elif change=='profile':app.session_state['test_draft']=replace(draft,profile=replace(draft.profile,title='Another report scope'))
    elif change=='month':app.session_state['test_draft']=replace(draft,period=ReportPeriod(2026,10))
    elif change=='incarnation':app.session_state['section_read_rich_text_epoch']='replacement-incarnation'
    elif change=='qa_generation':app.session_state['_monthly_qa_generation']='replacement-qa-generation'
    else:library.save_snapshot(draft,expected_revision=0,entered_editor='Concurrent editor')
    old.click().run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['worker']==0
    assert any('Nothing was sent' in x.value for x in app.warning)


def test_changed_incarnation_rejects_late_result_before_cache_or_application(monkeypatch,tmp_path):
    app,calls,_,futures=setup(monkeypatch,tmp_path,pending=True)
    app.run();read(app).click().run()
    before=app.session_state['test_draft']
    app.session_state['section_read_rich_text_epoch']='replacement-incarnation'
    app.run()
    futures[0].set_result({'items':[]})
    app.run()
    assert not app.exception
    assert calls['cache']==0 and calls['start']==1
    assert app.session_state['test_draft']==before


def test_valid_completed_read_survives_cache_failure_without_paid_retry(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path)
    def fail_cache(*a):
        calls['cache']+=1
        raise OSError('Synthetic reuse cache write unavailable')
    monkeypatch.setattr(ai,'save_cache',fail_cache)
    app.run();read(app).click().run();app.run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['cache']==1
    assert any('reuse cache' in x.value for x in app.warning)
    assert not any(b.label in ('Read selected files','Retry reading uploaded files') for b in app.button)


def test_malformed_result_is_not_cached_and_requires_explicit_retry(monkeypatch,tmp_path):
    app,calls,_,futures=setup(monkeypatch,tmp_path,pending=True)
    app.run();read(app).click().run()
    before=app.session_state['test_draft']
    futures[0].set_result({'items':'malformed'})
    app.run();app.run()
    assert not app.exception
    assert calls['cache']==0 and calls['start']==1
    assert app.session_state['test_draft']==before
    next(b for b in app.button if b.label=='Retry reading uploaded files').click().run()
    assert not app.exception and calls['start']==2


def test_valid_cache_is_free_without_configured_external_reader(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path,cache={'items':[]})
    monkeypatch.setattr(ai,'ANTHROPIC_API_KEY','')
    app.run();app.run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['worker']==0
    assert not any(b.label=='Read selected files' for b in app.button)
    assert any(key.endswith('_completed_ids') for key in app.session_state.filtered_state)


def test_completed_source_does_not_replay_cached_wording_after_shared_save(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path)
    app.run();read(app).click().run()
    current=app.session_state['test_draft']
    manual=replace(current,blocks=(replace(current.blocks[0],text='A deliberate human replacement.'),))
    app.session_state['test_draft']=manual
    saved=library.save_snapshot(manual,expected_revision=0,entered_editor='Synthetic editor')
    app.session_state['section_read_revision']=saved.revision
    cached_calls=[]
    monkeypatch.setattr(ai,'cached',lambda *a:cached_calls.append(a) or {'items':[]})
    app.run()
    assert not app.exception
    assert app.session_state['test_draft']==manual
    assert cached_calls==[] and calls['start']==1
    assert not any(b.label=='Read selected files' for b in app.button)


def test_reset_rotates_native_uploader_and_does_not_replay_old_selected_file(monkeypatch,tmp_path):
    app,calls,_,futures=setup(monkeypatch,tmp_path,pending=True)
    native_keys=[]
    original=ui.st.file_uploader
    def native_upload(*a,**kw):
        native_keys.append(kw['key'])
        return original(*a,**kw) if not native_keys or kw['key']==native_keys[0] else []
    monkeypatch.setattr(ui.st,'file_uploader',native_upload)
    app.run();read(app).click().run()
    before=app.session_state['test_draft']
    replacement=replace(before,blocks=(ResolvedBlock('activity_summary','This month',text='Replacement wording only.'),))
    app.session_state['test_draft']=replacement
    app.session_state['section_read_draft']=replacement
    app.session_state['section_read_rich_text_epoch']='replacement-incarnation'
    app.run()
    futures[0].set_result({'items':[]})
    app.run()
    assert not app.exception
    assert native_keys[-1]!=native_keys[0]
    assert app.session_state['test_draft']==replacement
    assert calls['start']==1 and calls['cache']==0


def test_saturated_reader_keeps_native_content_and_requires_fresh_explicit_retry(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path)
    monkeypatch.setattr(receipt_jobs,'start_receipt',lambda *a:None)
    app.run();old=read(app);old.click().run()
    assert not app.exception
    assert calls['reserve']==calls['worker']==0
    assert any('Other document readings' in x.value for x in app.warning)
    retry=next(b for b in app.button if b.label=='Retry reading uploaded files')
    assert retry.key != old.key
    before=app.session_state['test_draft']
    old.click().run()
    assert app.session_state['test_draft']==before
    assert calls['reserve']==calls['worker']==0


def test_isolated_test_refuses_matching_queued_read_before_preparation(monkeypatch,tmp_path):
    from app import monthly_report_testing as testing
    app,calls,_,_=setup(monkeypatch,tmp_path)
    app.run();old=read(app)
    monkeypatch.setattr(testing,'scope',lambda:'invented-isolated-test')
    old.click().run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['prepare']==0
    assert not any(b.label=='Read selected files' for b in app.button)


def test_failed_shared_version_read_keeps_native_content_and_sends_nothing(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path)
    app.run();old=read(app)
    monkeypatch.setattr(library,'load_snapshot',lambda *a,**kw:(_ for _ in ()).throw(OSError('Synthetic shared version unavailable')))
    old.click().run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['worker']==0
    assert any('Synthetic shared version unavailable' in x.value for x in app.warning)


@pytest.mark.parametrize('change',['source','clear','profile','month','qa_generation','shared_revision'])
def test_late_result_cannot_validate_or_cache_against_another_target(monkeypatch,tmp_path,change):
    app,calls,uploads,futures=setup(monkeypatch,tmp_path,pending=True)
    app.run();read(app).click().run()
    validations=[]
    original=structured.reader_update
    monkeypatch.setattr(structured,'reader_update',lambda *a,**kw:validations.append(a) or original(*a,**kw))
    current=app.session_state['test_draft']
    if change=='source':uploads[0]=[upload(b'Completed another synthetic inspection.')]
    elif change=='clear':uploads[0]=[]
    elif change=='profile':app.session_state['test_draft']=replace(current,profile=replace(current.profile,title='Different report scope'))
    elif change=='month':app.session_state['test_draft']=replace(current,period=ReportPeriod(2026,10))
    elif change=='qa_generation':app.session_state['_monthly_qa_generation']='replacement-qa-generation'
    else:library.save_snapshot(current,expected_revision=0,entered_editor='Concurrent editor')
    futures[0].set_result({'items':[]})
    app.run()
    assert not app.exception
    assert validations==[] and calls['cache']==0 and calls['start']==1


def test_held_native_suggestion_add_cannot_approve_another_pending_read(monkeypatch,tmp_path):
    app,calls,uploads,futures=setup(monkeypatch,tmp_path,pending=True)
    app.run();read(app).click().run()
    current=app.session_state['test_draft']
    app.session_state['test_draft']=replace(current,blocks=(replace(current.blocks[0],text='Manual wording A.'),))
    futures[0].set_result({'items':[]});app.run()
    old=next(b for b in app.button if b.label=='Add new source suggestions to my edits')
    uploads[0]=[upload(b'Completed another synthetic inspection.')]
    app.run();read(app).click().run()
    current=app.session_state['test_draft']
    app.session_state['test_draft']=replace(current,blocks=(replace(current.blocks[0],text='Manual wording B.'),))
    futures[1].set_result({'items':[]});app.run()
    before=app.session_state['test_draft']
    pending_key=next(k for k in app.session_state.filtered_state if k.endswith('_pending'))
    pending=app.session_state[pending_key]
    newer=next(b for b in app.button if b.label=='Add new source suggestions to my edits')
    assert old.key != newer.key
    old.click().run()
    assert not app.exception
    assert app.session_state['test_draft']==before
    assert app.session_state[pending_key]==pending and calls['cache']==0
    next(b for b in app.button if b.label=='Add new source suggestions to my edits').click().run()
    assert not app.exception
    assert pending_key not in app.session_state.filtered_state and calls['cache']==1
    app.run()
    assert calls['cache']==1 and calls['start']==2


def test_disappearing_reader_configuration_rejects_old_native_action_without_spending(monkeypatch,tmp_path):
    app,calls,_,_=setup(monkeypatch,tmp_path)
    app.run();old=read(app)
    monkeypatch.setattr(ai,'ANTHROPIC_API_KEY','')
    old.click().run()
    assert not app.exception
    assert calls['start']==calls['reserve']==calls['prepare']==0
    assert any('not configured' in x.value for x in app.warning)
