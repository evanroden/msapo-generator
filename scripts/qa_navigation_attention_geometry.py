"""Standalone synthetic hit-target proof using the shipped navigation CSS.

This complements, never replaces, full native report journeys. No report state,
external services, forced clicks, retries or timing sleeps are involved.
"""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts/warning-routes/attention-geometry'


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    css = (ROOT / 'app/workspace_initial.css').read_text()
    with sync_playwright() as playwright:
        for name in ('chromium', 'webkit'):
            browser = getattr(playwright, name).launch()
            try:
                for width in (320, 390, 1365):
                    page = browser.new_page(viewport={'width': width, 'height': 844})
                    page.set_content('<style>body{margin:16px;font:16px sans-serif}' + css + '</style>'
                        '<div class="st-key-epc_workspace_monthly"><span class="epc-section-navigation">'
                        '<button class="epc-section-back">Back</button>'
                        '<span class="epc-navigation-attention" hidden></span>'
                        '<span class="epc-section-progress">Cover</span>'
                        '<button class="epc-section-next">Next</button></span></div>')
                    page.evaluate('''() => {
                        window.hits = [];
                        for (const button of document.querySelectorAll('button'))
                            button.addEventListener('click', event => window.hits.push({
                                control:button.className, trusted:event.isTrusted}));
                    }''')
                    controls = [page.locator('.epc-section-' + key) for key in ('back', 'next')]
                    baseline = [control.bounding_box() for control in controls]
                    for count in (0, 1, 4, 999):
                        for control, initial in zip(controls, baseline):
                            point = {'x': initial['x'] + initial['width']/2,
                                     'y': initial['y'] + initial['height']/2}
                            page.mouse.move(**point)
                            page.mouse.down()
                            # A synthetic standalone receipt update between the
                            # native down/up reproduces the first failed gesture.
                            page.evaluate('''count => {
                                const receipt=document.querySelector('.epc-navigation-attention');
                                receipt.textContent=count ? `${count} items need attention` : '';
                                receipt.hidden=!count;
                                document.querySelector('.epc-section-progress').textContent=
                                    count ? '4 of 14 · Monthly Scorecards' : 'Cover';
                            }''', count)
                            actual = control.bounding_box()
                            assert actual == initial, (name, width, count, initial, actual)
                            assert actual['x'] >= 0 and actual['x'] + actual['width'] <= width
                            page.mouse.up()
                    hits = page.evaluate('window.hits')
                    assert hits == [{'control': 'epc-section-' + key, 'trusted': True}
                                    for _ in range(4) for key in ('back', 'next')], hits
                    page.screenshot(path=str(OUT / f'{name}-{width}.png'))
                    results.append({'engine': name, 'width': width, 'native_clicks': len(hits),
                                    'stable_bounds': baseline})
                    page.close()
            finally:
                browser.close()
    (OUT / 'results.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
