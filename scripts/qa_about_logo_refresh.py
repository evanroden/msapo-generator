"""Ordinary first-click About refresh in Chromium and WebKit, invented data only.

Uses the existing marked/cookie-isolated actual guided fixture. No force click,
backend mutation after explicit sample setup, public route, retry, or live catalog.
Native outputs use the real builder/converter, not a shared-version save action.
"""
from contextlib import contextmanager, ExitStack
from hashlib import sha256
from io import BytesIO
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
from playwright.sync_api import expect, sync_playwright
from scripts.workspace_history_observations import namespace, storage_state
from scripts.workspace_logo_refresh_observations import MODES, artwork

OUT = ROOT / 'test-artifacts/about-logo-refresh'
URL = 'http://127.0.0.1:8546'
SELECTOR = '[data-enfra-logo-refresh]'
REPORT = {'synthetic_only': True, 'physical_device': False, 'cases': {},
    'legacy_omit_output_contract': 'Passive legacy company Omit retains its native source furniture; only explicit Replace once changes the bound occurrence. No claim of native omission.',
    'stale_revision_browser_coverage': 'Not exercised: this journey never changes the shared catalog. Exact stale/revision rejection is covered separately by AppTest.'}


def receipt(page):
    return json.loads(page.locator(SELECTOR).last.get_attribute('data-enfra-logo-refresh'))


def wait_state(page, *, company=False, after=0, scope=None, generation=None):
    page.wait_for_function('''wanted => {
      const nodes=document.querySelectorAll('[data-enfra-logo-refresh]');
      if(!nodes.length)return false;
      const s=JSON.parse(nodes[nodes.length-1].dataset.enfraLogoRefresh);
      return s.sequence>wanted.after && s.original_unchanged &&
        (wanted.scope==null || s.scope===wanted.scope) &&
        (wanted.generation==null || s.generation===wanted.generation) &&
        (!wanted.company || (s.working.block.source==='Replace once' &&
          JSON.stringify(s.working.block.asset_hashes)===JSON.stringify([s.company_asset]) &&
          JSON.stringify(s.working)===JSON.stringify(s.durable))) &&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }''', arg={'company': company, 'after': after, 'scope': scope, 'generation': generation}, timeout=30000)
    return receipt(page)


def protected_files(base, token):
    inventory = storage_state(base, token)
    assert inventory['live_library_absent']
    target, _, _ = namespace(base, token)
    root = target / 'monthly_reports'
    # Every existing saved version, profile, source asset and catalog byte/mtime.
    # Working journals and explicitly requested disposable output files are not
    # shared history. storage_state above validates all descendants and bounds.
    result = {}
    for prefix in ('snapshots', 'library', 'branding', 'objects'):
        for path in (root / prefix).rglob('*'):
            if path.is_file():
                result[str(path.relative_to(root))] = (path.stat().st_mtime_ns, sha256(path.read_bytes()).hexdigest())
    source = root / 'qa-logo-refresh/source.docx'
    result['original-source'] = (source.stat().st_mtime_ns, sha256(source.read_bytes()).hexdigest())
    return result


def about(page):
    panel = page.get_by_test_id('stExpander').filter(has=page.locator('summary').get_by_text('About this report', exact=True))
    expect(panel).to_have_count(1)
    if not panel.evaluate("node => node.matches('details') ? node.open : node.querySelector('details').open"):
        panel.locator('summary').first.click()
    return panel


def native_outputs(page, directory, expected):
    prior = receipt(page)
    sequence = prior['sequence']
    page.get_by_role('button', name='Render synthetic native logo outputs', exact=True).click()
    wait_state(page, after=sequence, scope=prior['scope'], generation=prior['generation'])
    for label, name in (('Download synthetic native Word', 'actual.docx'), ('Download synthetic native PDF', 'actual.pdf')):
        with page.expect_download(timeout=30000) as event:
            page.get_by_role('button', name=label, exact=True).click()
        event.value.save_as(directory / name)
    return validate_native_outputs(directory, expected)


