from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import pytest
from scripts.qa_cover_recovery_service import assert_resources, unchanged, same_content, MIB


def measurement():
    return {'memory.max':str(512*MIB),'memory.swap.max':'0','cpu.max':'50000 100000',
            'memory.peak':str(400*MIB),'memory.events':'low 0\nhigh 0\nmax 0\noom 0\noom_kill 0'}


def test_real_gate_checks_memory_swap_cpu_and_child_oom():
    assert_resources(measurement())
    for key,value in (('memory.max',str(1024*MIB)),('memory.swap.max','1'),
                      ('cpu.max','100000 100000'),('memory.peak',str(513*MIB)),
                      ('memory.events','oom 1\noom_kill 0'),('memory.events','oom 0\noom_kill 1')):
        bad=measurement();bad[key]=value
        with pytest.raises(AssertionError):assert_resources(bad)
    bad=measurement();bad.pop('memory.events')
    with pytest.raises(KeyError):assert_resources(bad)


def test_storage_allowances_are_exact_source_and_profile_not_directory_wildcard():
    from app import monthly_report_qa_fixture as fixture,monthly_report_library as library
    token='a'*32;digest=sha256(b'original').hexdigest()
    profile=Path('library')/library._contract_directory(fixture.CONTRACT)/fixture.profile().key
    original=str(profile/'cover-originals'/(digest+'.original'))
    before={'snapshots/old.json':[1,2,'old'],'library/other/profile/original':[2,3,'other']}
    after={**before,original:[8,3,digest]}
    unchanged(before,after,token=token,original_digest=digest)
    for mutation in ('other-original','other-profile','old-history','lost-source','bad-original'):
        bad=deepcopy(after)
        if mutation=='other-original':bad[str(profile/'cover-originals'/('b'*64+'.original'))]=[1,2,'b'*64]
        if mutation=='other-profile':bad['library/other/profile/cover-originals/'+digest+'.original']=[8,3,digest]
        if mutation=='old-history':bad['snapshots/old.json']=[1,3,'old']
        if mutation=='lost-source':bad.pop('library/other/profile/original')
        if mutation=='bad-original':bad[original]=[8,3,'wrong']
        with pytest.raises(AssertionError):unchanged(before,bad,token=token,original_digest=digest)


def test_content_checks_include_sources_history_and_chosen_art():
    state={'working':{'fingerprint':'old','cover':{'asset_hashes':['old.jpg']},'sources':['source']},
           'versions':[[1,'when']],'revision':1}
    same_content(state,deepcopy(state))
    for field in ('fingerprint','cover','sources'):
        bad=deepcopy(state);bad['working'][field]=None
        with pytest.raises(AssertionError):same_content(state,bad)


def test_fixture_hook_refuses_unmarked_environment_before_reading_namespace(monkeypatch,tmp_path):
    from scripts.workspace_cover_service_observations import require
    monkeypatch.delenv('EPC_MONTHLY_COVER_SERVICE_TASK',raising=False)
    with pytest.raises(ValueError,match='marked isolated fixture'):require(tmp_path,'a'*32)


def test_hosted_gate_never_uses_state_priming_or_starts_local_server():
    text=Path('scripts/qa_cover_recovery_service.py').read_text()
    assert 'set_input_files(' in text and 'sync_playwright()' in text
    assert 'streamlit run' not in text and 'AppTest' not in text
    assert 'session_state' not in text and 'memory_headroom =' not in text
    workflow=Path('.github/workflows/cover-photo-resources.yml').read_text()
    assert 'cover-recovery-running-service:' in workflow
    assert '--memory=512m --memory-swap=512m --cpus=0.5' in workflow
    assert 'EPC_MONTHLY_DOM_APPTEST' not in workflow
    assert 'run_case report-slot-retry large.jpg 2 success --slot-retry' in workflow
    assert 'recover_case isolated --kind isolated --expect success' in workflow


