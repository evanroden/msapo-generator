from io import BytesIO
from PIL import Image
from streamlit.testing.v1 import AppTest
import pytest


def harness():
    return AppTest.from_string('''
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import ReportDraft, ReportPeriod,ResolvedBlock,synthetic_profiles
from app.monthly_report_cover_ui import render_cover_photograph
report=st.session_state.setdefault('report',ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Editor',(),(ResolvedBlock('cover_photo','Omit'),)))
assets=st.session_state.setdefault('assets',{})
blocks=render_cover_photograph({b.key:b for b in report.blocks},'test',assets,lambda ref:assets[ref],scope=(report.profile.contract,report.profile.key,report.period.key,tuple(site.key for site in report.profile.facilities),st.session_state.get('epoch',1)),report=report,revision=st.session_state.get('revision',0))
st.session_state.report=replace(report,blocks=tuple(blocks.values()),cover_recovery_request=st.session_state.pop('test_cover_recovery_request_update',report.cover_recovery_request))
''',default_timeout=20).run()

@pytest.fixture
def setup(tmp_path,monkeypatch):
    from app import monthly_report_cover_ui as ui
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    incoming={}
    real=ui.st.file_uploader
    monkeypatch.setattr(ui.st,'file_uploader',lambda label,*a,**kw:incoming.get(label) or real(label,*a,**kw))
    return incoming


def upload(incoming):
    stream=BytesIO();Image.new('RGBA',(100,50),(10,20,30,100)).save(stream,'PNG')
    stream.name='photo.jpg';stream.size=len(stream.getvalue())
    incoming['New photograph for this report']=stream


def test_prepare_is_automatic_but_use_is_explicit_and_not_repeated(setup,monkeypatch):
    from app import monthly_report_cover_recovery as recovery
    real=recovery._normal_candidate;calls=[]
    def run(*args):calls.append(1);return real(*args)
    monkeypatch.setattr(recovery,'_normal_candidate',run)
    app=harness();original=app.session_state.report.blocks
    upload(setup);app.run()
    assert not app.exception and not app.warning and not app.error
    assert app.session_state.report.blocks==original
    assert app.session_state.report.cover_recovery_request.status=='ready'
    for _ in range(3):app.run()
    assert len(calls)==1 and app.session_state.report.blocks==original
    next(button for button in app.button if button.label=='Use this photograph').click().run()
    assert not app.exception
    assert app.session_state.report.cover_recovery_request.status=='applied'
    assert app.session_state.report.blocks[0].cover_original is not None


def test_clearing_upload_cancels_prepared_intent_not_original(setup):
    app=harness();original=app.session_state.report.blocks
    upload(setup);app.run()
    request=app.session_state.report.cover_recovery_request
    setup.clear();app.run()
    assert app.session_state.report.cover_recovery_request is None
    assert app.session_state.report.blocks==original
    from app.monthly_report_cover_recovery import cover_original_path,original_reference
    assert cover_original_path(app.session_state.report.profile,original_reference(request)).exists()


