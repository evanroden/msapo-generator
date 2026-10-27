"""Hosted native browsers: actual upload, period/site correction, save/reload.

Synthetic disposable namespace only. No injected review decisions, source-view
patches, forced clicks, increased resource limits or genuine report downloads.
"""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.qa_about_logo_refresh import controller_environment
from scripts.qa_import_receipts import wait_receipt
from scripts.workspace_import_retention import make_source, EDITED, FIRST, SECOND, OLD
from scripts.workspace_history_observations import namespace
from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
from app.monthly_report_import import MAX_DOCX_BYTES

OUT=ROOT/'test-artifacts/import-retention'
URL='http://127.0.0.1:8551'
REPORT={'synthetic_only':True,'physical_device':False,'real_upload_and_review_controls':True,
        'native_source_byte_limit':MAX_VIEW_SOURCE_BYTES,'cases':{},'failures':[]}


def all_cases_passed(report):
    expected={engine+'/'+scenario for engine in ('chromium','playwright-webkit') for scenario in ('stale','scope')}
    return (set(report.get('cases',{}))==expected and not report.get('failures')
            and all(case.get('result')=='passed' for case in report['cases'].values()))


def receipt(page, expected=None):
    return wait_receipt(page, 'data-import-retention', expected)


def exercise(engine,name,source,base,scenario,replacement=None):
    from playwright.sync_api import expect
    out=OUT/name/scenario;out.mkdir(parents=True,exist_ok=True)
    record=REPORT['cases'][name+'/'+scenario]={'result':'running'}
    browser=engine.launch();context=browser.new_context(viewport={'width':1440,'height':1000})
    token=secrets.token_hex(16)
    context.add_cookies([{'name':'epc_device_id','value':token,'url':URL}])
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        from urllib.parse import urlparse
        target=urlparse(route.request.url)
        if target.scheme in ('http','https') and target.netloc!='127.0.0.1:8551':
            external.append(route.request.url);route.abort()
        else:route.continue_()
    context.route('**/*',guard)
    def open_details(box):
        if not box.locator('details').evaluate('node=>node.open'):box.locator('summary').click()
    def choose_north():
        correction=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Correct source sites'))
        open_details(correction)
        combo=correction.get_by_role('combobox')
        # Native Backspace removes the last preselected tag (South), no DOM mutation.
        combo.click();combo.press('Backspace');combo.press('Tab')
        expect(correction.get_by_text('Demonstration South Facility',exact=True)).to_have_count(0)
    try:
        page.goto(URL)
        page.get_by_role('button',name='Prepare disposable site catalog',exact=True).click()
        upload=page.get_by_test_id('stFileUploader').filter(has=page.get_by_text('Starting report',exact=True))
        upload.locator('input[type=file]').set_input_files(str(source))
        proceed=page.get_by_role('button',name='Continue to this month’s updates',exact=True)
        expect(proceed).to_be_visible(timeout=120000)
        if scenario=='stale':
            expect(proceed).to_be_disabled()
            activity=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Monthly Activity'))
            if activity.count()==0:activity=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Activity Summary'))
            open_details(activity)
            activity.get_by_text('Update work, counts or photos',exact=True).click()
            text=activity.get_by_role('textbox',name='Work completed this month',exact=True)
            expect(text).to_have_value(FIRST+'\n\n'+SECOND)
            text.fill(EDITED);text.press('Tab')
            receipt(page, {'saved': False, 'staged_texts': [EDITED]})
            expect(proceed).to_be_disabled()
            confirmation=activity.get_by_role('checkbox',name='This work belongs in September 2026',exact=True)
            def confirm_month():
                # Streamlit's real input is clipped to 1px; its associated
                # visible label is the ordinary pointer target, not an overlay.
                expect(confirmation).not_to_be_checked()
                label=confirmation.locator('xpath=ancestor::label')
                expect(label).to_have_count(1)
                label.click()
                expect(confirmation).to_be_checked()
            confirm_month();expect(proceed).to_be_enabled()
            record['month_action']='one-visible-associated-label-click'
            # Close and reopen the actual review control after confirmation.
            # Ready content must remain correctable, not disappear on rerun.
            activity.locator('summary').click()
            expect(text).not_to_be_visible()
            open_details(activity)
            expect(text).to_have_value(EDITED)
            text.fill(EDITED+' Changed.');text.press('Tab')
            receipt(page, {'saved': False, 'staged_texts': [EDITED+' Changed.']})
            expect(confirmation).not_to_be_checked();expect(proceed).to_be_disabled()
            text.fill(EDITED);text.press('Tab')
            receipt(page, {'saved': False, 'staged_texts': [EDITED]})
            confirm_month()
            expect(proceed).to_be_enabled()
            expected=EDITED
        else:
            warning=page.get_by_text(re.compile('This report covers different sites'))
            expect(warning).to_be_visible()
            assert not any(FIRST in t for t in receipt(page)['staged_texts'])
            choose_north();expect(warning).to_be_visible()
            page.get_by_role('button',name='Confirm source sites',exact=True).click()
            expect(warning).to_have_count(0)
            assert receipt(page)['confirmed_source']
            assert any(FIRST in t for t in receipt(page)['staged_texts'])
            page.get_by_role('button',name='Use detected source sites',exact=True).click()
            expect(warning).to_be_visible()
            assert not receipt(page)['confirmed_source']
            page.get_by_role('button',name='Confirm source sites',exact=True).click()
            expect(warning).to_have_count(0)
            upload.locator('input[type=file]').set_input_files(str(replacement))
            receipt(page, {'staged_sha256': sha256(replacement.read_bytes()).hexdigest()})
            expect(warning).to_be_visible(timeout=120000)
            assert not receipt(page)['confirmed_source']
            choose_north()
            page.get_by_role('button',name='Confirm source sites',exact=True).click()
            expect(warning).to_have_count(0)
            source=replacement
            expected='September 2026 '+FIRST
        assert not receipt(page)['saved']
        page.screenshot(path=str(out/'before-save.png'),full_page=True)
        proceed.click()
        expect(page.get_by_text('Synthetic import saved',exact=True)).to_be_visible(timeout=120000)
        saved=receipt(page, {'saved': True})
        assert saved['sites']==['north']
        assert any(expected in t for t in saved['saved_texts'])
        assert any(SECOND in t for t in saved['saved_texts'])
        if scenario=='stale':assert not any(OLD in t for t in saved['saved_texts'])
        assert saved['source_sha256']==sha256(source.read_bytes()).hexdigest()
        assert saved['source_bytes']==source.stat().st_size
        page.reload();expect(page.get_by_text('Synthetic import saved',exact=True)).to_be_visible(timeout=120000)
        reloaded=receipt(page, {'saved': True})
        assert reloaded['saved_texts']==saved['saved_texts']
        assert reloaded['source_sha256']==saved['source_sha256']
        assert not (base/'monthly_reports').exists()
        assert not errors and not external,(errors,external)
        page.screenshot(path=str(out/'after-reload.png'),full_page=True)
        record.update(result='passed',saved=saved,reloaded=reloaded)
    except Exception as exc:
        record.update(result='failed',error=type(exc).__name__+': '+str(exc)[:2000])
        page.screenshot(path=str(out/'failure.png'),full_page=True)
        (out/'failure.html').write_text(page.content());raise
    finally:
        context.tracing.stop(path=str(out/'trace.zip'))
        (out/'receipt.json').write_text(json.dumps(record,indent=2))
        context.close();browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    REPORT['tested_checkout']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    assert MAX_VIEW_SOURCE_BYTES==24*1024*1024 and MAX_DOCX_BYTES==128*1024*1024
    with tempfile.TemporaryDirectory(prefix='cover-fallback-synthetic-') as temp, ExitStack() as controller:
        base=Path(temp);(base/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        sources={scenario:make_source(base/'input',scenario) for scenario in ('stale','scope')}
        replacement=make_source(base/'input','scope','replacement')
        for source in (*sources.values(),replacement):
            assert source.stat().st_size < 1024*1024
            (OUT/source.name).write_bytes(source.read_bytes())
        controller.enter_context(controller_environment(base))
        env=dict(os.environ,EPC_DATA_DIR=temp,EPC_MONTHLY_DOM_FIXTURE='1',EPC_MONTHLY_IMPORT_RETENTION_TASK='1',
                 ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled',PYTHONDONTWRITEBYTECODE='1')
        for key in tuple(env):
            if key.startswith('EPC_MONTHLY_') and (key.endswith('_TASK') or key=='EPC_MONTHLY_DOM_APPTEST') and key!='EPC_MONTHLY_IMPORT_RETENTION_TASK':
                env.pop(key)
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/monthly_app.py',
                '--server.address','127.0.0.1','--server.port','8551','--server.headless','true','--browser.gatherUsageStats','false'],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(URL+'/_stcore/health',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as p:
                    for engine,name in ((p.chromium,'chromium'),(p.webkit,'playwright-webkit')):
                        for scenario,source in sources.items():
                            try:exercise(engine,name,source,base,scenario,replacement)
                            except Exception as exc:REPORT['failures'].append(name+'/'+scenario+': '+str(exc)[:300])
            finally:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                complete=all_cases_passed(REPORT)
                if not complete and not REPORT['failures']:
                    REPORT['failures'].append('Native setup or case execution did not complete all four required scenarios.')
                REPORT['result']='passed' if complete and not REPORT['failures'] else 'failed'
                (OUT/'results.json').write_text(json.dumps(REPORT,indent=2))
    if REPORT['failures']:raise AssertionError('; '.join(REPORT['failures']))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        REPORT['result']='failed'
        REPORT['failures'].append(type(exc).__name__+': '+str(exc)[:1000])
        OUT.mkdir(parents=True,exist_ok=True)
        (OUT/'results.json').write_text(json.dumps(REPORT,indent=2))
        raise
