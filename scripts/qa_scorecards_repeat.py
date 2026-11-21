"""Hosted synthetic Scorecards round trips; one native click per step."""
import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_warning_routes as fixture
from scripts.monthly_sequential_navigation import navigate_sections, section_order


def exercise(engine, scenario, repeat):
    from playwright.sync_api import expect

    results = []
    with engine.launch(headless=True) as browser:
        with browser.new_context(viewport=fixture.MODES['wide-pointer']) as context:
            context.add_cookies([{'name': 'epc_device_id', 'value': secrets.token_hex(16), 'url': fixture.URL}])
            external = []

            def network(route):
                addr = urlparse(route.request.url)
                if addr.scheme in {'data', 'blob'} or addr.hostname == '127.0.0.1' and addr.port == fixture.PORT:
                    route.continue_()
                else:
                    external.append(addr.hostname)
                    route.abort()

            context.route('**/*', network)
            page = context.new_page()
            page.set_default_timeout(30000)
            diagnostics = []
            errors = []
            page.on('console', lambda message: diagnostics.append(message.text) if message.text.startswith('W01 ') else None)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(fixture.URL, wait_until='domcontentloaded')
            fixture.select_native_option(page, page.get_by_role('combobox', name='Synthetic historical scenario', exact=True), scenario)
            page.get_by_role('button', name='Load synthetic historical report with unresolved warnings', exact=True).click()
            state = fixture.receipt(page)
            assert state['scenario'] == scenario and not state['blocked_external_attempts']
            expect(page.locator('.epc-section-progress')).to_have_attribute('data-section', 'monthly_cover')
            navigate_sections(page, 'monthly_scorecards')
            ids = [entry['id'] for entry in section_order(page)]
            assert ids[ids.index('monthly_scorecards') + 1] == 'monthly_mbcx'
            for iteration in range(repeat):
                for origin, target in (('monthly_scorecards', 'monthly_mbcx'), ('monthly_mbcx', 'monthly_scorecards')):
                    diagnostics.clear()
                    try:
                        expect(page.locator('.epc-section-progress')).to_have_attribute('data-section', origin)
                        navigate_sections(page, target)
                        results.append({'iteration': iteration + 1, 'target': target, 'passed': True})
                    except Exception as exc:
                        results.append({'iteration': iteration + 1, 'target': target, 'passed': False,
                                        'error': str(exc), 'diagnostics': list(diagnostics)})
                        # No reactivation after a failure; another fixture is independent.
                        return results, external, errors
            return results, external, errors


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Hosted synthetic CI only')
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument('--repeat', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.repeat > 0 and args.repeat % len(fixture.SCENARIOS) == 0
    report = {}
    with tempfile.TemporaryDirectory(prefix='w01-synthetic-') as temp:
        base = Path(temp)
        (base / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        with fixture.controller_environment(base):
            env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE='1', EPC_MONTHLY_WARNING_ROUTES_TASK='1',
                       ANTHROPIC_API_KEY='', SMARTSHEET_API_MODE='disabled', PYTHONDONTWRITEBYTECODE='1')
            for key in tuple(env):
                if key.startswith('EPC_MONTHLY_') and (key.endswith('_TASK') or key == 'EPC_MONTHLY_DOM_APPTEST') and key != 'EPC_MONTHLY_WARNING_ROUTES_TASK':
                    env.pop(key)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.with_suffix('.streamlit.log').open('w') as log:
                process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'tests/fixtures/workspaces/monthly_app.py',
                                            '--server.address', '127.0.0.1', '--server.port', str(fixture.PORT),
                                            '--server.headless', 'true', '--browser.gatherUsageStats', 'false'],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError('Synthetic server stopped')
                        try:
                            with urlopen(fixture.URL + '/_stcore/health', timeout=1) as response:
                                if response.status == 200:
                                    break
                        except OSError:
                            time.sleep(.1)
                    else:
                        raise RuntimeError('Synthetic server not ready')
                    with sync_playwright() as p:
                        for name in ('chromium', 'webkit'):
                            cases = report[name] = {}
                            for scenario in fixture.SCENARIOS:
                                try:
                                    steps, external, errors = exercise(getattr(p, name), scenario, args.repeat // len(fixture.SCENARIOS))
                                    cases[scenario] = {'steps': steps, 'external': external, 'errors': errors}
                                except Exception as exc:
                                    cases[scenario] = {'steps': [], 'setup_error': str(exc)}
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    args.output.write_text(json.dumps(report, indent=2))
    complete = True
    for name, cases in report.items():
        steps = [step for case in cases.values() for step in case['steps']]
        failures = sum(not step['passed'] for step in steps)
        print(f'W01 {name}: {failures}/{len(steps)} failed; planned {2 * args.repeat} clicks', flush=True)
        complete &= len(steps) == 2 * args.repeat and not failures and all(
            not (case.get('external') or case.get('errors') or case.get('setup_error')) for case in cases.values())
    assert complete and len(report) == 2, report


if __name__ == '__main__':
    main()
