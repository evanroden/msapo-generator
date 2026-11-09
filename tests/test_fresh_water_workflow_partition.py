"""Fresh Water remains mandatory, with its own bounded two-engine workload."""
from pathlib import Path
import re


WORKFLOW = Path('.github/workflows/adaptive-workspaces.yml')


def jobs():
    text = WORKFLOW.read_text().split('\njobs:', 1)[1]
    parts = re.split(r'^  ([\w-]+):\n', text, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2]))


def test_partition_preserves_all_adaptive_jobs_and_runs_fresh_water_exactly_once():
    lanes = jobs()
    assert {'preview-first-paint', 'synthetic-work-order-rows', 'literal-labels',
            'synthetic-progress-photos', 'synthetic-history', 'cover-first-display',
            'synthetic-dom', 'synthetic-contact', 'training-date',
            'monthly-site-geometry', 'workflow-shell-width', 'fresh-water'} <= lanes.keys()
    command = 'python scripts/qa_water_fresh_page_journey.py'
    assert WORKFLOW.read_text().count(command) == 1
    assert command in lanes['fresh-water']
    assert command not in lanes['synthetic-dom']
    assert '    timeout-minutes: 60\n' in lanes['synthetic-dom']
    budgets = re.findall(r'ci_native_test_budget.py --minutes (\d+)', lanes['synthetic-dom'])
    assert budgets and set(budgets) == {'25'}


def test_fresh_water_has_pinned_dependencies_both_engines_and_bounded_budgets():
    lane = jobs()['fresh-water']
    assert '    runs-on: ubuntu-24.04\n' in lane
    assert '    timeout-minutes: 15\n' in lane
    assert 'continue-on-error' not in lane
    assert not re.search(r'^    (if|needs):', lane, re.MULTILINE)
    for exact in ('uses: actions/checkout@v4', 'fetch-depth: 2',
                  'uses: actions/setup-python@v5', "python-version: '3.12'",
                  'cache: pip', 'cache-dependency-path: requirements-dev.lock',
                  'uses: actions/setup-node@v4', "node-version: '22'"):
        assert exact in lane
    setup, native, upload = re.split(r'^      - name: ', lane, flags=re.MULTILINE)[1:]
    assert '        timeout-minutes: 5\n' in setup
    assert not re.search(r'^        if:', setup + native, re.MULTILINE)
    assert setup.split('        run: |\n', 1)[1].splitlines() == [
        '          sudo python3 scripts/ci_ubuntu_mirror_priority.py',
        '          sudo apt-get update -qq',
        '          sudo apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc',
        '          python -m pip install -r requirements-dev.lock',
        '          python scripts/patch_streamlit_frontend.py',
        '          python -m pip install playwright==1.58.0',
        '          python -m playwright install --with-deps chromium webkit',
    ]
    assert '        timeout-minutes: 9\n' in native
    assert native.split('        run: |\n', 1)[1].splitlines() == [
        "          python scripts/ci_native_test_budget.py --minutes 8 <<'NATIVE_TEST'",
        '          python scripts/patch_streamlit_date_input.py',
        '          python scripts/qa_water_fresh_page_journey.py',
        '          NATIVE_TEST',
    ]
    assert '        if: always()\n' in upload
    assert '        timeout-minutes: 2\n' in upload
    for exact in ('uses: actions/upload-artifact@v4',
                  'name: fresh-water-browser-evidence-${{ github.run_attempt }}',
                  'path: test-artifacts/water-fresh-page-journey/',
                  'retention-days: 7', 'if-no-files-found: error'):
        assert exact in upload
    assert 'water-fresh-page-journey/' not in jobs()['synthetic-dom']


def test_original_fresh_water_harness_still_exercises_both_native_engines():
    source = Path('scripts/qa_water_fresh_page_journey.py').read_text()
    assert 'for name, browser_type in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):' in source
