"""Source regression only; hosted shell geometry remains required."""
import re
from pathlib import Path
from app.web_ui import CUSTOM_CSS

ROOT = Path(__file__).parents[1]


def test_shared_shell_width_precedes_workspace_and_preserves_gutters():
    css = re.sub(r'/\*.*?\*/', '', CUSTOM_CSS, flags=re.S)
    block = css.split('\n    .block-container {', 1)[1].split('}', 1)[0]
    assert 'max-width: 1680px !important;' in block
    for side in ('left', 'right'):
        assert f'padding-{side}: max(1rem, env(safe-area-inset-{side})) !important;' in block
    assert '1000px' not in block
    source = (ROOT / 'app/web_ui.py').read_text()
    assert source.index('st.markdown(CUSTOM_CSS, unsafe_allow_html=True)') < source.index('st.segmented_control(')


def test_workspace_mount_and_mode_never_resize_the_outer_shell():
    for filename in ('workspace_layout.css', 'workspace_initial.css'):
        css = re.sub(r'/\*.*?\*/', '', (ROOT / 'app' / filename).read_text(), flags=re.S)
        assert not re.search(r'(?:stMainBlockContainer|\.block-container)[^{]*\{[^}]*max-width', css)
    css = (ROOT / 'app/workspace_layout.css').read_text()
    assert 'grid-template-columns:minmax(0,1.12fr) minmax(0,1fr)' in css
    assert '[data-epc-mode="compact"] .epc-workspace-row {grid-template-columns:minmax(0,1fr);}' in css
    assert '[data-epc-mode="book"]' in css and '[data-epc-mode="tabletop"]' in css


def test_browser_matrix_covers_requested_states_and_sidebar_boundary():
    from scripts.qa_workflow_shell_width import WIDTHS, CASES, FIXTURE
    assert WIDTHS == (390, 768, 1024, 1440, 1780, 1781, 1920)
    assert set(CASES) == {'po', 'expense', 'monthly-setup', 'monthly-conflict', 'monthly-ready'}
    compile(FIXTURE, 'synthetic-shell-fixture', 'exec')
    assert 'label=st.segmented_control' in FIXTURE
    assert 'on_click=phase_to' in FIXTURE
    assert 'window.__shellAdapterGate' in FIXTURE
    assert 'monthly_report_library' not in FIXTURE


def test_frame_gate_rejects_wrong_width_and_a_late_width_change():
    import pytest
    from scripts.qa_workflow_shell_width import validate_samples
    good={'openerOverlap':0,'maxWidth':'1680px','width':1440,'x':0,'tabX':16,'tabWidth':1408}
    validate_samples([good,dict(good),{**good,'maxWidth':'none'}],good)
    for samples in ([],[{**good,'maxWidth':'1000px','width':1000}],
                    [good,{**good,'width':1000}], [good,{**good,'maxWidth':'none','width':1000}],
                    [good,{**good,'maxWidth':'none','width':1920}], [good,{**good,'x':20}], [good,{**good,'openerOverlap':1}],
                    [good,{**good,'tabX':30}], [good,{**good,'tabWidth':1380}]):
        with pytest.raises(AssertionError):validate_samples(samples,good)


def test_browser_network_boundary_is_exact_loopback_only():
    from scripts.qa_workflow_shell_width import local_url
    assert local_url('http://127.0.0.1:8591/media/test')
    assert local_url('ws://127.0.0.1:8591/_stcore/stream',websocket=True)
    assert local_url('blob:http://127.0.0.1:8591/d7d4c664-daf7-45cc-a084-ee86312a68c0')
    for value in ('http://127.0.0.1:8592/','http://user@127.0.0.1:8591/',
                  'https://example.com/','file:///tmp/a','data:text/html,test',
                  'http://127.0.0.1.evil:8591/',
                  'blob:http://evil.example/d7d4c664-daf7-45cc-a084-ee86312a68c0',
                  'blob:http://127.0.0.1:8592/d7d4c664-daf7-45cc-a084-ee86312a68c0',
                  'blob:http://127.0.0.1:8591/not-a-blob-id'):
        assert not local_url(value)


