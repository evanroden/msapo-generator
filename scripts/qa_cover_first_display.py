"""Hosted Chromium/WebKit first-paint check, isolated invented standing artwork.

One explicit fixture setup; no old-report upload, rescue click, force click,
preview patch, live namespace, or genuine output download. Real preview pipeline.
"""
from contextlib import ExitStack
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.qa_about_logo_refresh import controller_environment
from scripts.workspace_cover_first_display import MODES, COLORS
from scripts.workspace_history_observations import storage_state

OUT = ROOT / 'test-artifacts/cover-first-display'
URL = 'http://127.0.0.1:8548'
REPORT = {'synthetic_only': True, 'real_preview_converter': True, 'physical_device': False,
          'no_import_or_rescue_click': True, 'cases': {}, 'failures': []}


def receipt(page):
    node = page.locator('[data-enfra-standing-cover]').last
    return json.loads(node.get_attribute('data-enfra-standing-cover'))


def circle_geometry(path, roles, *, absent_roles=()):
    from PIL import Image
    image = Image.open(path).convert('RGB')
    observed = {}
    for role in roles:
        color = COLORS[role]
        points = [(x,y) for y in range(image.height) for x in range(image.width)
                  if max(abs(a-b) for a,b in zip(image.getpixel((x,y)), color)) < 12]
        assert len(points) >= 20, role + ' must visibly render, not just have a source reference'
        width = max(x for x,y in points)-min(x for x,y in points)+1
        height = max(y for x,y in points)-min(y for x,y in points)+1
        assert abs(width-height) <= max(3, min(width,height)*.12), (role,width,height)
        observed[role] = {'width': width, 'height': height}
    for role in absent_roles:
        color = COLORS[role]
        assert not any(max(abs(a-b) for a,b in zip(pixel,color)) < 12 for pixel in image.getdata()), role + ' unexpectedly rendered'
    return observed


def exercise(engine, name, mode, base):
    from playwright.sync_api import expect
    out = OUT / (name + '-' + mode); out.mkdir(parents=True, exist_ok=True)
    record = REPORT['cases'][name + '/' + mode] = {'result': 'running'}
    browser = engine.launch()
    context = browser.new_context(viewport={'width':1440,'height':1000}, device_scale_factor=1)
    token = secrets.token_hex(16)
    context.add_cookies([{'name':'epc_device_id','value':token,'url':URL}])
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    errors, external = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    def guard(route):
        from urllib.parse import urlparse
        target = urlparse(route.request.url)
        if target.scheme in ('http','https') and target.netloc != '127.0.0.1:8548':
            external.append(route.request.url); route.abort()
        else: route.continue_()
    context.route('**/*', guard)
    try:
        page.goto(URL + '/?cover_mode=' + mode)
        page.get_by_role('button', name='Create synthetic standing cover', exact=True).click()
        # Bring the ordinary cover surface into view once; viewport-driven loading is
        # intentional. No business selection/click or synthetic receipt follows.
        cover = page.locator('.st-key-epc_pair_monthly_cover')
        cover.locator('.report-preview').scroll_into_view_if_needed()
        expect(cover.locator('.report-preview-status')).to_have_text(re.compile(r'^Current · [1-9]\d* pages?$'), timeout=120000)
        image = cover.locator('.report-preview img').first
        expect(image).to_be_visible()
        expect(image).to_have_js_property('complete', True, timeout=20000)
        assert image.evaluate('node => node.naturalWidth > 0 && node.naturalHeight > 0')
        first = receipt(page)
        assert first['mode'] == mode and first['photo_present'] == (mode != 'absent-photo')
        assert not first['saved_report'] and not first['imported_report']
        assert first['template'].startswith('enfra_master:')
        expected_roles = ['brand_logo','client_logo'] + ([] if mode == 'absent-photo' else ['cover_photo'])
        assert set(first['artwork']) == set(expected_roles)
        for artwork in first['artwork'].values():
            assert artwork['source'] == 'Library' and len(artwork['references']) == 1
            assert artwork['references'][0].split('.')[0] == artwork['sha256']
        image.screenshot(path=str(out/'first-cover.png'))
        record['geometry'] = circle_geometry(out/'first-cover.png', expected_roles, absent_roles=['cover_photo'] if mode=='absent-photo' else [])
        before = storage_state(base, token)
        assert before['live_library_absent']
        page.reload()
        cover.locator('.report-preview').scroll_into_view_if_needed()
        expect(cover.locator('.report-preview-status')).to_have_text(re.compile(r'^Current · [1-9]\d* pages?$'), timeout=120000)
        expect(image).to_be_visible()
        expect(image).to_have_js_property('complete', True, timeout=20000)
        assert receipt(page) == first
        after = storage_state(base, token)
        for group in ('history','assets','standing'):
            assert after['groups'][group] == before['groups'][group], 'Passive reload changed '+group
        assert after['live_library_absent']
        image.screenshot(path=str(out/'reloaded-cover.png'))
        record['reload_geometry'] = circle_geometry(out/'reloaded-cover.png', expected_roles, absent_roles=['cover_photo'] if mode=='absent-photo' else [])
        if mode == 'absent-photo':
            # This is after the untouched first-paint proof. Check honest empty-state copy.
            panel = cover.get_by_test_id('stExpander').filter(has=page.get_by_text('Change cover photograph', exact=True))
            panel.locator('summary').click()
            expect(panel.get_by_text('No cover photograph in this report (optional).', exact=True)).to_be_visible()
        assert not errors and not external, (errors,external)
        record.update(result='passed', receipt=first)
    except Exception as exc:
        record.update(result='failed', error=type(exc).__name__+': '+str(exc)[:2000])
        page.screenshot(path=str(out/'first-failure.png'), full_page=True)
        (out/'first-failure.html').write_text(page.content())
        raise
    finally:
        context.tracing.stop(path=str(out/'trace.zip'))
        (out/'receipt.json').write_text(json.dumps(record, indent=2))
        context.close(); browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cover-first-synthetic-') as temp, ExitStack() as controller:
        base = Path(temp)
        (base/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        controller.enter_context(controller_environment(base))
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE='1', EPC_MONTHLY_COVER_FIRST_TASK='1',
                   ANTHROPIC_API_KEY='', SMARTSHEET_API_MODE='disabled', PYTHONDONTWRITEBYTECODE='1')
        for key in tuple(env):
            if key.startswith('EPC_MONTHLY_') and (key.endswith('_TASK') or key=='EPC_MONTHLY_DOM_APPTEST') and key!='EPC_MONTHLY_COVER_FIRST_TASK':
                env.pop(key)
        with (OUT/'streamlit.log').open('w') as log:
            process = subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/monthly_app.py',
                '--server.address','127.0.0.1','--server.port','8548','--server.headless','true','--browser.gatherUsageStats','false'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None: raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(URL+'/_stcore/health', timeout=1) as response:
                            if response.status==200: break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as playwright:
                    for engine,name in ((playwright.chromium,'chromium'),(playwright.webkit,'playwright-webkit')):
                        for mode in MODES:
                            try: exercise(engine,name,mode,base)
                            except Exception as exc: REPORT['failures'].append(name+'/'+mode+': '+str(exc)[:300])
            finally:
                process.terminate()
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                REPORT['result'] = 'failed' if REPORT['failures'] else 'completed-see-cases'
                (OUT/'results.json').write_text(json.dumps(REPORT,indent=2))
    if REPORT['failures']: raise AssertionError('; '.join(REPORT['failures']))

if __name__ == '__main__': main()
