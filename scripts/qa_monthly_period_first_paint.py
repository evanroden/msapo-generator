"""Native period-control arrival cannot move an action during its first press.

Hold only the real Selectbox module response, then deliver it between a trusted
pointerdown and pointerup at the same coordinates. Production widget code and
callbacks run unchanged. No retries, rescue scrolling or genuine report data.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts/monthly-period-first-paint'
URL = 'http://127.0.0.1:8553'


def geometry(page):
    return page.evaluate('''() => {
      const rect = selector => {
        const r=document.querySelector(selector).getBoundingClientRect();
        return {x:r.x,y:r.y,w:r.width,h:r.height};
      };
      return {button:rect('.st-key-period_action button'),
        month:rect('.st-key-report_month_number'),year:rect('.st-key-report_year'),
        scroll:document.querySelector('[data-testid="stMain"]').scrollTop};
    }''')


def frames(page):
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def exercise(engine, name, width, scale, long_label):
    from playwright.sync_api import expect
    browser=engine.launch(headless=True)
    context=browser.new_context(viewport={'width':width,'height':900})
    held=[];external=[];errors=[]
    def route(request):
        parsed=urlparse(request.request.url)
        if parsed.hostname!='127.0.0.1' or parsed.port!=8553:
            external.append(parsed.hostname);request.abort()
        elif re.search(r'/Selectbox\.[^/]+\.js$',parsed.path):
            held.append(request)
        else:request.continue_()
    context.route('**/*',route)
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();page.set_default_timeout(15000)
    page.on('pageerror',lambda error:errors.append(str(error)))
    result={'engine':name,'width':width,'font_scale':scale,'long_label':long_label,
            'physical_device':False,'runs':[],'errors':errors,'external':external}
    label=f'{name}-{width}-{scale}-'+('long' if long_label else 'short')
    try:
        for load in ('cold','reload'):
            held.clear()
            if load=='cold':page.goto(URL+('/?long_label=1' if long_label else ''),wait_until='domcontentloaded')
            else:page.reload(wait_until='domcontentloaded')
            # Text scaling is established before the tested action. This is
            # CSS text scale, not browser zoom or physical-device acceptance.
            page.add_style_tag(content='html {font-size:'+str(16*scale)+'px !important;}')
            action=page.get_by_role('button',name='Record synthetic action',exact=True)
            expect(action).to_be_visible()
            expect(page.locator('.st-key-report_month_number > [data-testid="stSkeleton"]')).to_have_count(1)
            page.wait_for_function('document.querySelector("[data-testid=stApp]")?.dataset.testScriptState === "notRunning"')
            assert held,'Expected a held real Selectbox module'
            action.evaluate('node => document.querySelector("[data-testid=stMain]").scrollTop += node.getBoundingClientRect().top-400')
            frames(page)
            page.evaluate('''() => {
              window.__periodPress=[];
              for(const type of ['pointerdown','pointerup','click'])
                document.addEventListener(type,event=>window.__periodPress.push({type,
                  trusted:event.isTrusted,owned:!!event.target.closest('.st-key-period_action'),
                  x:event.clientX,y:event.clientY}),{capture:true,passive:true});
            }''')
            before=geometry(page)
            x=before['button']['x']+before['button']['w']/2
            y=before['button']['y']+before['button']['h']/2
            page.mouse.move(x,y);page.mouse.down()
            for pending in held:pending.continue_()
            expect(page.locator('.st-key-report_month_number [data-testid="stSelectbox"]')).to_have_count(1)
            expect(page.locator('.st-key-report_year [data-testid="stSelectbox"]')).to_have_count(1)
            frames(page)
            after=geometry(page)
            page.mouse.up()
            events=page.evaluate('window.__periodPress')
            run={'load':load,'before':before,'after':after,'events':events}
            result['runs'].append(run)
            page.screenshot(path=str(OUT/(label+'-'+load+'.png')))
            assert abs(after['button']['y']-before['button']['y'])<=3,run
            assert abs(after['scroll']-before['scroll'])<=3,run
            for control in ('month','year'):
                assert abs(after[control]['h']-before[control]['h'])<=3,run
            assert [e['type'] for e in events]==['pointerdown','pointerup','click'],run
            assert all(e['trusted'] and e['owned'] for e in events),run
            expect(page.get_by_text('Native actions: 1',exact=True)).to_be_visible()
            expect(page.get_by_text('Received period: (2026, 9)',exact=True)).to_be_visible()
            # Full native labels remain readable in flow. No fixed-height live
            # control, hidden label, nested scroller or duplicate input exists.
            for key in ('month_number','year'):
                control=page.locator('.st-key-report_'+key)
                expect(control.locator('[data-testid="stWidgetLabel"]')).to_be_visible()
                assert control.evaluate('node => node.scrollHeight <= node.clientHeight+1')
        assert not errors and not external
    except Exception as error:
        result['failure']=str(error)
        page.screenshot(path=str(OUT/(label+'-first-failure.png')))
        raise
    finally:
        (OUT/(label+'.json')).write_text(json.dumps(result,indent=2))
        context.tracing.stop(path=str(OUT/(label+'-trace.zip')))
        context.close();browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    failures=[]
    with tempfile.TemporaryDirectory(prefix='period-first-paint-') as temp:
        env=dict(os.environ,EPC_DATA_DIR=temp,ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled')
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/period_mount_app.py',
                '--server.address','127.0.0.1','--server.port','8553','--server.headless','true',
                '--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(URL+'/_stcore/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as playwright:
                    for engine,name in ((playwright.chromium,'chromium'),(playwright.webkit,'webkit')):
                        for width,scale,long_label in ((1365,1,False),(390,1,False),(390,2,True)):
                            try:exercise(engine,name,width,scale,long_label)
                            except Exception as error:failures.append(f'{name}/{width}/{scale}: {error}')
            finally:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    if failures:raise AssertionError('\n'.join(failures))


if __name__=='__main__':main()