def test_marked_real_fixture_receipt_and_control_are_bounded_read_only(tmp_path):
    """AppTest fixture check only, not browser/cgroup acceptance."""
    import os, subprocess, sys
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    script=r'''
import json,re,sys
from html import unescape
from pathlib import Path
from streamlit.testing.v1 import AppTest
from scripts.workspace_history_observations import storage_state
from app import monthly_report_section_preview_ui as preview
preview.render_section_preview=lambda *a,**kw:None
base=Path(sys.argv[1]);token='d'*32
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py',default_timeout=30)
app.session_state['_monthly_dom_app_test_token']=token
app.run();assert not app.exception,[x.message for x in app.exception]
next(b for b in app.button if b.label=='Load known-value report').click().run()
assert not app.exception,[x.message for x in app.exception]
def receipt():
 node=next(x.proto.body for x in app.get('html') if 'data-cover-service-receipt=' in x.proto.body)
 return json.loads(unescape(re.search('data-cover-service-receipt="([^"]+)"',node)[1]))
old=receipt();before=storage_state(base,token)
next(b for b in app.button if b.label=='QA refresh cover service receipt').click().run()
assert not app.exception
assert receipt()['sequence']>old['sequence'] and receipt()['working']==old['working']
assert storage_state(base,token)==before
assert old['revision']==1 and old['working']==old['durable']
next(b for b in app.button if b.label=='QA hold real report work slot for 15 seconds').click().run()
assert not app.exception,[x.message for x in app.exception]
assert any(c.value=='QA controlled contention active: true' for c in app.caption)
new=receipt();assert new['working']==old['working'] and new['versions']==old['versions']
assert storage_state(base,token)==before
next(b for b in app.button if b.label=='QA release controlled report contention').click().run()
assert not app.exception,[x.message for x in app.exception]
assert any(c.value=='QA controlled contention active: false' for c in app.caption)
assert storage_state(base,token)==before
assert not (base/'monthly_reports').exists()
'''
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],capture_output=True,text=True,timeout=90,
        env={**os.environ,'EPC_DATA_DIR':str(tmp_path),'EPC_MONTHLY_DOM_FIXTURE':'1',
             'EPC_MONTHLY_COVER_SERVICE_TASK':'1','EPC_MONTHLY_DOM_APPTEST':'1',
             'ANTHROPIC_API_KEY':'','SMARTSHEET_API_MODE':'disabled'})
    assert result.returncode==0,result.stdout+'\n'+result.stderr[-6000:]


def test_rendered_art_assertion_uses_independent_source_visual_signature():
    from io import BytesIO
    from PIL import Image
    from scripts.qa_cover_recovery_service import synthetic_photo,assert_visible_last_good
    raw=synthetic_photo(0)
    assert assert_visible_last_good(raw)['matching_pixels'][0]>100
    with Image.open(BytesIO(raw)) as art:
        for altered in (Image.new('RGB',art.size,'white'),art.transpose(Image.Transpose.FLIP_LEFT_RIGHT)):
            stream=BytesIO();altered.save(stream,'PNG')
            with pytest.raises(AssertionError):assert_visible_last_good(stream.getvalue())
        # Rasterization/JPEG tolerance must not hide removal or wrong ordering.
        stream=BytesIO();art.save(stream,'JPEG',quality=82)
        assert_visible_last_good(stream.getvalue())


@pytest.fixture
def browser_errors(monkeypatch):
    # Pure protocol tests do not install or launch a local browser. The hosted
    # native gate uses the actual Playwright package installed by its workflow.
    import sys
    from types import ModuleType
    module=ModuleType('playwright.sync_api')
    class BrowserError(Exception):pass
    class BrowserTimeout(BrowserError):pass
    module.Error=BrowserError;module.TimeoutError=BrowserTimeout
    monkeypatch.setitem(sys.modules,'playwright.sync_api',module)
    return BrowserTimeout


@pytest.mark.parametrize('raw,expected', [
    ('{"working":{"request":{"status":"pending"}},"durable":{"request":null}}','pending'),
    ('x'*32769,'unavailable'),
    ('not json','unavailable'),
    (None,'unavailable'),
    ('{"x":'+'['*16000+'0'+']'*16000+'}','unavailable'),
], ids=['receipt','oversize','malformed','absent','deeply-nested'])
def test_timeout_diagnostic_is_bounded_read_only_and_keeps_original_failure(raw,expected,capsys,browser_errors):
    BrowserTimeout=browser_errors
    from scripts.qa_cover_recovery_service import wait, RECEIPT
    error=BrowserTimeout('original wait failure')
    class Page:
        last=property(lambda self:self)
        def wait_for_function(self,*args,**kwargs):
            assert kwargs['timeout']==120000
            raise error
        def locator(self,selector):
            assert selector==RECEIPT
            return self
        def get_attribute(self,name,**kwargs):
            assert name=='data-cover-service-receipt' and kwargs['timeout']==1000
            return raw
    with pytest.raises(BrowserTimeout) as caught:wait(Page())
    assert caught.value is error
    printed=capsys.readouterr().out
    assert expected in printed
    assert len(printed.encode())<33000
    assert 'x'*100 not in printed