def test_hosted_shell_job_is_separate_mandatory_and_bounded():
    workflow=(ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    job=workflow.split('\n  workflow-shell-width:\n',1)[1]
    assert 'timeout-minutes: 50' in job and 'timeout-minutes: 20' in job
    assert 'timeout-minutes: 26' in job and 'timeout-minutes: 3' in job
    assert "ci_native_test_budget.py --minutes 25 <<'NATIVE_TEST'" in job
    assert 'python scripts/qa_workflow_shell_width.py' in job
    assert 'continue-on-error' not in job
    assert 'if:' not in job.split('      - name: Retain first shell-width',1)[0]
    assert 'if: always()' in job
    for path in ('scripts/qa_workflow_shell_width.py','tests/test_workflow_shell_width.py'):
        assert workflow.count("      - '"+path+"'")==2


def test_existing_adaptive_fixture_uses_production_shell_before_workspace():
    fixture=(ROOT/'tests/fixtures/workspaces/app.py').read_text()
    assert 'from app.web_ui import CUSTOM_CSS' in fixture
    assert fixture.index('st.markdown(CUSTOM_CSS, unsafe_allow_html=True)') < fixture.index("with workspace(")
    assert 'max-width:1000px' not in fixture


def test_static_shell_style_is_single_sourced_early_idempotent_and_fail_closed(tmp_path,monkeypatch):
    import pytest
    from scripts import patch_streamlit_metadata as metadata
    css=(ROOT/'app/workflow_shell.css').read_text()
    assert css in CUSTOM_CSS
    index=tmp_path/'index.html'
    index.write_text('<html><head><meta charset="UTF-8"><title>Streamlit</title><script type="module" src="app.js"></script></head><body></body></html>')
    metadata.patch_index(index)
    first=index.read_text()
    assert first.count('id="process-control-workflow-shell"')==1
    assert first.index(css)<first.index('<script')
    assert first.index('charset')<1024
    metadata.patch_index(index)
    assert index.read_text()==first
    invalid=tmp_path/'invalid.css'
    monkeypatch.setattr(metadata,'_SHELL_CSS_PATH',invalid)
    for content in (None,'','</style><script>alert(1)</script>'):
        if content is not None:invalid.write_text(content)
        with pytest.raises(RuntimeError):metadata.patch_index(index)
        assert index.read_text()==first


def test_static_shell_survives_locked_frontend_date_publication(tmp_path):
    import json
    from hashlib import sha256
    import streamlit
    from scripts import patch_streamlit_metadata as metadata
    from scripts import patch_streamlit_frontend as frontend
    from scripts import patch_streamlit_date_input as date
    from streamlit_static_fixture import pristine_html
    installed=Path(streamlit.__file__).parent/'static'
    target=tmp_path/'static/js';target.mkdir(parents=True)
    members={**json.loads(frontend.MANIFEST_PATH.read_bytes())['members'],
             **json.loads(frontend.FLOATING_MANIFEST_PATH.read_bytes())['members']}
    for name,record in members.items():
        raw=(installed/'static/js'/name).read_bytes()
        assert sha256(raw).hexdigest()==record['sha256']
        (target/name).write_bytes(raw)
    index=tmp_path/'index.html';index.write_bytes(pristine_html(installed))
    metadata.patch_index(index)
    frontend.patch_bundle(tmp_path,installed_version='1.61.1')
    date.patch_bundle(tmp_path,installed_version='1.61.1')
    css=(ROOT/'app/workflow_shell.css').read_text()
    first=index.read_text()
    assert first.count('id="process-control-workflow-shell"')==1 and css in first
    assert first.index(css)<first.index('<script')
    assert first.index('charset')<1024
    metadata.patch_index(index)
    frontend.patch_bundle(tmp_path,installed_version='1.61.1')
    date.patch_bundle(tmp_path,installed_version='1.61.1')
    assert index.read_text()==first


def test_full_state_sidebar_matrix_cannot_pass_with_missing_setup_or_conflict():
    import pytest
    from scripts.qa_workflow_shell_width import CASES,validate_state_coverage
    states=[{'state':state,'sidebar_open':opened} for state in CASES for opened in (False,True)]
    validate_state_coverage(states)
    for missing in ('monthly-setup','monthly-conflict'):
        with pytest.raises(AssertionError):
            validate_state_coverage([row for row in states if not (row['state']==missing and row['sidebar_open'])])


def test_native_measurement_rejects_placeholders_stale_and_wrong_owners():
    """Execute the actual browser predicate without starting a browser."""
    import json
    import subprocess
    from scripts.qa_workflow_shell_width import NATIVE_READINESS
    script = r'''
const assert=require('node:assert/strict');
class Node {
 constructor(text=''){this.textContent=text;this.attrs={};this.children=[];this.stale=false;this.visible=true;}
 getBoundingClientRect(){return {width:this.visible?100:0,height:20};}
 getAttribute(k){return this.attrs[k]??null;}
 contains(n){return this.children.includes(n)||this.children.some(c=>c.contains(n));}
 closest(){return this.stale?this:null;}
 querySelectorAll(s){return this.queries?.[s]??[];}
}
const app=new Node(),main=new Node(),shell=new Node(),owner=new Node(),group=new Node();
const radios=['Purchase order','Expense reimbursement','Monthly report'].map(x=>new Node(x));
radios[2].attrs['aria-checked']='true';
const caption=new Node('State: monthly-setup');
app.attrs['data-test-script-state']='notRunning';
main.children=[shell];shell.children=[owner];owner.children=[group];
group.queries={'[role="radio"]':radios};main.queries={'[data-testid="stCaptionContainer"]':[caption]};
const nodes={'[data-testid="stApp"]':[app],'[data-testid="stMain"]':[main],'.block-container':[shell],
 '.st-key-workflow_mode':[owner],'.st-key-workflow_mode [role="radiogroup"]':[], '[data-testid="stSkeleton"]':[new Node()]};
global.document={querySelectorAll:s=>nodes[s]??[]};
global.getComputedStyle=()=>({visibility:'visible',display:'block'});
const probe=PROBE;
assert.equal(probe('monthly-setup').ready,false); // null / skeleton is not native readiness
assert.equal(probe('monthly-setup').skeletonCount,1);
nodes['.st-key-workflow_mode [role="radiogroup"]']=[group];
assert.equal(probe('monthly-setup').ready,true);
assert.equal(probe('po').ready,false); // wrong selected native workflow
assert.equal(probe('monthly-ready').ready,false); // stale phase caption
assert.equal(probe('unknown').ready,false);
owner.stale=true;assert.equal(probe('monthly-setup').ready,false);owner.stale=false;
shell.children=[];assert.equal(probe('monthly-setup').ready,false);shell.children=[owner];
nodes['.st-key-workflow_mode'].push(new Node());assert.equal(probe('monthly-setup').ready,false);nodes['.st-key-workflow_mode'].pop();
caption.stale=true;assert.equal(probe('monthly-setup').ready,false);caption.stale=false;
app.attrs['data-test-script-state']='running';assert.equal(probe('monthly-setup').ready,false);
app.attrs['data-test-script-state']='notRunning';group.visible=false;assert.equal(probe('monthly-setup').ready,false);
group.visible=true;assert.equal(probe('monthly-setup').ready,true);
'''.replace('const probe=PROBE;', 'const probe='+NATIVE_READINESS+';')
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_measurement_mount_wait_shares_idle_deadline_and_retains_timing():
    from scripts.qa_workflow_shell_width import wait_native_measurement
    calls=[]
    class Handle:
        def json_value(self):return {'ready':True,'at':150}
        def dispose(self):calls.append('dispose')
    class Page:
        def get_by_test_id(self,name):return self
        def to_have_attribute(self,*args,**kwargs):calls.append(('idle',kwargs['timeout']))
        def evaluate(self,js,*args):
            if args:
                if not any(isinstance(x,tuple) and x[0]=='wait' for x in calls):
                    return {'ready':False,'at':100,'groupCount':0,'skeletonCount':4}
                return {'ready':True,'at':151}
            calls.append('two-frames')
        def wait_for_function(self,js,**kwargs):
            calls.append(('wait',kwargs['timeout'],kwargs['arg']))
            assert 'r.ready ? r : false' in js
            return Handle()
    times=iter([0,1,3,4,5]);evidence={}
    wait_native_measurement(Page(),'monthly-setup',evidence,lambda x:x,clock=lambda:next(times))
    assert calls==[('idle',44000),('wait',42000,'monthly-setup'),'dispose','two-frames']
    assert evidence['initial_after_backend_idle']['skeletonCount']==4
    assert evidence['backend_idle_to_native_ready_ms']==50


def test_measurement_expired_or_replaced_owner_never_authorizes_geometry():
    import pytest
    from scripts.qa_workflow_shell_width import wait_native_measurement
    class Page:
        def get_by_test_id(self,name):return self
        def to_have_attribute(self,*args,**kwargs):pass
        def evaluate(self,js,*args):return {'ready':False,'at':100}
        def wait_for_function(self,*args,**kwargs):return self
        def json_value(self):return {'ready':True,'at':150}
        def dispose(self):pass
    times=iter([0,46])
    with pytest.raises(TimeoutError):
        wait_native_measurement(Page(),'monthly-ready',{},lambda x:x,clock=lambda:next(times))
    with pytest.raises(AssertionError,match='owner changed'):
        wait_native_measurement(Page(),'monthly-ready',{},lambda x:x,clock=lambda:0)


def test_measurement_late_final_owner_evaluation_cannot_admit_geometry():
    import pytest
    from scripts.qa_workflow_shell_width import wait_native_measurement
    class Page:
        def get_by_test_id(self,name):return self
        def to_have_attribute(self,*args,**kwargs):pass
        def evaluate(self,js,*args):return {'ready':True,'at':100}
        def wait_for_function(self,*args,**kwargs):return self
        def json_value(self):return {'ready':True,'at':150}
        def dispose(self):pass
    times=iter([0,1,2,3,46])
    with pytest.raises(TimeoutError):
        wait_native_measurement(Page(),'monthly-ready',{},lambda x:x,clock=lambda:next(times))
