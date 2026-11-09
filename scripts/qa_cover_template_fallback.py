"""Hosted native browsers: real 25 MiB upload -> edit -> template -> saved DOCX.

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
from scripts.workspace_cover_template_fallback import make_source, EDITED
from scripts.workspace_history_observations import namespace
from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
from app.monthly_report_import import MAX_DOCX_BYTES

OUT=ROOT/'test-artifacts/cover-template-fallback'
URL='http://127.0.0.1:8549'
REPORT={'synthetic_only':True,'physical_device':False,'real_upload_and_review_controls':True,
        'native_source_byte_limit':MAX_VIEW_SOURCE_BYTES,'cases':{},'failures':[]}


def receipt(page, expected=None, *, timeout=30000):
    return wait_receipt(page, 'data-enfra-template-fallback', expected, timeout=timeout)


def exercise(engine,name,source,base):
    from playwright.sync_api import expect
    out=OUT/name;out.mkdir(parents=True,exist_ok=True)
    record=REPORT['cases'][name]={'result':'running'}
    browser=engine.launch()
    context=browser.new_context(viewport={'width':1440,'height':1000})
    token=secrets.token_hex(16)
    context.add_cookies([{'name':'epc_device_id','value':token,'url':URL}])
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        from urllib.parse import urlparse
        target=urlparse(route.request.url)
        if target.scheme in ('http','https') and target.netloc!='127.0.0.1:8549':
            external.append(route.request.url);route.abort()
        else:route.continue_()
    context.route('**/*',guard)
    try:
        page.goto(URL)
        page.get_by_role('button',name='Install synthetic independent template',exact=True).click()
        upload=page.get_by_test_id('stFileUploader').filter(has=page.get_by_text('Starting report',exact=True))
        upload.locator('input[type=file]').set_input_files(str(source))
        expect(page.get_by_text(re.compile('This file is within the 128 MiB upload limit'))).to_be_visible(timeout=120000)
        expect(page.get_by_text(re.compile('limited to 24 MiB'))).to_be_visible()
        proceed=page.get_by_role('button',name='Continue to this month’s updates',exact=True)
        expect(proceed).to_be_disabled()
        # Open the production activity review; no session-state injection.
        activity=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Monthly Activity'))
        if activity.count()==0:
            activity=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Activity Summary'))
        expect(activity).to_have_count(1)
        summary=activity.locator('summary')
        if summary.get_attribute('aria-expanded')!='true':
            # HTML details.open is authoritative where aria-expanded is absent.
            if not activity.locator('details').evaluate('node => node.open'):
                summary.click()
        activity.get_by_text('Update work, counts or photos',exact=True).click()
        text=activity.get_by_role('textbox',name='Work completed this month',exact=True)
        expect(text).to_be_visible();text.fill(EDITED);text.press('Tab')
        expect(text).to_have_value(EDITED)
        page.get_by_role('button',name='Use ENFRA template and keep this review',exact=True).click()
        expect(page.get_by_text(re.compile('whole report, not just its cover'))).to_be_visible()
        expect(proceed).to_be_enabled(timeout=120000)
        selected=receipt(page, {'template_chosen': True})
        assert not selected['saved'] and selected['profile_count']==0
        assert selected['template_chosen'] and EDITED in selected['staged_texts']
        page.screenshot(path=str(out/'review-before-save.png'),full_page=True)
        proceed.click()
        expect(page.get_by_text('Synthetic reviewed report saved',exact=True)).to_be_visible(timeout=120000)
        saved=receipt(page, {'saved': True})
        assert saved['saved'] and saved['profile_count']==1 and EDITED in saved['saved_texts']
        assert saved['template'].startswith('enfra_master:')
        assert saved['source_sha256']==sha256(source.read_bytes()).hexdigest()
        assert saved['source_bytes']==source.stat().st_size
        page.reload()
        expect(page.get_by_text('Synthetic reviewed report saved',exact=True)).to_be_visible(timeout=120000)
        reloaded=receipt(page, {'saved': True})
        assert reloaded['saved_texts']==saved['saved_texts'] and reloaded['source_sha256']==saved['source_sha256']
        page.get_by_role('button',name='Build saved synthetic DOCX',exact=True).click()
        final=receipt(page, {'saved': True, 'output.edited_text_present': True}, timeout=120000)
        assert final['output']['edited_text_present'] and final['output']['unread_source_art_absent'] and final['output']['pricing_absent']
        target,_,_=namespace(base,token)
        generated=target/'monthly_reports'/'qa-fallback-final.docx'
        assert generated.is_file()
        (out/'synthetic-final.docx').write_bytes(generated.read_bytes())
        assert not (base/'monthly_reports').exists(),'Live library must never be touched'
        assert not errors and not external,(errors,external)
        page.screenshot(path=str(out/'saved-report.png'),full_page=True)
        record.update(result='passed',before_save=selected,final=final)
    except Exception as exc:
        record.update(result='failed',error=type(exc).__name__+': '+str(exc)[:2000])
        page.screenshot(path=str(out/'failure.png'),full_page=True)
        (out/'failure.html').write_text(page.content())
        raise
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
        source=make_source(base/'input')
        assert MAX_VIEW_SOURCE_BYTES < source.stat().st_size < MAX_DOCX_BYTES
        REPORT['source_bytes']=source.stat().st_size
        REPORT['source_sha256']=sha256(source.read_bytes()).hexdigest()
        controller.enter_context(controller_environment(base))
        env=dict(os.environ,EPC_DATA_DIR=temp,EPC_MONTHLY_DOM_FIXTURE='1',EPC_MONTHLY_COVER_FALLBACK_TASK='1',
                 ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled',PYTHONDONTWRITEBYTECODE='1')
        for key in tuple(env):
            if key.startswith('EPC_MONTHLY_') and (key.endswith('_TASK') or key=='EPC_MONTHLY_DOM_APPTEST') and key!='EPC_MONTHLY_COVER_FALLBACK_TASK':
                env.pop(key)
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/monthly_app.py',
                '--server.address','127.0.0.1','--server.port','8549','--server.headless','true','--browser.gatherUsageStats','false'],
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
                        try:exercise(engine,name,source,base)
                        except Exception as exc:REPORT['failures'].append(name+': '+str(exc)[:300])
            finally:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                REPORT['result']='failed' if REPORT['failures'] else 'passed'
                (OUT/'results.json').write_text(json.dumps(REPORT,indent=2))
    if REPORT['failures']:raise AssertionError('; '.join(REPORT['failures']))

if __name__=='__main__':main()