def test_busy_rerenders_do_not_retry_but_real_reopen_can_prepare(setup,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    from app import monthly_report_cover_recovery as recovery
    real=recovery.attempt_cover_recovery;calls=[]
    def attempt(*args,**kwargs):calls.append(kwargs['event']);return real(*args,**kwargs)
    monkeypatch.setattr(recovery,'attempt_cover_recovery',attempt)
    monkeypatch.setattr(jobs,'memory_headroom',lambda:0)
    app=harness();upload(setup);app.run()
    assert calls==['upload']
    pending=app.session_state.report
    for _ in range(4):app.run()
    assert calls==['upload']
    setup.clear()
    reopened=harness()
    reopened.session_state.report=pending
    reopened.run()
    assert calls==['upload','resume']
    assert reopened.session_state.report.cover_recovery_request.events==()
    # Another genuine editor incarnation after capacity returns; no timer or
    # hot-rerender polling and neither busy event spent the decoder budget.
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    available=harness();available.session_state.report=reopened.session_state.report;available.run()
    assert available.session_state.report.cover_recovery_request.status=='ready'
    assert available.session_state.report.blocks==pending.blocks


def test_restored_ready_use_is_bound_to_current_editor_incarnation(setup):
    app=harness();upload(setup);app.run()
    ready=app.session_state.report
    setup.clear()
    resumed=harness();resumed.session_state.report=ready;resumed.session_state.assets=dict(app.session_state.assets);resumed.run()
    old_use=next(button for button in resumed.button if button.label=='Use this photograph')
    resumed.session_state.epoch=2;resumed.run()
    new_use=next(button for button in resumed.button if button.label=='Use this photograph')
    assert old_use.key!=new_use.key
    old_use.click()
    packet=resumed._tree.get_widget_states();packet.widgets.append(old_use._widget_state)
    resumed._run(packet)
    assert not resumed.exception
    assert resumed.session_state.report.blocks==ready.blocks
    next(button for button in resumed.button if button.label=='Use this photograph').click().run()
    assert resumed.session_state.report.cover_recovery_request.status=='applied'


def test_interrupted_processed_upload_without_request_is_not_permanently_skipped(setup):
    from dataclasses import replace
    app=harness();upload(setup);app.run()
    # Model interruption after source identity was installed but before the
    # prepared request reached the owning draft. The verified cache is usable.
    app.session_state.report=replace(app.session_state.report,cover_recovery_request=None)
    app.run()
    assert not app.exception
    assert app.session_state.report.cover_recovery_request.status=='ready'
    assert any(button.label=='Use this photograph' for button in app.button)


def test_held_use_cannot_bind_reprepared_identical_bytes(setup):
    app=harness();upload(setup);app.run()
    old_use=next(button for button in app.button if button.label=='Use this photograph')
    original=app.session_state.report.blocks
    old_request=app.session_state.report.cover_recovery_request
    setup.clear();app.run();upload(setup);app.run()
    new_request=app.session_state.report.cover_recovery_request
    assert new_request.sha256==old_request.sha256 and new_request.occurrence_id!=old_request.occurrence_id
    new_use=next(button for button in app.button if button.label=='Use this photograph')
    assert new_use.key!=old_use.key
    old_use.click();packet=app._tree.get_widget_states();packet.widgets.append(old_use._widget_state);app._run(packet)
    assert not app.exception and app.session_state.report.blocks==original
    next(button for button in app.button if button.label=='Use this photograph').click().run()
    assert app.session_state.report.cover_recovery_request.status=='applied'


def test_held_use_cannot_bind_reloaded_ready_request(setup):
    app=harness();upload(setup);app.run()
    old_use=next(button for button in app.button if button.label=='Use this photograph')
    ready=app.session_state.report;assets=dict(app.session_state.assets)
    setup.clear()
    reloaded=harness();reloaded.session_state.report=ready;reloaded.session_state.assets=assets;reloaded.run()
    assert next(button for button in reloaded.button if button.label=='Use this photograph').key!=old_use.key
    old_use.click();packet=reloaded._tree.get_widget_states();packet.widgets.append(old_use._widget_state);reloaded._run(packet)
    assert not reloaded.exception and reloaded.session_state.report.blocks==ready.blocks
    next(button for button in reloaded.button if button.label=='Use this photograph').click().run()
    assert reloaded.session_state.report.cover_recovery_request.status=='applied'


def test_storage_admission_failure_is_not_retried_every_rerender(setup,monkeypatch):
    from app import monthly_report_cover_recovery as recovery
    calls=[]
    def full(*args,**kwargs):calls.append(1);raise ValueError('storage full')
    monkeypatch.setattr(recovery,'begin_cover_recovery',full)
    app=harness();upload(setup);app.run()
    for _ in range(4):app.run()
    assert len(calls)==1
    assert app.session_state.report.cover_recovery_request is None
    assert not app.error and not app.warning and not app.exception


def test_held_use_cannot_bind_changed_report_scope(setup):
    from dataclasses import replace
    app=harness();upload(setup);app.run()
    old_use=next(button for button in app.button if button.label=='Use this photograph')
    old_blocks=app.session_state.report.blocks
    setup.clear()
    app.session_state.report=replace(app.session_state.report,profile=replace(app.session_state.report.profile,key='other'))
    app.run()
    old_use.click();packet=app._tree.get_widget_states();packet.widgets.append(old_use._widget_state);app._run(packet)
    assert not app.exception and app.session_state.report.blocks==old_blocks
    upload(setup);app.run()
    next(button for button in app.button if button.label=='Use this photograph').click().run()
    assert app.session_state.report.cover_recovery_request.status=='applied'


def test_held_use_is_invalid_after_shared_revision_stamps_ready_request(setup):
    from app import monthly_report_library as library
    app=harness();upload(setup);app.run()
    ready=app.session_state.report
    old_use=next(button for button in app.button if button.label=='Use this photograph')
    saved=library.save_snapshot(ready,expected_revision=0,assets=tuple(app.session_state.assets.items()))
    app.session_state.report=saved.draft;app.session_state.revision=saved.revision
    app.run()
    assert next(button for button in app.button if button.label=='Use this photograph').key!=old_use.key
    old_use.click();packet=app._tree.get_widget_states();packet.widgets.append(old_use._widget_state);app._run(packet)
    assert not app.exception and app.session_state.report.blocks==ready.blocks
    next(button for button in app.button if button.label=='Use this photograph').click().run()
    assert app.session_state.report.cover_recovery_request.status=='applied'