def test_timeout_diagnostic_read_failure_does_not_mask_original(capsys,browser_errors):
    BrowserTimeout=browser_errors
    from scripts.qa_cover_recovery_service import wait
    error=BrowserTimeout('original')
    class Page:
        def wait_for_function(self,*a,**kw):raise error
        def locator(self,*a):raise BrowserTimeout('receipt unreachable')
    with pytest.raises(BrowserTimeout) as caught:wait(Page())
    assert caught.value is error
    assert 'unavailable' in capsys.readouterr().out


@pytest.mark.parametrize('mutation',[None,'wrong-hash','wrong-size','wrong-reference','other-profile','extra-object','changed-existing','absent-library'])
def test_only_exact_existing_last_good_art_may_be_copied_to_private_journal(mutation):
    from app import monthly_report_qa_fixture as fixture,monthly_report_library as library
    token='a'*32;digest=sha256(b'corrupt original').hexdigest();picture='1'*64+'.jpg'
    profile=Path('library')/library._contract_directory(fixture.CONTRACT)/fixture.profile().key
    journal=Path('active_work')/sha256(token.encode()).hexdigest()/library._contract_directory(fixture.CONTRACT)/fixture.profile().key/fixture.PERIOD.key
    shared=str(profile/'assets'/picture);copy=str(journal/'assets'/picture)
    original=str(profile/'cover-originals'/(digest+'.original'))
    before={shared:[42,100,'1'*64],'snapshots/immutable.json':[10,80,'saved']}
    after={**deepcopy(before),copy:[42,200,'1'*64],original:[16,200,digest]}
    if mutation=='wrong-hash':after[copy][2]='2'*64
    if mutation=='wrong-size':after[copy][0]=43
    if mutation=='wrong-reference':after[str(journal/'assets'/('2'*64+'.jpg'))]=after.pop(copy)
    if mutation=='other-profile':after[str(journal.parent.parent/'other'/fixture.PERIOD.key/'assets'/picture)]=after.pop(copy)
    if mutation=='extra-object':after['objects/11/'+'1'*64]=[42,200,'1'*64]
    if mutation=='changed-existing':after[shared][1]+=1
    if mutation=='absent-library':before.pop(shared);after.pop(shared)
    def check():unchanged(before,after,token=token,original_digest=digest,last_good_reference=picture)
    if mutation is None:check()
    else:
        with pytest.raises(AssertionError):check()


@pytest.mark.parametrize('name',['.conversion-lock','.active-office.json'])
def test_only_exact_valid_runtime_bookkeeping_is_outside_content_inventory(tmp_path,name):
    import os
    from scripts.qa_cover_recovery_service import runtime_bookkeeping
    root=tmp_path/'monthly_reports';folder=root/'render-jobs';folder.mkdir(parents=True)
    path=folder/name
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+os.readlink('/proc/self/ns/pid')
    raw=b'' if name=='.conversion-lock' else __import__('json').dumps({'pid':os.getpid(),'boot':boot}).encode()
    path.write_bytes(raw)
    assert runtime_bookkeeping(root,path)
    # Renderer state can be created/updated/removed without changing report content.
    if name=='.active-office.json':
        path.write_text(__import__('json').dumps({'pid':os.getpid()+1,'boot':boot}))
        assert runtime_bookkeeping(root,path)
    path.unlink()
    assert runtime_bookkeeping(root,path)
    unknown=folder/'other.json';unknown.write_bytes(raw)
    assert not runtime_bookkeeping(root,unknown)
    other=root/'library'/'render-jobs';other.mkdir(parents=True)
    wrong=other/name;wrong.write_bytes(raw)
    assert not runtime_bookkeeping(root,wrong)


