"""Synthetic WebKit layout regression, not physical Safari or fold hardware proof.

Run: python scripts/qa_duo_compact_portrait.py
QA_WEBKIT_EXECUTABLE optionally selects an installed WebKit binary. All data is
invented. Outputs stay in an ignored evidence directory, not in the repository.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect
from qa_device_metadata import browser_evidence

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts' / 'duo-compact-portrait'
VALUE = 'Invented notes retained through resize and preview.'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {'synthetic_only': True, 'physical_device': False, 'checks': []}
    with tempfile.TemporaryDirectory() as data, (OUT / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run',
            'tests/fixtures/workspaces/duo_app.py', '--server.port', '8523',
            '--server.address', '127.0.0.1', '--server.headless', 'true',
            '--browser.gatherUsageStats', 'false'], cwd=ROOT,
            env=dict(os.environ, EPC_DATA_DIR=data, ANTHROPIC_API_KEY='synthetic-unused'),
            stdout=log, stderr=log)
        try:
            for _ in range(150):
                try:
                    urlopen('http://127.0.0.1:8523/_stcore/health', timeout=1)
                    break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError('Disposable fixture did not start')
            with sync_playwright() as playwright:
                options = {'executable_path': os.environ['QA_WEBKIT_EXECUTABLE']} if os.environ.get('QA_WEBKIT_EXECUTABLE') else {}
                browser = playwright.webkit.launch(**options)
                page = browser.new_page(viewport={'width': 669, 'height': 885})
                page.set_default_timeout(20000)
                evidence['environment'] = browser_evidence(page, engine='webkit', input_method='automated mouse and keyboard')
                page.goto('http://127.0.0.1:8523')
                root = page.locator('.epc-workspace')
                notes = page.get_by_label('Synthetic notes', exact=True)
                receipt = page.get_by_text('Layout fixture pass ',exact=False)

                def commit_notes():
                    before=receipt.inner_text()
                    notes.fill(VALUE)
                    page.get_by_label('Synthetic reference',exact=True).click()
                    page.wait_for_function("old=>{const a=[...document.querySelectorAll('p')].filter(n=>n.textContent.startsWith('Layout fixture pass '));return a.length===1&&a[0].textContent!==old}",arg=before)
                    expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
                    expect(page.locator('[data-stale="true"]')).to_have_count(0)
                    expect(notes).to_have_count(1)
                    expect(root).to_have_count(1)

                def settle(mode):
                    expect(root).to_have_attribute('data-epc-mode', mode)
                    page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')

                def inspect(name, mode, width, height):
                    page.set_viewport_size({'width': width, 'height': height})
                    settle(mode)
                    assert notes.input_value() == VALUE, name
                    observed = page.evaluate('''() => {
                      const box=n=>n.getBoundingClientRect().toJSON();
                      return {mode:document.querySelector('.epc-workspace').dataset.epcMode,
                        overflow:document.documentElement.scrollWidth>innerWidth+1,
                        tabs:[...document.querySelectorAll('.st-key-workflow_mode [role=radio]')].map(box),
                        steps:[...document.querySelectorAll('.po-step-link')].map(box),
                        panes:[...document.querySelectorAll('.epc-workspace-editor,.epc-workspace-reference')].map(box)};
                    }''')
                    assert not observed['overflow'], (name, observed)
                    assert len(observed['tabs']) == 3
                    assert all(t['height'] >= 44 and t['width'] >= 44 for t in observed['tabs'])
                    if width <= 540:
                        assert max(t['y'] for t in observed['tabs'])-min(t['y'] for t in observed['tabs']) < 1
                    if width <= 700 and observed['steps']:
                        assert all(t['height'] >= 44 for t in observed['steps'])
                        assert len({round(t['y']) for t in observed['steps']}) == 2
                    page.get_by_test_id('stMain').evaluate('n=>n.scrollTop=0')
                    page.screenshot(path=str(OUT / (name + '.png')))
                    evidence['checks'].append({'name': name, **observed})

                settle('wide')
                # Native controls may move the lazy viewer below the fold.
                # Bring its real container into view before requiring pixels.
                page.locator('.epc-workspace-reference').scroll_into_view_if_needed()
                expect(page.locator('.report-preview img').first).to_be_visible(timeout=20000)
                expect(page.locator('.report-preview img').first).to_have_js_property('complete', True)
                assert page.locator('.report-preview img').first.evaluate('n=>n.naturalWidth>0')
                commit_notes()
                inspect('open-portrait', 'wide', 669, 885)
                inspect('compact-phone', 'compact', 382, 600)
                page.get_by_role('button', name='View preview', exact=True).click()
                expect(page.get_by_role('button', name='Back to editing', exact=True)).to_be_visible()
                page.get_by_role('button', name='Back to editing', exact=True).click()
                expect(notes).to_be_visible()
                assert notes.input_value() == VALUE
                inspect('small-phone', 'compact', 320, 600)
                inspect('keyboard-height', 'compact', 669, 200)
                inspect('open-return', 'wide', 669, 885)
                page.evaluate("document.documentElement.style.fontSize='22.4px';window.dispatchEvent(new Event('resize'))")
                inspect('larger-text', 'compact', 669, 885)
                page.evaluate("document.documentElement.style.fontSize='';window.dispatchEvent(new Event('resize'))")
                # Segment rectangles explicitly simulate a measured fold. No
                # user-agent name, screen model or guessed hinge is used.
                def segments(values):
                    page.evaluate('''segments=>{
                        Object.defineProperty(window,'viewport',{configurable:true,value:{segments}});
                        window.dispatchEvent(new Event('resize'));
                    }''', values)
                page.set_viewport_size({'width': 951, 'height': 700})
                segments([{'x':0,'y':0,'width':470,'height':700}, {'x':490,'y':0,'width':461,'height':700}])
                inspect('simulated-book', 'book', 951, 700)
                page.set_viewport_size({'width':669,'height':1100})
                segments([{'x':0,'y':0,'width':669,'height':540}, {'x':0,'y':560,'width':669,'height':540}])
                inspect('simulated-tabletop', 'tabletop', 669, 1100)
                segments(None)
                inspect('unfolded-return', 'wide', 669, 885)
                for workflow in ('Monthly report', 'Expense reimbursement', 'Purchase order'):
                    before=receipt.inner_text()
                    page.get_by_role('radio', name=workflow, exact=True).click()
                    page.wait_for_function("old=>{const a=[...document.querySelectorAll('p')].filter(n=>n.textContent.startsWith('Layout fixture pass '));return a.length===1&&a[0].textContent!==old}",arg=before)
                    expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state', 'notRunning')
                    # A completed backend rerun may still have a stale widget
                    # owner in the browser until reconciliation finishes.
                    expect(notes).to_have_count(1)
                    expect(page.locator('.st-key-workflow_mode [role=radio][aria-checked=true]')).to_have_text(workflow)
                    expect(page.locator('.epc-workspace')).to_have_count(1)
                    expect(notes).to_be_visible()
                    if notes.input_value()!=VALUE:
                        commit_notes()
                    expect(page.locator('[data-stale="true"]')).to_have_count(0)
                    inspect(workflow.lower().replace(' ', '-'), 'compact', 382, 600)
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=20)
            (OUT / 'results.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps({'passed': len(evidence['checks']), 'output': str(OUT)}))


if __name__ == '__main__':
    main()
