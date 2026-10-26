"""Observe the remaining pre-adapter reload shift in a disposable local report.

Diagnosis only: no forced click, retry, or state repair. Product files are
unchanged from the parent revision that includes the period loading repair. Stop at
the first failed press and retain its component geometry and native trace.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_about_logo_refresh as logo
from scripts.workspace_wire_observations import WireObservations

OUT = ROOT / 'test-artifacts/monthly-first-paint-diagnostic'

CLIENT = r"""(() => {
  if(location.hostname !== '127.0.0.1' || location.port !== '8546') return;
  const ids = new WeakMap(); let next = 0, frame = null, held = false;
  const id = n => {if (!ids.has(n)) ids.set(n, ++next); return ids.get(n)};
  const describe = n => n?.tagName ? {id:id(n), tag:n.tagName,
    testid:n.dataset.testid || '', key:[...n.classList].find(c=>c.startsWith('st-key-')) || ''} : null;
  const button = () => [...document.querySelectorAll('button')].find(
    n=>n.textContent === 'Render synthetic native logo outputs');
  const rect = n => {const r=n.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};
  const snapshot = () => {
    const main = document.querySelector('[data-testid="stMain"]');
    return {at:performance.now(),scroll:main?.scrollTop,scrollHeight:main?.scrollHeight,
      clientHeight:main?.clientHeight,button:button()?rect(button()):null,
      mode:document.querySelector('.st-key-epc_workspace_monthly')?.dataset.epcMode || null,
      running:document.querySelector('[data-testid="stApp"]')?.dataset.testScriptState,
      focused:describe(document.activeElement),
      nodes:[...document.querySelectorAll('[data-testid="stElementContainer"], [data-testid="stVerticalBlock"], [data-testid="stHorizontalBlock"], [data-testid="stColumn"]')]
        .slice(0,1500).map(n=>({...describe(n),parent:describe(n.parentElement),...rect(n),
          component:n.querySelector('.stBidiComponent') ? 'v2' : '',
          slot:!!n.querySelector('[class*="st-key-epc_preview_slot_"]')}))};
  };
  let events=[], samples=[], previous='';
  function sample() {
    frame=null;
    if (!held || samples.length>=90) return;
    const value=snapshot();
    const signature=JSON.stringify({...value,at:0});
    if(signature!==previous){samples.push(value);previous=signature;}
    frame=requestAnimationFrame(sample);
  }
  for(const type of ['pointerdown','pointerup','click','focusin','scroll']) {
    document.addEventListener(type,event=>{
      if(type==='pointerdown' && (event.target===button() || button()?.contains(event.target))){
        held=true;sample();
      }
      if(!held)return;
      events.push({type,trusted:event.isTrusted,target:describe(event.target),
        action:describe(event.target?.closest?.('button')),
        x:event.clientX,y:event.clientY,...snapshot()});
      if(type==='click') {held=false;if(frame!==null)cancelAnimationFrame(frame);}
    },{capture:true,passive:true});
  }
  window.__firstPaintEvidence=()=>({events,samples});
})();"""


def exercise(playwright, base):
    from playwright.sync_api import expect
    logo.expect = expect
    browser = playwright.webkit.launch(headless=True)
    context = browser.new_context(viewport={'width':1365,'height':900}, accept_downloads=True)
    token = secrets.token_hex(16)
    context.add_cookies([{'name':'epc_device_id','value':token,'url':logo.URL}])
    external=[]
    def route(request):
        target=urlparse(request.request.url)
        if target.scheme in ('data','blob') or (target.hostname=='127.0.0.1' and target.port==8546):
            request.continue_()
        else:
            external.append(target.hostname);request.abort()
    context.route('**/*',route)
    context.add_init_script(CLIENT)
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page()
    page.set_default_timeout(30000)
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    wire=WireObservations(8546);wire.attach(page)
    report={'synthetic_only':True,'physical_device':False,'tested_checkout':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'cases':[],'errors':errors,'external':external}
    try:
        page.goto(logo.URL+'/?workflow=monthly&logo_mode=custom')
        page.get_by_role('button',name='Create synthetic custom logo report',exact=True).click()
        original=logo.wait_state(page)
        protected=logo.protected_files(base,token)
        logo.about(page).get_by_role('button',name='Use this logo in this report',exact=True).click()
        logo.wait_state(page,company=True,after=original['sequence'])
        for index in range(100):
            context.tracing.start_chunk()
            page.reload()
            before=logo.wait_state(page,company=True,scope=original['scope'],generation=original['generation'])
            boundary=wire.sequence
            action=page.get_by_role('button',name='Render synthetic native logo outputs',exact=True)
            # A single ordinary held native press, matching the measured
            # 255–363 ms failure window. No input is replayed on failure.
            action.click(delay=300)
            evidence=page.evaluate('window.__firstPaintEvidence()')
            events=evidence['events']
            down=next((e for e in events if e['type']=='pointerdown'),None)
            up=next((e for e in events if e['type']=='pointerup'),None)
            click=next((e for e in events if e['type']=='click'),None)
            record={'case':index,'down':down,'up':up,'click':click,'samples':evidence['samples'],
                    'wire': [e for e in wire.events if e['sequence']>boundary]}
            report['cases'].append(record)
            if not down or not up or not click or not down['action'] or down['action']!=up['action'] or down['action']!=click['action']:
                raise AssertionError('Native press target changed: case '+str(index))
            logo.wait_state(page,company=True,after=before['sequence'],scope=before['scope'],generation=before['generation'])
            assert logo.protected_files(base,token)==protected
            assert not errors and not external
            # Preserve full geometry for the first failure only. Stable cases
            # retain pointer targets, scroll and timing without repeated DOMs.
            for event in (record['down'],record['up'],record['click']):
                event.pop('nodes',None)
            record['samples']=[{key:value for key,value in sample.items() if key!='nodes'}
                               for sample in record['samples']]
            context.tracing.stop_chunk()
            print('Stable press',index,flush=True)
    except Exception as error:
        report['failure']=str(error)
        page.screenshot(path=str(OUT/'first-failure.png'))
        (OUT/'first-failure.html').write_text(page.content())
        context.tracing.stop_chunk(path=str(OUT/'first-failure-trace.zip'))
        raise
    finally:
        (OUT/'results.json').write_text(json.dumps(report,indent=2))
        context.close();browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='monthly-first-paint-') as temp, ExitStack() as controller:
        base=Path(temp)
        (base/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        controller.enter_context(logo.controller_environment(base))
        env=dict(os.environ,EPC_DATA_DIR=temp,EPC_MONTHLY_DOM_FIXTURE='1',EPC_MONTHLY_LOGO_REFRESH_TASK='1',
                 ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled',PYTHONDONTWRITEBYTECODE='1')
        env.pop('EPC_MONTHLY_DOM_APPTEST',None)
        env.pop('EPC_MONTHLY_LOGO_ADMIN_TASK',None)
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/monthly_app.py',
                '--server.address','127.0.0.1','--server.port','8546','--server.headless','true',
                '--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(logo.URL+'/_stcore/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as playwright:exercise(playwright,base)
            finally:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':main()