def validate_native_outputs(directory, expected):
    from docx import Document
    from docx.oxml.ns import qn
    import pymupdf
    doc = Document(directory / 'actual.docx')
    blobs = [doc.part.rels[node.get(qn('r:embed'))].target_part.blob for node in doc.element.iter(qn('a:blip'))]
    assert [sha256(raw).hexdigest() for raw in blobs] == [sha256(raw).hexdigest() for raw in expected]
    with pymupdf.open(directory / 'actual.pdf') as pdf:
        assert len(pdf) == 1
        assert 'QA North and South - Synthetic' in ''.join(page.get_text() for page in pdf)
        images = [image for page in pdf for image in page.get_image_info(hashes=True)]
        assert len(images) == len(expected)
        ratios = [(image['bbox'][2]-image['bbox'][0]) / (image['bbox'][3]-image['bbox'][1]) for image in images]
        assert all(abs(actual-wanted) < .001 for actual, wanted in zip(ratios, ([3, 1] if len(expected) == 2 else [1])))
        # Independently inspect rendered pixel payloads, not merely file existence.
        expected_digests = []
        from PIL import Image
        from hashlib import md5
        for raw in expected:
            expected_digests.append(md5(Image.open(BytesIO(raw)).convert('RGB').tobytes()).digest())
        assert [item['digest'] for item in images] == expected_digests
        pdf[0].get_pixmap().save(directory / 'native-output.png')
    return {'docx_sha256': sha256((directory / 'actual.docx').read_bytes()).hexdigest(),
        'pdf_sha256': sha256((directory / 'actual.pdf').read_bytes()).hexdigest(), 'image_occurrences': len(expected)}


