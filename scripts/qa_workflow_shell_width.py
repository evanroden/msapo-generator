"""Synthetic native shell, actual workflow changes and delayed adapter acceptance.

Run only in an authorized browser-equipped executor. Fixture contains invented
session state and no report/data imports. Font/device/real-report acceptance is
not claimed. The component gate delays unchanged display code and CSS only.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts' / 'workflow-shell-width'
PORT = 8591
URL = f'http://127.0.0.1:{PORT}'
WIDTHS = (390, 768, 1024, 1440, 1780, 1781, 1920)
CASES = ('po', 'expense', 'monthly-setup', 'monthly-conflict', 'monthly-ready')
FIXTURE = '''import json
from functools import lru_cache
from pathlib import Path
import streamlit as st
from app.web_ui import CUSTOM_CSS
from app import workspace_layout
from app.workspace_layout import workspace, workspace_section, workspace_columns

@lru_cache(maxsize=2)
def delayed_adapter(runtime):
    assets=Path(workspace_layout.__file__).parent
    source='\\n'.join((assets/name).read_text() for name in ('workspace_geometry.js','monthly_report_source_navigation.js','workspace_navigation.js','workspace_layout.js'))
    assert source.count('export default function(component)')==1
    source=source.replace('export default function(component)','function renderWorkspace(component)',1)
    source+=''' + repr('''
export default async function(component) {
 window.__shellAdapterWaiting=true;
 await (window.__shellAdapterGate ||= new Promise(resolve=>{window.__releaseShellAdapter=resolve;}));
 if(!document.querySelector('#synthetic-shell-workspace-style')) {
   const style=document.createElement('style');style.id='synthetic-shell-workspace-style';
   style.textContent=CSS_TEXT;document.head.appendChild(style);
 }
 const cleanup=renderWorkspace(component);window.__shellAdapterReleased=true;return cleanup;
}
''') + '''.replace('CSS_TEXT',json.dumps((assets/'workspace_layout.css').read_text()))
    return st.components.v2.component('synthetic_shell_delayed_adapter',js=source,isolate_styles=False)
workspace_layout._adapter=delayed_adapter

st.set_page_config(layout="wide",initial_sidebar_state="collapsed")
st.markdown(CUSTOM_CSS,unsafe_allow_html=True)
labels=("Purchase order","Expense reimbursement","Monthly report")
label=st.segmented_control("Choose workflow",labels,default="Monthly report",key="workflow_mode",label_visibility="collapsed",width="stretch",required=True)
workflow=("po","expense","monthly")[labels.index(label)]
with st.sidebar: st.write("Synthetic administration")
st.title(label)
phase=st.session_state.setdefault('synthetic_phase','setup')
def phase_to(value): st.session_state['synthetic_phase']=value
state=workflow if workflow!='monthly' else 'monthly-'+phase
st.caption('State: '+state)
if state=='monthly-setup':
    st.text_input("Synthetic report name")
    st.button("Finish synthetic setup",on_click=phase_to,args=('ready',))
elif state=='monthly-conflict':
    st.warning("Synthetic unfinished draft needs review.")
    st.button("Resolve synthetic conflict",on_click=phase_to,args=('ready',))
else:
    with workspace(workflow,"synthetic-shell"):
        with workspace_section("shell","Synthetic section"):
            editor,reference=workspace_columns("shell")
            with editor: st.text_input("Synthetic update")
            with reference: st.write("Synthetic reference")
    if workflow=='monthly': st.button("Show synthetic conflict",on_click=phase_to,args=('conflict',))
'''
OBSERVER = r'''(() => {
 const state={samples:[],overflow:false,epoch:'cold'};window.__shellEvidence=state;
 window.__shellEpoch=label=>{state.epoch=label;};
 function sample(){
  const n=document.querySelector('.block-container');
  const group=document.querySelector('.st-key-workflow_mode [role="radiogroup"]');
  if(n&&group&&group.getBoundingClientRect().width>0){
   const r=n.getBoundingClientRect(),g=group.getBoundingClientRect(),style=getComputedStyle(n);
   const value={epoch:state.epoch,x:r.x,width:r.width,tabX:g.x,tabWidth:g.width,maxWidth:style.maxWidth,
    sidebar:document.querySelector('[data-testid="stSidebar"]')?.getAttribute('aria-expanded'),
    adapter:!!document.querySelector('.epc-workspace'),time:performance.now()};
   const prev=state.samples.at(-1);
   if(!prev||['epoch','x','width','tabX','tabWidth','maxWidth','sidebar','adapter'].some(k=>prev[k]!==value[k])){
    if(state.samples.length>=1024)state.overflow=true;else state.samples.push(value);
   }
  }
  requestAnimationFrame(sample);
 }
 requestAnimationFrame(sample);
})();'''
PROBE = r'''n => {
 const main=document.querySelector('[data-testid="stMain"]'),tabs=document.querySelector('.st-key-workflow_mode [role="radiogroup"]');
 const opener=document.querySelector('[data-testid="stExpandSidebarButton"]');
 const r=opener?.getBoundingClientRect(),t=tabs.getBoundingClientRect();
 const visible=opener&&getComputedStyle(opener).visibility==='visible'&&r.width>0&&r.height>0;
 const overlap=visible?Math.max(0,Math.min(r.right,t.right)-Math.max(r.left,t.left))*Math.max(0,Math.min(r.bottom,t.bottom)-Math.max(r.top,t.top)):0;
 return {box:n.getBoundingClientRect().toJSON(),main:main.getBoundingClientRect().toJSON(),tabs:t.toJSON(),
 maxWidth:getComputedStyle(n).maxWidth,paddingTop:getComputedStyle(n).paddingTop,openerVisible:!!visible,openerOverlap:overlap,
 overflow:document.documentElement.scrollWidth>innerWidth+1};
}'''


def validate_samples(samples, expected):
    assert samples, 'No visible native workflow frame was captured'
    for sample in samples:
        assert sample['maxWidth']=='1680px', sample
        for key in ('x','width','tabX','tabWidth'):
            assert abs(sample[key]-expected[key])<=1, sample


def local_url(url, port=PORT, websocket=False):
    u=urlparse(url)
    return u.scheme==('ws' if websocket else 'http') and u.hostname=='127.0.0.1' and u.port==port and not u.username and not u.password


def run_case(browser,width,output):
    from playwright.sync_api import expect
    context=browser.new_context(viewport={'width':width,'height':1000},service_workers='block')
    context.add_init_script(OBSERVER)
    errors=[];rejected=[];record={'width':width,'states':[]}
    def guard(route):
        if local_url(route.request.url):route.continue_()
        else:rejected.append(route.request.url);route.abort()
    def ws_guard(socket):
        if local_url(socket.url,websocket=True):socket.connect_to_server()
        else:rejected.append(socket.url);socket.close(code=1008,reason='Synthetic loopback only')
    context.route('**/*',guard);context.route_web_socket('**/*',ws_guard)
    context.tracing.start(screenshots=True,snapshots=True,sources=False)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    expected={}
    def snapshot(label,opened=False):
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning',timeout=45000)
        page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        value=page.locator('.block-container').evaluate(PROBE)
        assert value['maxWidth']=='1680px' and not value['overflow'] and value['openerOverlap']==0,value
        assert value['box']['width']<=min(1681,value['main']['width']+1),value
        assert value['paddingTop']==('60px' if width<=1780 else '20px'),value
        expected.setdefault(opened,value)
        for key in ('x','width'):
            assert abs(expected[opened]['box'][key]-value['box'][key])<=1,value
        record['states'].append({'label':label,'sidebar_open':opened,'geometry':value})
        return value
    def switch(label,state,opened=False):
        page.evaluate('(s)=>window.__shellEpoch(s)',state)
        page.get_by_role('radio',name=label,exact=True).click()
        expect(page.get_by_text('State: '+state,exact=True)).to_be_visible()
        snapshot(state,opened)
    try:
        page.goto(URL,wait_until='domcontentloaded')
        expect(page.get_by_text('State: monthly-setup',exact=True)).to_be_visible()
        initial=snapshot('monthly-setup')
        page.evaluate("window.__shellEpoch('setup-to-ready')")
        page.get_by_role('button',name='Finish synthetic setup',exact=True).click()
        page.wait_for_function('window.__shellAdapterWaiting===true')
        expect(page.locator('.epc-workspace')).to_have_count(0)
        before=snapshot('ready-before-adapter')
        page.evaluate('window.__releaseShellAdapter()')
        expect(page.locator('.epc-workspace')).to_have_count(1)
        page.wait_for_function('document.querySelector(".epc-workspace")?.dataset.epcMode')
        after=snapshot('ready-after-adapter')
        assert before['box']==after['box'] or all(abs(before['box'][k]-after['box'][k])<=1 for k in ('x','width')), (before,after)
        for label,state in [('Expense reimbursement','expense'),('Purchase order','po'),('Monthly report','monthly-ready')]:switch(label,state)
        page.evaluate("window.__shellEpoch('conflict')")
        page.get_by_role('button',name='Show synthetic conflict',exact=True).click()
        expect(page.get_by_text('State: monthly-conflict',exact=True)).to_be_visible();snapshot('monthly-conflict')
        page.get_by_role('button',name='Resolve synthetic conflict',exact=True).click()
        expect(page.get_by_text('State: monthly-ready',exact=True)).to_be_visible();snapshot('resolved-ready')
        # Capture every visible frame before native sidebar animation intentionally changes width.
        evidence=page.evaluate('window.__shellEvidence');assert not evidence['overflow']
        validate_samples(evidence['samples'],{'x':initial['box']['x'],'width':initial['box']['width'],
            'tabX':initial['tabs']['x'],'tabWidth':initial['tabs']['width']})
        record['first_visible_and_switch_frames']=evidence
        page.get_by_test_id('stExpandSidebarButton').click()
        expect(page.get_by_test_id('stSidebar')).to_have_attribute('aria-expanded','true')
        page.wait_for_timeout(400);snapshot('sidebar-open',True)
        for label,state in [('Expense reimbursement','expense'),('Purchase order','po'),('Monthly report','monthly-ready')]:switch(label,state,True)
        page.get_by_test_id('stSidebar').hover()
        page.get_by_test_id('stSidebarCollapseButton').get_by_role('button').click()
        expect(page.get_by_test_id('stSidebar')).to_have_attribute('aria-expanded','false')
        page.wait_for_timeout(400);snapshot('sidebar-closed-again')
        assert not errors and not rejected,(errors,rejected)
        record['result']='pass'
    except Exception as e:
        record.update(result='fail',error=str(e));page.screenshot(path=str(output/'failure.png'));raise
    finally:
        record.update(errors=errors,rejected=rejected)
        context.tracing.stop(path=str(output/'trace.zip'));context.close()
        (output/'results.json').write_text(json.dumps(record,indent=2))
    return record


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True);results=[]
    with tempfile.TemporaryDirectory() as tmp,(OUT/'server.log').open('w') as log:
        fixture=Path(tmp)/'fixture.py';fixture.write_text(FIXTURE)
        env={**os.environ,'PYTHONPATH':str(ROOT),'EPC_DATA_DIR':str(Path(tmp)/'data'),'SMARTSHEET_API_MODE':'disabled'}
        process=subprocess.Popen([sys.executable,'-m','streamlit','run',str(fixture),'--server.address=127.0.0.1',f'--server.port={PORT}','--browser.gatherUsageStats=false'],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+45
            while True:
                try:
                    with urlopen(URL+'/_stcore/health',timeout=1) as response:
                        if response.status==200:break
                except OSError:pass
                if time.monotonic()>deadline or process.poll() is not None:raise RuntimeError('Synthetic shell server not ready')
                time.sleep(.1)
            with sync_playwright() as pw:
                for name in ('chromium','webkit'):
                    browser=getattr(pw,name).launch(headless=True)
                    try:
                        for width in WIDTHS:
                            output=OUT/f'{name}-{width}';output.mkdir(exist_ok=True)
                            results.append(run_case(browser,width,output))
                    finally:browser.close()
        finally:
            process.terminate();process.wait(timeout=15);(OUT/'results.json').write_text(json.dumps(results,indent=2))
    assert len(results)==14 and all(r['result']=='pass' for r in results)

if __name__=='__main__':main()
