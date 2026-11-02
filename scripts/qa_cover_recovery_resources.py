"""New recovery-service gate: synthetic inputs, real capped container required.

Imports the production guided-report modules, retains visitor upload buffers,
and measures parent+child cgroup usage. This is not a browser/render fidelity
claim. Run in a fresh Docker container for every case; no simulated admission.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
from threading import Event, Thread
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MIB=1024*1024


def cgroup_value(name):
    try:
        return int((Path('/sys/fs/cgroup')/name).read_text())
    except (OSError,ValueError):
        return None


def oom_kills():
    for path in (Path('/sys/fs/cgroup/memory.events'),
                 Path('/sys/fs/cgroup/memory/memory.oom_control')):
        try:
            return int(dict(line.split() for line in path.read_text().splitlines())['oom_kill'])
        except (OSError,ValueError,KeyError):
            continue
    return None



def independent_uploads(*, source=None, path=None, visitors=1):
    # BytesIO(bytes) can share immutable backing bytes. Reread a file per
    # visitor, or force a distinct small synthetic bytes object per visitor.
    uploads=[BytesIO(path.read_bytes() if path is not None else bytes(bytearray(source)))
             for _ in range(visitors)]
    backing=[upload.getvalue() for upload in uploads]
    assert len({id(raw) for raw in backing})==visitors, 'Visitors must retain independent upload buffers'
    return uploads


def main(args):
    from scripts.qa_cover_photo_resources import cgroup_memory
    limit,current=cgroup_memory()
    assert os.environ.get('RESOURCE_REQUIRE_512_MB')=='1', 'This is a real-cgroup acceptance probe only'
    assert limit is not None and 0<limit<=512*MIB, 'Real <=512 MiB cgroup required'
    before_oom=oom_kills()
    assert before_oom is not None, 'Cgroup child OOM accounting is required for acceptance'
    from app import monthly_report_guided  # Real parent modules/dependencies, no UI invocation.
    from app import monthly_report_cover_recovery as recovery
    from app import monthly_report_render_jobs as jobs
    from app.monthly_report_cover_originals import cover_original_path
    from app.monthly_report_model import ReportDraft,ReportPeriod,ResolvedBlock,synthetic_profiles
    from app import monthly_report_library as library
    from PIL import Image
    if args.kind=='corrupt':
        source=b'not a photograph'
    elif args.source:
        assert 30*MIB<args.source.stat().st_size<=64*MIB
        source=None
    else:
        out=BytesIO();Image.new('RGBA' if args.kind=='alpha' else 'RGB',(420,250),
            (10,20,30,100) if args.kind=='alpha' else (10,20,30)).save(out,'PNG')
        source=out.getvalue()
    # Force independently retained bytes, like distinct uploader visitors.
    uploads=independent_uploads(source=source,path=args.source,visitors=args.visitors)
    del source
    old_out=BytesIO();Image.new('RGB',(20,10),'navy').save(old_out,'JPEG')
    old_raw=old_out.getvalue();old_ref=library.asset_reference(old_raw,'jpg')
    old=ResolvedBlock('cover_photo','Library',asset_hashes=(old_ref,))
    profile=synthetic_profiles()[0]
    draft=ReportDraft(profile,ReportPeriod(2026,9),'Synthetic Editor',(),(old,))
    held,release=Event(),Event()
    thread=None
    if args.kind=='slot':
        def hold():
            with jobs.work_slot(wait_seconds=0):
                held.set();assert release.wait(20)
        thread=Thread(target=hold);thread.start();assert held.wait(10)
    if args.kind in ('timeout','isolated'):
        # Deterministic eligible decoder failure: admission/resource guards
        # remain real, and only this synthetic probe forces the alternate path.
        recovery._normal_candidate=lambda *args:('fallback',None)
    if args.kind=='timeout':
        recovery.WALL_SECONDS=0.001  # Exercise real process-group kill/reap.
    started=time.monotonic()
    def attempt(index):
        raw=uploads[index].getvalue()
        # Different visitor profiles prevent the private-original/cache store
        # from deduplicating these independent retained inputs in this gate.
        visitor_profile=replace(profile,key='visitor_'+str(index))
        visitor_draft=replace(draft,profile=visitor_profile)
        assets={old_ref:old_raw}
        requested=recovery.begin_cover_recovery(visitor_draft,raw,revision=0)
        prepared=recovery.attempt_cover_recovery(requested,revision=0,assets=assets,event='upload')
        assert prepared.blocks==draft.blocks, 'Preparation applied artwork without Use'
        assert assets[old_ref]==old_raw
        original=cover_original_path(visitor_profile,recovery.original_reference(prepared.cover_recovery_request))
        assert original.stat().st_size==len(raw)
        if prepared.cover_recovery_request.status=='ready':
            applied=recovery.apply_cover_recovery(prepared,revision=0,assets=assets)
            assert applied.cover_recovery_request.status=='applied'
            assert applied.blocks[0].cover_original.sha256==requested.cover_recovery_request.sha256
            result={'status':'recovered','bytes':len(assets[applied.blocks[0].asset_hashes[0]])}
        else:
            assert prepared.blocks==(old,)
            result={'status':prepared.cover_recovery_request.status,'reason':prepared.cover_recovery_request.reason}
        return prepared,assets,result
    try:
        with ThreadPoolExecutor(max_workers=args.visitors) as pool:
            observations=list(pool.map(attempt,range(args.visitors)))
    finally:
        if thread:
            release.set();thread.join(10);assert not thread.is_alive()
    if args.kind=='slot':
        prepared,assets,result=observations[0]
        assert result['status']=='pending' and result['reason']=='work_busy'
        resumed=recovery.attempt_cover_recovery(prepared,revision=0,assets=assets,event='resume')
        assert resumed.cover_recovery_request.status=='ready', 'Resource recovery after work slot release must succeed'
    results=[entry[2] for entry in observations]
    if args.expect=='success':
        assert any(result['status']=='recovered' for result in results), results
    if args.kind in ('corrupt','timeout'):
        assert all(result['status']!='recovered' for result in results), results
    assert not list(library._root().rglob('.cover-recovery-*')), 'Temporary decoder files were retained'
    after_oom=oom_kills()
    assert after_oom is not None and after_oom==before_oom, 'A process was OOM-killed or cgroup OOM accounting disappeared'
    print(json.dumps({'kind':args.kind,'source':args.source.name if args.source else 'small-synthetic',
        'visitors':args.visitors,'distinct_original_profiles':args.visitors,
        'retained_upload_bytes':sum(len(upload.getbuffer()) for upload in uploads),
        'retained_original_bytes':sum(entry[0].cover_recovery_request.byte_count for entry in observations),
        'normalizer_temporary_input_cap_bytes':64*MIB,'simulation_only':False,'cgroup_limit_bytes':limit,
        'cgroup_start_bytes':current,'cgroup_finish_bytes':cgroup_memory()[1],
        'cgroup_peak_bytes':cgroup_value('memory.peak'),'oom_kill_before':before_oom,'oom_kill_after':after_oom,
        'parent_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'child_peak_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        'seconds':round(time.monotonic()-started,3),'results':results}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path)
    parser.add_argument('--visitors',type=int,choices=(1,2),default=1)
    parser.add_argument('--kind',choices=('photo','alpha','corrupt','slot','timeout','isolated'),default='photo')
    parser.add_argument('--expect',choices=('success','safe'),default='safe')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='cover-recovery-probe-') as directory:
        os.environ['EPC_DATA_DIR']=directory
        main(args)
