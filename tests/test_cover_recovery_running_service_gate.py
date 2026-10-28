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
