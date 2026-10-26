"""Late preview mount must preserve the next native button's pointer target.

Real Streamlit DOM and Chromium/WebKit, with a synthetic PDF and separate gates
on preview HTML and adapter/CSS arrival. No genuine report or remote app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts' / 'adaptive-workspaces' / 'preview-first-paint'
URL = 'http://127.0.0.1:8528'


def frames(page):
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def geometry(page, button_key):
    return page.evaluate('''buttonKey => {
        const cover = document.querySelector('.st-key-epc_pair_monthly_cover');
        const button = document.querySelector('.st-key-' + buttonKey + ' button');
        const reference = cover.querySelector('.st-key-epc_reference_monthly_cover');
        return {cover:cover.getBoundingClientRect().toJSON(),
            button:button.getBoundingClientRect().toJSON(),
            reference:reference.getBoundingClientRect().toJSON(),
            scrollTop:document.querySelector('[data-testid="stMain"]').scrollTop};
    }''', button_key)


def exercise(engine, name, late, target, press=True):
    browser = engine.launch(headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    evidence = {'late': late, 'target': target, 'runs': [], 'browser_errors': errors}
    button_key = 'render_outputs' if target == 'outside' else 'clear_activity'
    button_name = 'Render synthetic outputs' if target == 'outside' else 'Clear Activity'
    receipt = 'Output renders: 1' if target == 'outside' else 'Activity clears: 1'
    url = URL + ('?delay_adapter=1' if late == 'adapter' else '')
    try:
        for label in ('cold', 'reload'):
            if label == 'cold':
                page.goto(url, wait_until='domcontentloaded')
            else:
                page.reload(wait_until='domcontentloaded')
            page.wait_for_function('window.__previewMountWaiting === true')
            button = page.get_by_role('button', name=button_name, exact=True)
            expect(button).to_be_visible()
            if late == 'adapter':
                page.wait_for_function('window.__workspaceMountWaiting === true')
                page.evaluate('window.__releasePreviewMount()')
                expect(page.locator('.report-preview')).to_have_count(1)
                expect(page.locator('.epc-workspace')).to_have_count(0)
            else:
                page.wait_for_selector('.st-key-epc_pair_monthly_activity .epc-workspace-editor')
                page.wait_for_function('document.querySelector(".epc-workspace")?.dataset.epcMode === "wide"')
                expect(page.locator('.report-preview')).to_have_count(0)
            # A reader below Cover, before its viewer has mounted. Set only the
            # initial reading position; never scroll between down and up.
            button.evaluate('''node => {
                document.querySelector('[data-testid="stMain"]').scrollTop +=
                    node.getBoundingClientRect().top - 400;
            }''')
            frames(page)
            page.evaluate('''buttonKey => {
                window.__previewPointerEvents = [];
                const button = document.querySelector('.st-key-' + buttonKey + ' button');
                for (const type of ['pointerdown', 'pointerup', 'click'])
                    button.addEventListener(type, () => window.__previewPointerEvents.push(type));
            }''', button_key)
            before = geometry(page, button_key)
            page.screenshot(path=str(OUT / f'{name}-{label}-before.png'))
            x = before['button']['x'] + before['button']['width'] / 2
            y = before['button']['y'] + before['button']['height'] / 2
            page.mouse.move(x, y)
            if press:
                page.mouse.down()
            if late == 'adapter':
                page.evaluate('window.__releaseWorkspaceMount()')
                page.wait_for_function('window.__workspaceMountReleased === true')
            else:
                page.evaluate('window.__releasePreviewMount()')
                expect(page.locator('.report-preview')).to_have_count(1)
            if not press:
                # No gesture holds the first layout back here. The reader's
                # pointer rests on the action while the wide layout lands.
                page.wait_for_function('document.querySelector(".epc-workspace")?.dataset.epcMode === "wide"')
            frames(page)
            after = geometry(page, button_key)
            if not press:
                page.mouse.down()
            page.mouse.up()
            events = page.evaluate('window.__previewPointerEvents')
            run = {'load': label, 'press': press, 'before': before, 'after': after, 'events': events}
            evidence['runs'].append(run)
            page.screenshot(path=str(OUT / f'{name}-{label}-after.png'))
            assert abs(after['button']['y'] - before['button']['y']) <= 3, run
            if press:
                assert abs(after['cover']['height'] - before['cover']['height']) <= 3, run
                assert abs(after['scrollTop'] - before['scrollTop']) <= 3, run
            assert events == ['pointerdown', 'pointerup', 'click'], run
            # The native callback must arrive, not just a synthetic DOM event.
            expect(page.get_by_text(receipt, exact=True)).to_be_visible()
            page.wait_for_function('document.querySelector(".epc-workspace")?.dataset.epcMode === "wide"')
            # The outside action leaves Cover offscreen. After recording the
            # entire native click, expose it again for the real raster check;
            # production deliberately does not render invisible preview pages.
            if target == 'outside':
                page.locator('.st-key-epc_pair_monthly_cover').scroll_into_view_if_needed()
            image = page.locator('.report-preview img').first
            expect(image).to_have_js_property('complete', True)
            assert image.evaluate('node => node.naturalWidth > 0'), 'Real raster did not load'
        # Empty/text references stay short; reservation belongs only to viewers.
        empty = page.locator('.st-key-epc_reference_monthly_activity')
        assert empty.bounding_box()['height'] < 180
        assert not errors, errors
    except Exception as error:
        evidence['failure'] = str(error)
        page.screenshot(path=str(OUT / f'{name}-failure.png'))
        raise
    finally:
        (OUT / f'{name}.json').write_text(json.dumps(evidence, indent=2))
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    with tempfile.TemporaryDirectory(prefix='preview-first-paint-') as data:
        env = dict(os.environ, EPC_DATA_DIR=data, ANTHROPIC_API_KEY='test-key-not-used')
        with (OUT / 'streamlit.log').open('w') as log:
            process = subprocess.Popen([
                sys.executable, '-m', 'streamlit', 'run',
                'tests/fixtures/workspaces/preview_mount_app.py',
                '--server.address', '127.0.0.1', '--server.port', '8528',
                '--server.headless', 'true', '--browser.gatherUsageStats', 'false',
            ], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError('Synthetic preview fixture stopped')
                    try:
                        with urllib.request.urlopen(URL + '/_stcore/health', timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(.1)
                with sync_playwright() as playwright:
                    for engine, name in ((playwright.chromium, 'chromium'),
                                         (playwright.webkit, 'webkit')):
                        for late, target, press in (('preview', 'inside', True), ('adapter', 'inside', True),
                                                    ('adapter', 'outside', True), ('adapter', 'outside', False)):
                            label = name + '-' + late + '-' + target + ('' if press else '-hover')
                            try:
                                exercise(engine, label, late, target, press)
                            except Exception as error:
                                failures.append(label + ': ' + str(error))
            finally:
                process.terminate()
                process.wait(timeout=15)
    if failures:
        raise AssertionError('\n'.join(failures))


if __name__ == '__main__':
    main()
