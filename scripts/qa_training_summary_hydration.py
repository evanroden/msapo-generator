"""Trusted down/hydration/up proof on the real Streamlit first-paint summary.

The optional baseline mode reproduces the retained old lazy Table defect.
No external services, changed native-row journey, forced clicks or retries.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts/training-summary-hydration'
APP = '''
import os
import streamlit as st
from app.monthly_report_training_ui import _session_summary_html
rows = (("Synthetic safety refresher with a complete unshortened description", "2026-09-25", "In person", "Synthetic North staff; Synthetic South staff", "0.75"),)
st.subheader("Training completed this month")
if os.environ.get("EPC_TRAINING_SUMMARY_BASELINE") == "1":
    st.table([dict(zip(("Training", "Date", "Method", "Participants", "Hours"), rows[0]))])
else:
    st.markdown(_session_summary_html(rows), unsafe_allow_html=True)
st.button("Edit request")
'''


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='training-summary-') as temp:
        path=Path(temp)/'summary_fixture.py';path.write_text(APP)
        env=dict(os.environ,PYTHONPATH=str(ROOT),ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled')
        with (OUT/'streamlit.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','streamlit','run',str(path),'--server.address','127.0.0.1','--server.port','8559','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while True:
                    try:
                        with urlopen('http://127.0.0.1:8559/_stcore/health',timeout=1):break
                    except OSError:
                        if time.monotonic()>deadline:raise
                        time.sleep(.1)
                with sync_playwright() as p:
                    for engine in ('chromium','webkit'):
                        browser=getattr(p,engine).launch()
                        try:
                            for width in (320,545,1365):
                                page=browser.new_page(viewport={'width':width,'height':1000})
                                pending=[]
                                page.route('**/Table.*.js',lambda route:pending.append(route))
                                page.goto('http://127.0.0.1:8559',wait_until='domcontentloaded')
                                button=page.get_by_role('button',name='Edit request',exact=True)
                                button.wait_for(state='visible')
                                page.wait_for_function('''() => document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning' ''')
                                button.evaluate('''node=>{window.hits=[];node.addEventListener('click',e=>window.hits.push(e.isTrusted));}''')
                                old=button.bounding_box();point={'x':old['x']+old['width']/2,'y':old['y']+old['height']/2}
                                page.mouse.move(**point);page.mouse.down()
                                for route in pending:route.continue_()
                                if pending:
                                    page.locator('[data-testid="stTable"]').wait_for(state='visible')
                                else:
                                    page.locator('[data-enfra-training-summary] table').wait_for(state='visible')
                                new=button.bounding_box();page.mouse.up()
                                hits=page.evaluate('window.hits')
                                page.screenshot(path=str(OUT/f'{engine}-{width}.png'))
                                item={'engine':engine,'width':width,'before':old,'after':new,'trusted_clicks':hits,'lazy_table_requests':len(pending)}
                                results.append(item)
                                assert old==new and hits==[True],item
                                assert page.locator('[data-enfra-training-summary] td').count()==5
                                summary=page.locator('[data-enfra-training-summary]')
                                summary.evaluate('(node)=>node.scrollLeft=node.scrollWidth')
                                assert summary.locator('td').last.inner_text()=='0.75 hours'
                                page.screenshot(path=str(OUT/f'{engine}-{width}-right.png'))
                                page.close()
                        finally:browser.close()
            finally:
                server.terminate();server.wait(timeout=20)
                (OUT/'results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
