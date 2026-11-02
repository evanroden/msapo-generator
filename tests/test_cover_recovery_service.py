from io import BytesIO
from dataclasses import replace
import pytest
from PIL import Image
from app import monthly_report_cover_recovery as recovery
from app.monthly_report_cover_originals import store_cover_original
from app.monthly_report_model import ReportProfile, Facility

@pytest.fixture
def profile(tmp_path, monkeypatch):
    from app import monthly_report_library as library
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(library, '_root', lambda: tmp_path)
    monkeypatch.setattr(jobs, 'memory_headroom', lambda: 400*1024*1024)
    return ReportProfile('Contract A','a','A',(Facility('a','A'),))


def test_success_cached_per_original_and_validated(profile, monkeypatch):
    stream=BytesIO(); Image.new('RGBA',(200,100),(10,20,30,100)).save(stream,'PNG')
    ref=store_cover_original(profile,stream.getvalue())
    first=recovery.recover_cover_original(profile,ref)
    assert first.status=='recovered'
    assert (first.image.width,first.image.height,first.image.extension)==(200,100,'jpg')
    monkeypatch.setattr(recovery,'_run_worker',lambda *a: pytest.fail('must use verified cache'))
    second=recovery.recover_cover_original(profile,ref)
    assert second.image==first.image


def test_corruption_failure_not_retried_each_rerun(profile, monkeypatch):
    ref=store_cover_original(profile,b'broken photo')
    first=recovery.recover_cover_original(profile,ref)
    assert first.status=='unrecoverable'
    monkeypatch.setattr(recovery,'_run_worker',lambda *a: pytest.fail('must not retry identical failed attempt'))
    assert recovery.recover_cover_original(profile,ref).status=='unrecoverable'


def test_unknown_headroom_never_starts_worker(profile,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    ref=store_cover_original(profile,b'photo')
    monkeypatch.setattr(jobs,'memory_headroom',lambda:None)
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *a:('memory',None))
    monkeypatch.setattr(recovery,'_run_worker',lambda *a:pytest.fail('no resource admission'))
    assert recovery.recover_cover_original(profile,ref).status=='pending'


def test_transient_busy_does_not_cache_permanent_failure(profile,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    stream=BytesIO(); Image.new('RGB',(20,10)).save(stream,'PNG')
    ref=store_cover_original(profile,stream.getvalue())
    jobs._WORK_SLOT.acquire()
    try:
        assert recovery.recover_cover_original(profile,ref).status=='pending'
    finally:
        jobs._WORK_SLOT.release()
    assert recovery.recover_cover_original(profile,ref).status=='recovered'


def test_occurrences_distinct_for_identical_derivatives_and_originals_not_exported(profile):
    from app.monthly_report_model import ResolvedBlock, ReportDraft, ReportPeriod, used_asset_references
    from app import monthly_report_library as library
    from dataclasses import asdict
    stream=BytesIO(); Image.new('RGB',(20,10),'navy').save(stream,'PNG')
    first_raw=stream.getvalue(); second_raw=first_raw+b'original trailing metadata'
    assets={}; block=ResolvedBlock('cover_photo','Omit')
    first,outcome=recovery.prepare_cover_replacement(profile,block,first_raw,assets)
    second,outcome=recovery.prepare_cover_replacement(profile,first,second_raw,assets)
    assert first.asset_hashes==second.asset_hashes
    assert first.cover_original.sha256!=second.cover_original.sha256
    assert first.cover_original.occurrence_id!=second.cover_original.occurrence_id
    assert library.block_from_dict(asdict(second))==second
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Editor',(),(second,))
    assert used_asset_references(draft)==set(second.asset_hashes)
    saved=library.save_snapshot(draft,expected_revision=0,assets=tuple(assets.items()))
    assert saved.draft.blocks[0].cover_original==second.cover_original
    reopened=library.load_snapshot(profile.contract,profile.key,draft.period)
    assert reopened.draft.blocks[0].cover_original==second.cover_original
    following=replace(draft,period=ReportPeriod(2026,10))
    library.save_snapshot(following,expected_revision=0)
    assert library.load_snapshot(profile.contract,profile.key,following.period).draft.blocks[0].cover_original==second.cover_original
    with pytest.raises(library.RevisionConflict):
        library.save_snapshot(draft,expected_revision=0)
    assert recovery.cover_original_path(profile,recovery.original_reference(second.cover_original)).exists()


def test_failed_recovery_retains_block_and_assets(profile):
    from app.monthly_report_model import ResolvedBlock
    old=ResolvedBlock('cover_photo','Library',asset_hashes=('old',))
    assets={'old':b'last good'}
    result,outcome=recovery.prepare_cover_replacement(profile,old,b'corrupted input',assets)
    assert result is old
    assert outcome.status!='recovered'
    assert assets=={'old':b'last good'}


def test_legacy_fingerprints_unchanged(profile):
    from app.monthly_report_model import ResolvedBlock,ReportDraft,ReportPeriod
    block=ResolvedBlock('cover_photo','Omit')
    assert block.fingerprint=='bdb1c065d349f1fb23402a8f2143297fb861de25da9ef8ed7bc8a5fe11e8f415'
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Editor',(),(block,))
    assert draft.fingerprint=='08f844db7e4b4797ae1f9b6dfd9da731d0bea2731f688f91ea0ee835e4fd7c06'


@pytest.mark.parametrize('failure',['timeout','memory_limit'])
def test_resource_failure_retains_last_good_and_retries_only_with_more_actual_headroom(profile,monkeypatch,failure):
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_model import ResolvedBlock
    jobs_headroom=[384*1024*1024]
    monkeypatch.setattr(jobs,'memory_headroom',lambda:jobs_headroom[0])
    calls=[]
    def fail(source,target,budget):
        calls.append(budget)
        return failure
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *a:('fallback',None))
    monkeypatch.setattr(recovery,'_run_worker',fail)
    old=ResolvedBlock('cover_photo','Library',asset_hashes=('old',))
    assets={'old':b'last good'}
    for _ in range(3):
        result,outcome=recovery.prepare_cover_replacement(profile,old,b'original input',assets)
        assert result is old and outcome.status=='pending'
    assert len(calls)==1
    jobs_headroom[0]=512*1024*1024
    result,outcome=recovery.prepare_cover_replacement(profile,old,b'original input',assets)
    assert len(calls)==2 and calls[1]>calls[0]
    assert max(calls)<=256*1024*1024
    for _ in range(3):
        recovery.prepare_cover_replacement(profile,old,b'original input',assets)
    assert len(calls)==2 and assets=={'old':b'last good'}
    ref=store_cover_original(profile,b'original input')
    assert recovery.cover_original_path(profile,ref).read_bytes()==b'original input'