@pytest.mark.parametrize('mutation',['malformed','oversize','symlink','hardlink','fifo','parent-link','wrong-boot','extra-key','boolean-pid','lock-content'])
def test_runtime_bookkeeping_never_hides_invalid_or_linked_files(tmp_path,mutation):
    import os,json
    from scripts.qa_cover_recovery_service import runtime_bookkeeping
    root=tmp_path/'monthly_reports';folder=root/'render-jobs';folder.mkdir(parents=True)
    path=folder/('.conversion-lock' if mutation=='lock-content' else '.active-office.json')
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+os.readlink('/proc/self/ns/pid')
    value={'pid':os.getpid(),'boot':boot}
    path.write_text(json.dumps(value))
    if mutation=='malformed':path.write_text('{')
    if mutation=='oversize':path.write_bytes(b'x'*1025)
    if mutation=='symlink':
        path.unlink();path.symlink_to(tmp_path/'elsewhere')
    if mutation=='hardlink':os.link(path,tmp_path/'alias')
    if mutation=='fifo':path.unlink();os.mkfifo(path)
    if mutation=='parent-link':
        folder.rename(root/'real');folder.symlink_to(root/'real',target_is_directory=True)
    if mutation=='wrong-boot':value['boot']='other';path.write_text(json.dumps(value))
    if mutation=='extra-key':value['data']='unexpected';path.write_text(json.dumps(value))
    if mutation=='boolean-pid':value['pid']=True;path.write_text(json.dumps(value))
    with pytest.raises((AssertionError,ValueError,OSError)):
        runtime_bookkeeping(root,path)


@pytest.mark.parametrize("busy_seconds,success", [(0.5,True),(7,False)])
def test_fixture_real_contention_acquisition_waits_boundedly_and_never_leaks(monkeypatch,tmp_path,busy_seconds,success):
    import sys,time,threading
    from scripts import workspace_cover_service_observations as fixture
    from app.monthly_report_render_jobs import work_slot
    import streamlit as st
    key='_cover_service_qa_contention'
    monkeypatch.delattr(sys,key,raising=False)
    monkeypatch.setattr(fixture,'require',lambda *a:None)
    captions=[]
    monkeypatch.setattr(st,'button',lambda label:label=='QA hold real report work slot for 15 seconds')
    monkeypatch.setattr(st,'caption',captions.append)
    entered=threading.Event();release=threading.Event()
    def preview():
        with work_slot(wait_seconds=0):
            entered.set();release.wait(busy_seconds)
    prior=threading.Thread(target=preview);prior.start();assert entered.wait(2)
    start=time.monotonic()
    try:
        if success:
            fixture.contention_controls(tmp_path,'a'*32)
            elapsed=time.monotonic()-start
            assert .4<=elapsed<3
            held=getattr(sys,key)
            assert held['acquired'] and held['thread'].is_alive()
            assert 'QA controlled contention active: true' in captions
            assert 13<held['deadline']-time.monotonic()<=15
        else:
            with pytest.raises(ValueError,match='did not acquire'):
                fixture.contention_controls(tmp_path,'a'*32)
            elapsed=time.monotonic()-start
            assert 4.5<=elapsed<7
            held=getattr(sys,key)
            assert not held['acquired'] and held['release'].is_set()
            assert not held['thread'].is_alive()
            assert 'QA controlled contention active: true' not in captions
    finally:
        release.set();prior.join(2)
        held=getattr(sys,key,None)
        if held:held['release'].set();held['thread'].join(2)
        if hasattr(sys,key):delattr(sys,key)
    with work_slot(wait_seconds=0):pass


def test_fixture_setup_ack_timeout_releases_real_holder(monkeypatch,tmp_path):
    import sys,threading
    from scripts import workspace_cover_service_observations as fixture
    from app.monthly_report_render_jobs import work_slot
    import streamlit as st
    key='_cover_service_qa_contention'
    monkeypatch.delattr(sys,key,raising=False)
    monkeypatch.setattr(fixture,'require',lambda *a:None)
    monkeypatch.setattr(st,'button',lambda label:label=='QA hold real report work slot for 15 seconds')
    class LostAck(threading.Event):
        def wait(self,timeout=None):
            assert timeout==7
            assert super().wait(2)
            return False
    events=iter([LostAck(),threading.Event()])
    monkeypatch.setattr(fixture,'Event',lambda:next(events))
    try:
        with pytest.raises(ValueError,match='did not acquire'):
            fixture.contention_controls(tmp_path,'a'*32)
        held=getattr(sys,key)
        assert held['release'].is_set() and not held['thread'].is_alive()
        with work_slot(wait_seconds=0):pass
    finally:
        held=getattr(sys,key,None)
        if held:held['release'].set();held['thread'].join(2)
        if hasattr(sys,key):delattr(sys,key)
