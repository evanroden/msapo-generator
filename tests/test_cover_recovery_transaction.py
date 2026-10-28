from dataclasses import replace,asdict
from io import BytesIO
import pytest
from PIL import Image
from app import monthly_report_cover_recovery as recovery
from app import monthly_report_library as library
from app.monthly_report_model import ReportDraft,ReportPeriod,ResolvedBlock,synthetic_profiles

@pytest.fixture
def draft(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    return ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Editor',(),
                       (ResolvedBlock('cover_photo','Omit'),))

def raw():
    stream=BytesIO(); Image.new('RGB',(80,40),'navy').save(stream,'PNG');return stream.getvalue()


def test_upload_recovery_is_one_shot_and_keeps_original_reference(draft):
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    assert requested.blocks==draft.blocks
    assets={}
    recovered=recovery.attempt_cover_recovery(requested,revision=0,assets=assets,event='upload')
    assert recovered.cover_recovery_request.status=='ready'
    assert recovered.blocks==draft.blocks
    recovered=recovery.apply_cover_recovery(recovered,revision=0,assets=assets)
    assert recovered.cover_recovery_request.status=='applied'
    assert recovered.blocks[0].cover_original.occurrence_id==requested.cover_recovery_request.occurrence_id
    again=recovery.attempt_cover_recovery(recovered,revision=0,assets=assets,event='upload')
    assert again is recovered


@pytest.mark.parametrize('change',['cover','period','sites','revision'])
def test_stale_request_never_overwrites_new_context(draft,change):
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    if change=='cover':
        requested=replace(requested,blocks=(replace(draft.blocks[0],text='changed'),))
    elif change=='period':requested=replace(requested,period=ReportPeriod(2026,10))
    elif change=='sites':requested=replace(requested,profile=replace(draft.profile,facilities=(replace(draft.profile.facilities[0],key='other'),)))
    assets={}
    result=recovery.attempt_cover_recovery(requested,revision=1 if change=='revision' else 0,assets=assets,event='upload')
    assert result.blocks==requested.blocks and assets=={}
    assert result.cover_recovery_request.status=='stale'


def test_save_reopen_preserves_pending_and_new_month_does_not_retry(draft,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_setup import new_month_draft
    monkeypatch.setattr(jobs,'memory_headroom',lambda:0)
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    pending=recovery.attempt_cover_recovery(requested,revision=0,assets={},event='upload')
    assert pending.cover_recovery_request.status=='pending'
    saved=library.save_snapshot(pending,expected_revision=0)
    reopened=library.load_snapshot(draft.profile.contract,draft.profile.key,draft.period).draft
    assert reopened.cover_recovery_request.bound_revision==saved.revision
    assert reopened.cover_recovery_request.status=='pending'
    assert new_month_draft(reopened,ReportPeriod(2026,10)).cover_recovery_request is None
    assert reopened.blocks==draft.blocks
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    assets={}
    result=recovery.attempt_cover_recovery(reopened,revision=saved.revision,assets=assets,event='resume')
    assert result.cover_recovery_request.status=='ready'
    assert result.blocks==draft.blocks


def test_concurrent_save_during_decode_cannot_publish_replacement(draft,monkeypatch):
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    original=recovery.recover_cover_original
    def racing(profile,reference):
        result=original(profile,reference)
        library.save_snapshot(draft,expected_revision=0)
        return result
    monkeypatch.setattr(recovery,'recover_cover_original',racing)
    assets={}
    result=recovery.attempt_cover_recovery(requested,revision=0,assets=assets,event='upload')
    assert result.cover_recovery_request.status=='stale'
    assert result.blocks==draft.blocks and assets=={}


def test_browser_journal_retains_pending_metadata_without_rerender_rewrites(draft):
    from app import monthly_report_active_work as active
    token='a'*32
    first=active.save(token,draft,expected_revision=0,base_snapshot_revision=0)
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    assert requested.fingerprint==draft.fingerprint
    second=active.save(token,requested,expected_revision=first.revision,base_snapshot_revision=0)
    assert second.revision==first.revision+1
    third=active.save(token,requested,expected_revision=second.revision,base_snapshot_revision=0)
    assert third.revision==second.revision
    loaded=active.load(token,draft.profile.contract,draft.profile.key,draft.period)
    assert loaded.draft.cover_recovery_request==requested.cover_recovery_request


def test_ready_request_save_reopen_and_explicit_use(draft):
    assets={}
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    ready=recovery.attempt_cover_recovery(requested,revision=0,assets=assets,event='upload')
    saved=library.save_snapshot(ready,expected_revision=0,assets=tuple(assets.items()))
    reopened=library.load_snapshot(draft.profile.contract,draft.profile.key,draft.period).draft
    assert reopened.blocks==draft.blocks and reopened.cover_recovery_request.status=='ready'
    used=recovery.apply_cover_recovery(reopened,revision=saved.revision,assets={})
    assert used.cover_recovery_request.status=='applied'
    assert used.blocks!=draft.blocks


def test_ready_request_stale_use_never_changes_cover(draft):
    assets={}
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    ready=recovery.attempt_cover_recovery(requested,revision=0,assets=assets,event='upload')
    newer=replace(ready,blocks=(replace(draft.blocks[0],text='changed'),))
    attempted=recovery.apply_cover_recovery(newer,revision=0,assets=assets)
    assert attempted.blocks==newer.blocks
    assert attempted.cover_recovery_request.status=='stale'


def test_two_transient_denials_do_not_exhaust_later_ready_resume(draft,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    requested=recovery.begin_cover_recovery(draft,raw(),revision=0)
    monkeypatch.setattr(jobs,'memory_headroom',lambda:0)
    first=recovery.attempt_cover_recovery(requested,revision=0,assets={},event='upload')
    second=recovery.attempt_cover_recovery(first,revision=0,assets={},event='resume')
    assert second.cover_recovery_request.events==()
    assert second.cover_recovery_request.status=='pending' and second.blocks==draft.blocks
    monkeypatch.setattr(jobs,'memory_headroom',lambda:400*1024*1024)
    assets={}
    ready=recovery.attempt_cover_recovery(second,revision=0,assets=assets,event='resume')
    assert ready.cover_recovery_request.status=='ready'
    assert ready.blocks==draft.blocks