def test_actual_wall_timeout_reaps_child(profile,tmp_path,monkeypatch):
    worker=tmp_path/'sleep.py'
    worker.write_text('import time; time.sleep(60)')
    monkeypatch.setattr(recovery,'_WORKER',worker)
    monkeypatch.setattr(recovery,'WALL_SECONDS',0.1)
    from app import monthly_report_cover_storage as private
    from app import monthly_report_library as library
    reference=store_cover_original(profile,b'original')
    source=recovery.cover_original_path(profile,reference)
    folder=library._profile_path(profile.contract,profile.key)/'cover-recovery'
    with private.locked_folder(folder), private.temporary_folder(folder) as temporary:
        assert recovery._run_worker(source,temporary/'output',64*1024*1024)=='timeout'


def test_storage_full_keeps_old_without_claiming_recovery(profile,monkeypatch):
    from app import monthly_report_cover_originals as originals
    from app.monthly_report_model import ResolvedBlock
    monkeypatch.setattr(originals,'MAX_ORIGINAL_STORE_BYTES',1)
    old=ResolvedBlock('cover_photo','Library',asset_hashes=('old',))
    assets={'old':b'last good'}
    result,outcome=recovery.prepare_cover_replacement(profile,old,b'original',assets)
    assert result is old and outcome.status=='pending' and outcome.reason=='original_storage'
    assert assets=={'old':b'last good'}


def test_oversized_worker_output_not_read_and_temporary_files_removed(profile,monkeypatch):
    from app import monthly_report_library as library
    def oversized(source,target,budget):
        with target.open('wb') as output:
            output.seek(recovery.MAX_OUTPUT_BYTES)
            output.write(b'x')
        return 'success'
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *a:('fallback',None))
    monkeypatch.setattr(recovery,'_run_worker',oversized)
    reference=store_cover_original(profile,b'original')
    outcome=recovery.recover_cover_original(profile,reference)
    assert outcome.status=='unrecoverable' and outcome.reason=='invalid_derivative'
    folder=library._profile_path(profile.contract,profile.key)/'cover-recovery'
    assert not list(folder.glob('.cover-recovery-*'))


def test_tiny_photo_uses_approved_normalizer_when_cgroup_unknown(profile,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs,'memory_headroom',lambda:None)
    monkeypatch.setattr(recovery,'_run_worker',lambda *args:pytest.fail('isolated path requires actual headroom'))
    stream=BytesIO();Image.new('RGB',(100,50),'navy').save(stream,'PNG')
    reference=store_cover_original(profile,stream.getvalue())
    outcome=recovery.recover_cover_original(profile,reference)
    assert outcome.status=='recovered' and outcome.image.extension=='jpg'


