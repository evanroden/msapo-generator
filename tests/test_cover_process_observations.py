"""Read-only, bounded process evidence; never a replacement for hosted Cover."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from scripts import workspace_cover_process_observations as probe

ROOT = Path(__file__).resolve().parents[1]


def row():
    return {'sequence': 1, 'phase': 'original-archive:before', 'current': 123,
            'processes': [{'pid': 12, 'ppid': 1, 'rss': 4096, 'role': 'service'}]}


def process(root, pid, *, parent=1, role='python', children='', rss='24 kB', task=None):
    p = root / str(pid)
    p.mkdir(exist_ok=True)
    (p / 'status').write_text(f'Name:\tprivate-name-never-emitted\nPPid:\t{parent}\nVmRSS:\t{rss}\n')
    (p / 'comm').write_text(role + '\n')
    t = p / 'task' / str(pid if task is None else task)
    t.mkdir(parents=True, exist_ok=True)
    (t / 'children').write_text(children)


def test_thread_owned_descendants_and_fixed_roles_only(tmp_path):
    process(tmp_path, 10, children='20 30 40', task=11)
    process(tmp_path, 20, parent=10, role='soffice.bin', children='50')
    process(tmp_path, 30, parent=10, role='/private/customer/source.docx')
    process(tmp_path, 40, parent=10, role='bash')
    process(tmp_path, 50, parent=20, role='python3.12')
    result = probe.processes(tmp_path, 10)
    assert [x['role'] for x in result['processes']] == ['service', 'office', 'other', 'shell', 'python-child']
    assert all(x['rss'] == 24 * 1024 for x in result['processes'])
    assert 'private' not in json.dumps(result) and 'customer' not in json.dumps(result)
    assert not result['process_scan_truncated'] and result['process_scan_unavailable'] == 0


def test_process_and_task_walk_are_bounded(tmp_path, monkeypatch):
    process(tmp_path, 10, children='20 30 40')
    for pid in (20, 30, 40): process(tmp_path, pid, parent=10)
    monkeypatch.setattr(probe, 'MAX_PROCESSES', 2)
    result = probe.processes(tmp_path, 10)
    assert len(result['processes']) == 2 and result['process_scan_truncated']
    monkeypatch.setattr(probe, 'MAX_PROCESSES', 16)
    monkeypatch.setattr(probe, 'MAX_TASKS', 0)
    result = probe.processes(tmp_path, 10)
    assert len(result['processes']) == 1 and result['process_scan_truncated']


def test_missing_children_uses_one_bounded_parent_snapshot(tmp_path, monkeypatch):
    process(tmp_path, 10)
    process(tmp_path, 20, parent=10)
    (tmp_path/'10/task/10/children').unlink()
    assert {x['pid'] for x in probe.processes(tmp_path,10)['processes']}=={10,20}
    monkeypatch.setattr(probe,'MAX_FALLBACK_ENTRIES',0)
    result=probe.processes(tmp_path,10)
    assert [x['pid'] for x in result['processes']]==[10] and result['process_scan_truncated']


@pytest.mark.parametrize('fallback',[False,True])
def test_child_with_changed_fresh_parent_is_not_attributed(tmp_path,monkeypatch,fallback):
    process(tmp_path,10,children='20')
    process(tmp_path,20,parent=999)
    if fallback:
        (tmp_path/'10/task/10/children').unlink()
        original=probe._read;reads=[]
        def changed(path,limit=probe.MAX_READ):
            raw=original(path,limit)
            if path==tmp_path/'20/status':
                reads.append(path)
                if len(reads)==1:return raw.replace('PPid:\t999','PPid:\t10')
            return raw
        monkeypatch.setattr(probe,'_read',changed)
    result=probe.processes(tmp_path,10)
    assert [x['pid'] for x in result['processes']]==[10]
    assert result['process_scan_unavailable']>0


@pytest.mark.parametrize('case', ['disappeared', 'bad-rss', 'negative-rss', 'huge-status', 'bad-child'])
def test_process_errors_are_explicit_without_paths_or_raw_content(tmp_path, case):
    process(tmp_path, 10, children='20')
    if case == 'bad-rss': (tmp_path/'10/status').write_text('PPid: 1\nVmRSS: private bytes\n')
    if case == 'negative-rss': (tmp_path/'10/status').write_text('PPid: 1\nVmRSS: -1 kB\n')
    if case == 'huge-status': (tmp_path/'10/status').write_text('private' * 3000)
    if case == 'bad-child': (tmp_path/'10/task/10/children').write_text('private')
    result = probe.processes(tmp_path, 10)
    assert result['process_scan_unavailable'] > 0 and 'private' not in json.dumps(result)


def test_actual_thread_owned_python_child_is_seen_without_launching_browser():
    ready = threading.Event(); release = threading.Event(); state = {}
    def worker():
        child = subprocess.Popen([sys.executable, '-c', 'import sys;print("ready",flush=True);sys.stdin.read()'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            assert child.stdout.readline().strip() == 'ready'
            state['pid'] = child.pid; ready.set(); assert release.wait(5)
        finally:
            child.communicate(timeout=5)
    thread = threading.Thread(target=worker); thread.start()
    try:
        assert ready.wait(5)
        result = probe.processes()
        found = next(x for x in result['processes'] if x['pid'] == state['pid'])
        assert found['role'] == 'python-child' and found['rss'] > 0 and found['ppid'] == os.getpid()
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize('case,expected', [('missing','missing'),('valid','same-boot'),('stale','unverified'),
    ('foreign-pid','unavailable'),('huge','unavailable'),('symlink','unavailable'),('hardlink','unavailable')])
def test_office_owner_read_only_and_fail_closed(tmp_path, monkeypatch, case, expected):
    from app import office_process, monthly_report_render_jobs as jobs
    monkeypatch.setattr(office_process, '_boot_id', lambda:'known-boot')
    folder=tmp_path/'monthly_reports/render-jobs';folder.mkdir(parents=True)
    marker=folder/'.active-office.json'
    if case!='missing':
        marker.write_text(json.dumps({'pid':123,'boot':'other' if case=='stale' else 'known-boot'}))
    if case=='foreign-pid':marker.write_text(json.dumps({'pid':True,'boot':'known-boot'}))
    if case=='huge':marker.write_text('x'*1025)
    if case=='symlink':
        marker.unlink();marker.symlink_to(tmp_path/'outside')
        (tmp_path/'outside').write_text('private')
    if case=='hardlink':os.link(marker,tmp_path/'alias')
    before={str(p):p.lstat().st_mtime_ns for p in tmp_path.rglob('*')}
    result=probe.ownership(tmp_path)
    after={str(p):p.lstat().st_mtime_ns for p in tmp_path.rglob('*')}
    assert before==after and result['office_marker']==expected
    assert result['heavy_slot_locked']==jobs._WORK_SLOT.locked()
    assert 'private' not in json.dumps(result) and str(tmp_path) not in json.dumps(result)


def test_append_is_bounded_fsynced_and_collects_exact_numeric_rows(tmp_path, monkeypatch):
    original=os.fsync;syncs=[]
    monkeypatch.setattr(os,'fsync',lambda fd:(syncs.append(fd),original(fd))[1])
    probe.append(tmp_path,row());source=tmp_path/probe.FILE_NAME
    assert syncs and source.stat().st_mode & 0o777 == 0o600
    output=tmp_path/'out';output.mkdir();probe.collect(source,output/probe.FILE_NAME)
    assert (output/probe.FILE_NAME).read_bytes()==source.read_bytes()
    assert json.loads(source.read_text())==row()
    before=source.read_bytes();monkeypatch.setattr(probe,'MAX_FILE_BYTES',len(before))
    with pytest.raises(ValueError):probe.append(tmp_path,row())
    assert source.read_bytes()==before


@pytest.mark.parametrize('case', ['symlink','hardlink','directory','permissions','ancestor'])
def test_append_refuses_unsafe_file_or_ancestor(tmp_path,case):
    base=tmp_path;path=base/probe.FILE_NAME;other=tmp_path/'private';other.write_bytes(b'unchanged')
    if case=='symlink':path.symlink_to(other)
    elif case=='hardlink':os.link(other,path)
    elif case=='directory':path.mkdir()
    elif case=='permissions':path.write_text('');path.chmod(0o644)
    elif case=='ancestor':
        real=tmp_path/'real';real.mkdir();base=tmp_path/'linked';base.symlink_to(real,target_is_directory=True)
    with pytest.raises((OSError,ValueError)):probe.append(base,row())
    assert other.read_bytes()==b'unchanged'


@pytest.mark.parametrize('change', [{'private':'source content'},{'phase':'private/source'},
    {'processes':[{'pid':1,'ppid':0,'rss':1,'role':'private filename'}]}, {'current':True},
    {'office_marker':'private boot identity'},{'stat':{'private':123}}, {'sequence':257}])
def test_unknown_or_source_bearing_record_is_never_written_or_collected(tmp_path, change):
    bad={**row(),**change}
    with pytest.raises(ValueError):probe.append(tmp_path,bad)
    assert not (tmp_path/probe.FILE_NAME).exists()
    source=tmp_path/probe.FILE_NAME;source.write_text(json.dumps(bad)+'\n');source.chmod(0o600);out=tmp_path/'out';out.mkdir()
    with pytest.raises(ValueError):probe.collect(source,out/probe.FILE_NAME)
    assert not (out/probe.FILE_NAME).exists()


def test_collect_omits_torn_final_record_and_does_not_overwrite(tmp_path,capsys):
    source=tmp_path/probe.FILE_NAME;source.write_bytes((json.dumps(row())+'\n').encode()+b'{"private":"not validated');source.chmod(0o600)
    out=tmp_path/'out';out.mkdir();probe.collect(source,out/probe.FILE_NAME)
    assert json.loads((out/probe.FILE_NAME).read_text())==row()
    assert 'incomplete trailing row omitted' in capsys.readouterr().err
    with pytest.raises(FileExistsError):probe.collect(source,out/probe.FILE_NAME)


@pytest.mark.parametrize('raw',[
    b'{"sequence":1,"phase":"PRIVATE-SOURCE","phase":"original-archive:before"}\n',
    b'{"sequence":1,"phase":"original-archive:before","current":"PRIVATE-SOURCE","current":1}\n',
    b'{"sequence":1,"phase":"original-archive:before","processes":[{"pid":1,"ppid":0,"rss":1,"role":"PRIVATE-SOURCE","role":"service"}]}\n',
])
def test_duplicate_keys_cannot_hide_private_values_in_collected_raw_bytes(tmp_path,raw,capsys):
    source=tmp_path/probe.FILE_NAME;source.write_bytes(raw);source.chmod(0o600)
    out=tmp_path/'out';out.mkdir()
    with pytest.raises(ValueError,match='^Duplicate diagnostic key$') as error:
        probe.collect(source,out/probe.FILE_NAME)
    assert 'PRIVATE' not in str(error.value) and not (out/probe.FILE_NAME).exists()
    assert 'PRIVATE' not in capsys.readouterr().out


def test_actual_emit_receive_pipeline_creates_receiver_owned_readable_artifact(tmp_path):
    source=tmp_path/probe.FILE_NAME;probe.append(tmp_path,row())
    out=tmp_path/'out';out.mkdir();target=out/probe.FILE_NAME
    helper=ROOT/'scripts/workspace_cover_process_observations.py'
    sender=subprocess.Popen([sys.executable,str(helper),'--emit',str(source)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        receiver=subprocess.run([sys.executable,str(helper),'--receive',str(target)],stdin=sender.stdout,
                                capture_output=True,timeout=10)
        sender.stdout.close();stderr=sender.communicate(timeout=10)[1]
    finally:
        if sender.poll() is None:sender.kill();sender.wait()
    assert sender.returncode==0 and receiver.returncode==0,(stderr,receiver.stderr)
    assert target.stat().st_uid==os.geteuid() and target.stat().st_mode&0o777==0o600
    assert source.stat().st_mode&0o777==0o600 and json.loads(target.read_text())==row()
    assert os.access(target,os.R_OK)


def test_receiver_revalidates_input_before_artifact_creation(tmp_path):
    target=tmp_path/probe.FILE_NAME;helper=ROOT/'scripts/workspace_cover_process_observations.py'
    raw=b'{"sequence":1,"phase":"PRIVATE-SOURCE","phase":"original-archive:before"}\n'
    result=subprocess.run([sys.executable,str(helper),'--receive',str(target)],input=raw,capture_output=True,timeout=10)
    assert result.returncode!=0 and not target.exists()
    assert b'PRIVATE-SOURCE' not in result.stdout+result.stderr


@pytest.mark.parametrize('case',['symlink','hardlink','oversize','row-count','ancestor','output-link'])
def test_collect_refuses_unsafe_or_overbounded_evidence(tmp_path,case,monkeypatch):
    folder=tmp_path/'in';folder.mkdir();source=folder/probe.FILE_NAME
    source.write_text(json.dumps(row())+'\n');source.chmod(0o600);out=tmp_path/'out';out.mkdir();target=out/probe.FILE_NAME
    original=source.read_bytes()
    if case=='symlink':source.unlink();source.symlink_to(tmp_path/'private');(tmp_path/'private').write_bytes(original)
    elif case=='hardlink':os.link(source,tmp_path/'private')
    elif case=='oversize':monkeypatch.setattr(probe,'MAX_FILE_BYTES',1)
    elif case=='row-count':source.write_bytes(original*257)
    elif case=='ancestor':
        link=tmp_path/'link';link.symlink_to(folder,target_is_directory=True);source=link/probe.FILE_NAME
    elif case=='output-link':target.symlink_to(tmp_path/'private');(tmp_path/'private').write_bytes(b'preserved')
    with pytest.raises((ValueError,OSError)):probe.collect(source,target)
    if case=='output-link':assert (tmp_path/'private').read_bytes()==b'preserved'
    else:assert not target.exists()


def test_append_owner_row_limit_and_lock_contention_refuse_without_wait(tmp_path,monkeypatch):
    probe.append(tmp_path,row());path=tmp_path/probe.FILE_NAME;before=path.read_bytes()
    with monkeypatch.context() as m:
        m.setattr(probe,'MAX_ROW_BYTES',1)
        with pytest.raises(ValueError):probe.append(tmp_path,row())
    with monkeypatch.context() as m:
        m.setattr(os,'geteuid',lambda:path.stat().st_uid+1)
        with pytest.raises(ValueError):probe.append(tmp_path,row())
    import fcntl
    with path.open('rb') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):probe.append(tmp_path,row())
    assert path.read_bytes()==before


def test_durable_phase_survives_stderr_failure_and_diagnostic_failure_never_masks_action(tmp_path,monkeypatch):
    from scripts import workspace_cover_memory_phases as phases, workspace_cover_service_observations as service
    monkeypatch.setattr(service,'require',lambda *a:(tmp_path,'identity','generation'))
    monkeypatch.setattr(phases,'_COUNT',0)
    monkeypatch.setattr(probe,'processes',lambda:{})
    monkeypatch.setattr(probe,'ownership',lambda target:{})
    class Closed:
        def write(self,*args):raise OSError('closed')
        def flush(self):pass
    monkeypatch.setattr(phases.sys,'stderr',Closed())
    error=RuntimeError('original-action')
    def fail():raise error
    owner=SimpleNamespace(call=fail);phases._wrap(owner,'call','original-archive')
    active=phases._ACTIVE.set((tmp_path,'token'))
    try:
        with pytest.raises(RuntimeError) as caught:owner.call()
        assert caught.value is error
        rows=[json.loads(line) for line in (tmp_path/probe.FILE_NAME).read_text().splitlines()]
        assert [r['phase'] for r in rows]==['original-archive:before','original-archive:after']
        monkeypatch.setattr(probe,'append',lambda *a:(_ for _ in ()).throw(RuntimeError('diagnostic')))
        with pytest.raises(RuntimeError) as caught:owner.call()
        assert caught.value is error
    finally:phases._ACTIVE.reset(active)


def test_workflow_only_adds_bounded_always_collection_without_changing_caps_or_commands():
    path=ROOT/'.github/workflows/cover-photo-resources.yml';text=path.read_text()
    line='          set -o pipefail; sudo python3 scripts/workspace_cover_process_observations.py --emit test-artifacts/cover-service-data/cover-memory-phases.jsonl | python scripts/workspace_cover_process_observations.py --receive test-artifacts/cover-service/cover-memory-phases.jsonl\n'
    assert text.count(line)==1
    assert '      - name: Retain final service diagnostics\n        if: always()' in text
    original=text.replace(line,'')
    assert hashlib.sha256(original.encode()).hexdigest()=='ac3a7d457adefb6f675f3a53d85bea0b0d3a9ffc835deaf01c0330f7818b9dfd'
    assert '--memory=512m --memory-swap=512m --cpus=0.5' in original
    assert 'timeout 660 python scripts/qa_cover_recovery_service.py' in original
