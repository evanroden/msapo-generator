"""One native source-review/save/reload/output journey per browser; no retries."""
from io import BytesIO
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "training-source-review"
URL = "http://127.0.0.1:8537"
RECEIPT_PREFIX = "QA Training review receipt: "


def receipt(page, *, reviews=None, included=None, saved=None, previous_review=None):
    payload = {"prefix": RECEIPT_PREFIX, "wanted": {"reviews": reviews, "included": included,
        "saved": saved, "previous": previous_review}}
    predicate = '''payload => {
      for (const node of document.querySelectorAll('[data-testid="stCaptionContainer"]')) {
        const text=node.textContent||'';
        const at=text.indexOf(payload.prefix);
        if(at<0)continue;
        let v;
        try{v=JSON.parse(text.slice(at+payload.prefix.length))}catch{continue}
        const wanted=payload.wanted;
        if ((wanted.reviews===null||v.reviews===wanted.reviews) &&
            (wanted.included===null||v.tables.some(t=>t.rows.some(r=>r[0]==='Synthetic drill'))===wanted.included) &&
            (wanted.saved===null||v.saved_revision===wanted.saved) &&
            (wanted.previous===null||v.review_revision!==wanted.previous) &&
            document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning')
          return true;
      }
      return false;
    }'''
    try:
        page.wait_for_function(predicate, arg=payload, timeout=30000)
    except Exception as exc:
        probe = page.evaluate('''payload => {
          const candidates=[];
          for (const node of document.querySelectorAll('body *')) {
            const text=node.textContent||'';
            const at=text.indexOf(payload.prefix);
            if(at<0)continue;
            const raw=text.slice(at+payload.prefix.length);
            let parsed=null, parse_error=null;
            try{parsed=JSON.parse(raw)}catch(error){parse_error=String(error)}
            candidates.push({
              tag:node.tagName, testid:node.getAttribute('data-testid'),
              raw:raw.slice(0,1000), parse_error,
              parsed:parsed&&{
                reviews:parsed.reviews, saved_revision:parsed.saved_revision,
                review_revision:parsed.review_revision,
                included:Array.isArray(parsed.tables)&&parsed.tables.some(
                  table=>Array.isArray(table.rows)&&table.rows.some(row=>row[0]==='Synthetic drill')),
                table_count:Array.isArray(parsed.tables)?parsed.tables.length:null
              }
            });
            if(candidates.length>=8)break;
          }
          return {
            script_state:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')||null,
            body_has_prefix:(document.body?.textContent||'').includes(payload.prefix),
            candidates,
            body_tail:(document.body?.innerText||'').slice(-2500)
          };
        }''', payload)
        raise AssertionError("Training receipt readiness diagnostics: " +
                             json.dumps(probe, sort_keys=True, ensure_ascii=False)) from exc
    return page.evaluate('''prefix => {
      for (const node of document.querySelectorAll('[data-testid="stCaptionContainer"]')) {
        const text=node.textContent||'';
        const at=text.indexOf(prefix);
        if(at<0)continue;
        try{return JSON.parse(text.slice(at+prefix.length))}catch{}
      }
      throw new Error('Training receipt text disappeared after readiness.');
    }''', RECEIPT_PREFIX)