def exercise(engine, engine_name, mode, base):
    browser = engine.launch(headless=True)
    context = browser.new_context(viewport={'width': 1365, 'height': 900}, accept_downloads=True)
    token = secrets.token_hex(16)
    context.add_cookies([{'name': 'epc_device_id', 'value': token, 'url': URL}])
    errors, external = [], []
    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in ('data', 'blob') or (parsed.hostname == '127.0.0.1' and parsed.port == 8546):
            request.continue_()
        else:
            external.append(parsed.hostname); request.abort()
    context.route('**/*', route)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page(); page.set_default_timeout(30000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    out = OUT / engine_name / mode; out.mkdir(parents=True, exist_ok=True)
    record = {'stage': 'setup', 'errors': errors, 'external': external}
    REPORT['cases'][engine_name + '/' + mode] = record
    try:
        page.goto(URL + '/?workflow=monthly&logo_mode=' + mode)
        page.get_by_role('button', name='Create synthetic ' + mode + ' logo report', exact=True).click()
        identity = sha256(('monthly-qa-v1:' + token).encode('ascii')).hexdigest()[:32]
        before = wait_state(page, scope=identity)
        if mode == 'omit': assert before['working']['block']['source'] == 'Omit'
        if mode == 'custom': assert before['working']['block']['source'] == 'Replace once'
        baseline = protected_files(base, token)
        record['stage'] = 'passive About and reload'
        about(page)
        expect(page.get_by_role('button', name='Use this logo in this report', exact=True)).to_be_visible()
        assert receipt(page)['working'] == before['working']
        page.reload(); passive = wait_state(page, scope=identity, generation=before['generation'])
        assert passive['working'] == before['working'] and passive['saved'] == before['saved']
        assert protected_files(base, token) == baseline
        record['stage'] = 'passive native outputs'
        before_dir = out / 'before'; before_dir.mkdir()
        # Legacy company Omit preserves existing native furniture (native_layout
        # intentionally excludes brand_logo from its fallback removal branch).
        expected = [artwork('purple' if mode == 'custom' else 'red'), artwork('red')]
        record['before_outputs'] = native_outputs(page, before_dir, expected)
        assert protected_files(base, token) == baseline
        record['stage'] = 'one ordinary explicit About click'
        panel = about(page)
        action = panel.get_by_role('button', name='Use this logo in this report', exact=True)
        expect(action).to_be_enabled()
        sequence = receipt(page)['sequence']
        page.screenshot(path=str(out / 'before-click.png'), full_page=True)
        action.click()
        after = wait_state(page, company=True, after=sequence, scope=identity, generation=before['generation'])
        assert after['working']['assets'] == [{'reference': after['company_asset'], 'sha256': after['company_sha256']}]
        assert after['working']['without_logo'] == before['working']['without_logo']
        assert after['saved'] == before['saved'] and after['saved_revision'] == before['saved_revision']
        assert after['catalog_revision'] == before['catalog_revision'] == 1
        assert protected_files(base, token) == baseline
        record['stage'] = 'same-cookie reload recovery'
        page.reload(); recovered = wait_state(page, company=True, scope=identity, generation=before['generation'])
        expect(page.get_by_role('button', name='Use this logo in this report', exact=True)).to_have_count(0)
        assert recovered['working'] == after['working'] and recovered['saved'] == before['saved']
        assert protected_files(base, token) == baseline
        record['stage'] = 'refreshed native outputs'
        after_dir = out / 'after'; after_dir.mkdir()
        record['after_outputs'] = native_outputs(page, after_dir, [artwork('green'), artwork('red')])
        assert protected_files(base, token) == baseline
        page.screenshot(path=str(out / 'recovered.png'), full_page=True)
        assert not errors and not external
        record.update(result='passed', working=after['working'], saved_revision=after['saved_revision'])
    except Exception as exc:
        record.update(result='failed', error=type(exc).__name__ + ': ' + str(exc)[:2000])
        page.screenshot(path=str(out / 'first-failure.png'), full_page=True)
        (out / 'first-failure.html').write_text(page.content())
        raise
    finally:
        context.tracing.stop(path=str(out / 'trace.zip'))
        (out / 'receipt.json').write_text(json.dumps(record, indent=2))
        context.close(); browser.close()


@contextmanager
def controller_environment(base):
    """Bind controller observations to the same newly marked disposable root."""
    from scripts.workspace_browser_observations import require_synthetic_root
    previous = {key: os.environ.get(key) for key in ('EPC_DATA_DIR', 'EPC_MONTHLY_DOM_FIXTURE')}
    try:
        os.environ.update(EPC_DATA_DIR=str(base), EPC_MONTHLY_DOM_FIXTURE='1')
        require_synthetic_root(base)  # Missing/invalid marker remains a hard failure.
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    with tempfile.TemporaryDirectory(prefix='about-logo-synthetic-') as temp, ExitStack() as controller:
        base = Path(temp)
        (base / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        controller.enter_context(controller_environment(base))
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE='1', EPC_MONTHLY_LOGO_REFRESH_TASK='1',
            ANTHROPIC_API_KEY='', SMARTSHEET_API_MODE='disabled', PYTHONDONTWRITEBYTECODE='1')
        env.pop('EPC_MONTHLY_DOM_APPTEST', None)
        env.pop('EPC_MONTHLY_LOGO_ADMIN_TASK', None)
        with (OUT / 'streamlit.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'tests/fixtures/workspaces/monthly_app.py',
                '--server.address', '127.0.0.1', '--server.port', '8546', '--server.headless', 'true',
                '--browser.gatherUsageStats', 'false'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None: raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(URL + '/_stcore/health', timeout=1) as response:
                            if response.status == 200: break
                    except OSError: time.sleep(.1)
                else: raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as playwright:
                    for engine, name in ((playwright.chromium, 'chromium'), (playwright.webkit, 'playwright-webkit')):
                        for mode in MODES:
                            try: exercise(engine, name, mode, base)
                            except Exception as exc: failures.append(name + '/' + mode + ': ' + str(exc)[:300])
            finally:
                process.terminate()
                try: process.wait(timeout=20)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                REPORT['failures'] = failures
                (OUT / 'results.json').write_text(json.dumps(REPORT, indent=2))
    if failures: raise AssertionError('About logo native acceptance failed: ' + '; '.join(failures))


if __name__ == '__main__': main()