def test_unsafe_progressive_unknown_cgroup_stays_pending(profile,monkeypatch):
    from app import monthly_report_render_jobs as jobs
    monkeypatch.setattr(jobs,'memory_headroom',lambda:None)
    monkeypatch.setattr(recovery,'_run_worker',lambda *args:pytest.fail('cannot bypass unknown cgroup guard'))
    stream=BytesIO();image=Image.new('RGB',(6000,6000),'navy')
    image.save(stream,'JPEG',quality=95,subsampling=0,progressive=True);image.close()
    reference=store_cover_original(profile,stream.getvalue())
    outcome=recovery.recover_cover_original(profile,reference)
    assert outcome.status=='pending'


@pytest.mark.parametrize('orientation',[1,6,8])
def test_normal_and_isolated_cover_visual_policy_identical(profile,monkeypatch,orientation):
    stream=BytesIO();image=Image.new('RGBA',(160,80),(10,20,30,100))
    exif=Image.Exif();exif[274]=orientation
    image.save(stream,'PNG',exif=exif)
    raw=stream.getvalue()
    normal=recovery.recover_cover_original(profile,store_cover_original(profile,raw))
    alternate=replace(profile,key='isolated')
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *args:('fallback',None))
    isolated=recovery.recover_cover_original(alternate,store_cover_original(alternate,raw))
    assert normal.status==isolated.status=='recovered'
    assert normal.image.extension==isolated.image.extension=='jpg'
    assert normal.image==isolated.image
    original=recovery.cover_original_path(profile,store_cover_original(profile,raw)).read_bytes()
    with Image.open(BytesIO(original)) as retained:
        assert retained.mode=='RGBA' and retained.getpixel((0,0))[3]==100


def test_corrupt_png_tries_one_bounded_fallback_then_keeps_failure_cached(profile,monkeypatch):
    raw=b'\x89PNG\r\n\x1a\ntruncated'
    reference=store_cover_original(profile,raw)
    real=recovery._run_worker;calls=[]
    def run(*args):calls.append(1);return real(*args)
    monkeypatch.setattr(recovery,'_run_worker',run)
    first=recovery.recover_cover_original(profile,reference)
    assert first.status=='unrecoverable' and len(calls)==1
    second=recovery.recover_cover_original(profile,reference)
    assert second.status=='unrecoverable' and len(calls)==1


def test_programming_errors_are_not_silently_treated_as_image_failure(profile,monkeypatch):
    from app import monthly_report_docx as docx
    stream=BytesIO();Image.new('RGB',(20,10)).save(stream,'PNG')
    reference=store_cover_original(profile,stream.getvalue())
    def broken(*args,**kwargs):raise RuntimeError('programmer error')
    monkeypatch.setattr(docx,'normalize_report_image',broken)
    with pytest.raises(RuntimeError,match='programmer error'):
        recovery.recover_cover_original(profile,reference)


@pytest.mark.parametrize("available", [256, 263])
def test_isolated_future_upload_reserve_accounts_for_native_padding(profile, monkeypatch, available):
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_cover_images import cover_uploader_limit_mb
    assert recovery.PARENT_UPLOAD_RESERVE == (2*cover_uploader_limit_mb()+64)*1024*1024 == 200*1024*1024
    ref=store_cover_original(profile,b'photo needing isolated recovery')
    monkeypatch.setattr(jobs,'memory_headroom',lambda:available*1024*1024)
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *a:('memory',None))
    monkeypatch.setattr(recovery,'_run_worker',lambda *a:pytest.fail('must reserve future native buffers'))
    outcome=recovery.recover_cover_original(profile,ref)
    assert outcome.status=='pending' and outcome.reason=='memory_busy'


@pytest.mark.parametrize("available,budget", [(264,64),(327,64),(328,128),(456,256)])
def test_isolated_worker_budget_starts_after_full_native_future_reserve(profile, monkeypatch, available, budget):
    from app import monthly_report_render_jobs as jobs
    ref=store_cover_original(profile,b'photo needing isolated recovery')
    monkeypatch.setattr(jobs,'memory_headroom',lambda:available*1024*1024)
    monkeypatch.setattr(recovery,'_normal_candidate',lambda *a:('memory',None))
    calls=[]
    def worker(source,target,limit):
        calls.append(limit)
        return 'memory_limit'
    monkeypatch.setattr(recovery,'_run_worker',worker)
    outcome=recovery.recover_cover_original(profile,ref)
    assert calls==[budget*1024*1024]
    assert outcome.status=='pending'