def journey(engine, name):
    from playwright.sync_api import expect
    from docx import Document
    import pymupdf
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    browser = engine.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900}, accept_downloads=True)
    errors, external = [], []
    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in ("data", "blob") or (parsed.hostname == "127.0.0.1" and parsed.port == 8537):
            request.continue_()
        else:
            external.append(request.request.url)
            request.abort()
    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    evidence = {"browser": name, "synthetic": True, "steps": [], "errors": errors, "external": external}
    try:
        page.goto(URL + '/?case=' + name, wait_until='domcontentloaded')
        evidence['steps'].append(receipt(page, reviews=0, included=False))
        page.get_by_text('Import Training from a saved source', exact=True).click()
        page.get_by_role('button', name='Review this Training table', exact=True).click()
        reviewed = receipt(page, reviews=1, included=False)
        evidence['steps'].append(reviewed)
        hours = page.get_by_role('textbox', name='Hours', exact=True)
        expect(hours).to_have_value('0')
        hours.fill('')
        # One native form submission delivers the pending intentional clear.
        page.get_by_role('button', name='Save Training row review', exact=True).click()
        receipt(page, reviews=1, included=False, previous_review=reviewed['review_revision'])
        expect(page.get_by_role('textbox', name='Hours', exact=True)).to_have_value('')
        page.get_by_role('button', name='Include reviewed Training rows', exact=True).click()
        accepted = receipt(page, reviews=1, included=True)
        event = next(t for t in accepted['tables'] if t['reference'] == 'training:events:v1')
        assert event['rows'] == [['Synthetic drill', '2026-09-12', 'Virtual', 'Alice', '']]
        page.get_by_role('button', name='Save synthetic shared version', exact=True).click()
        evidence['steps'].append(receipt(page, reviews=1, included=True, saved=1))
        page.reload(wait_until='domcontentloaded')
        reopened = receipt(page, reviews=1, included=True, saved=1)
        assert reopened['fingerprint'] == accepted['fingerprint']
        page.set_viewport_size({'width': 390, 'height': 844})
        page.get_by_text('Import Training from a saved source', exact=True).click()
        expect(page.get_by_role('textbox', name='Hours', exact=True)).to_have_value('')
        page.get_by_role('button', name='Include reviewed Training rows', exact=True).click()
        assert receipt(page, reviews=1, included=True, saved=1)['fingerprint'] == reopened['fingerprint']
        page.get_by_role('button', name='Generate synthetic Training output', exact=True).click()
        word_button = page.get_by_role('button', name='Download synthetic Word', exact=True)
        expect(word_button).to_be_visible(timeout=90000)
        with page.expect_download() as download:
            word_button.click()
        word = Path(download.value.path()).read_bytes()
        with page.expect_download() as download:
            page.get_by_role('button', name='Download synthetic PDF', exact=True).click()
        pdf = Path(download.value.path()).read_bytes()
        doc = Document(BytesIO(word))
        rows = [tuple(c.text for c in r.cells) for t in doc.tables for r in t.rows]
        assert rows.count(('Synthetic drill', '2026-09-12', 'Virtual', 'Alice', '')) == 1
        with pymupdf.open(stream=pdf, filetype='pdf') as result:
            text = '\n'.join(p.get_text() for p in result)
            assert text.count('Synthetic drill') == 1 and '2026-09-12' in text
        assert not errors and not external
        (folder/'report.docx').write_bytes(word)
        (folder/'report.pdf').write_bytes(pdf)
        evidence['output'] = {'docx_sha256': sha256(word).hexdigest(), 'pdf_sha256': sha256(pdf).hexdigest()}
        evidence['passed'] = True
        page.screenshot(path=str(folder/'complete.png'), full_page=True)
    except Exception:
        evidence['passed'] = False
        evidence['failure'] = traceback.format_exc()
        page.screenshot(path=str(folder/'failure.png'), full_page=True)
        raise
    finally:
        (folder/'evidence.json').write_text(json.dumps(evidence, indent=2))
        context.close()
        browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='synthetic-training-browser-') as temporary:
        env = {**os.environ, 'EPC_DATA_DIR': temporary, 'EPC_TRAINING_SOURCE_QA': '1',
               'ANTHROPIC_API_KEY': '', 'OPENAI_API_KEY': ''}
        with (OUT/'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run',
                'tests/fixtures/workspaces/training_import_app.py', '--server.port=8537',
                '--server.address=127.0.0.1', '--server.headless=true', '--browser.gatherUsageStats=false'],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(150):
                    if server.poll() is not None:
                        raise RuntimeError('Synthetic Training server exited before startup')
                    try:
                        with urlopen(URL+'/_stcore/health', timeout=1) as health:
                            if health.status == 200:
                                break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('Synthetic Training server did not start')
                failures = []
                with sync_playwright() as p:
                    for name in ('chromium', 'webkit'):
                        try:
                            journey(getattr(p, name), name)
                        except Exception as exc:
                            failures.append(name+': '+str(exc))
                if failures:
                    raise SystemExit('Training source review failures: '+'; '.join(failures))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == '__main__':
    main()
