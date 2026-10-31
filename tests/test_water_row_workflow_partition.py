"""Exact mandatory relocation; no acceptance command or original gate is lost."""
from pathlib import Path
import hashlib
import re
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_JOB = "  water-row-output:\n    runs-on: ubuntu-24.04\n    # Saved Water and row outputs have independent bounded workload.\n    # DOM25 + fresh Water8 + saved Water/rows8 = 41 native minutes total.\n    timeout-minutes: 15\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 2\n      - uses: actions/setup-python@v5\n        with:\n          python-version: '3.12'\n          cache: pip\n          cache-dependency-path: requirements-dev.lock\n      - uses: actions/setup-node@v4\n        with:\n          node-version: '22'\n      - name: Install locked app and saved Water/row browser harness\n        timeout-minutes: 5\n        run: |\n          sudo python3 scripts/ci_ubuntu_mirror_priority.py\n          sudo apt-get update -qq\n          sudo apt-get install -y --no-install-recommends libreoffice-writer libreoffice-calc\n          python -m pip install -r requirements-dev.lock\n          python scripts/patch_streamlit_frontend.py\n          python -m pip install playwright==1.58.0\n          python -m playwright install --with-deps chromium webkit\n      - name: Apply exact locked scalar date compatibility repair\n        timeout-minutes: 9\n        run: |\n          python scripts/ci_native_test_budget.py --minutes 8 <<'NATIVE_TEST'\n          python scripts/patch_streamlit_date_input.py\n          NATIVE_TEST\n      - name: Water page management across desktop and narrow browser with actual output\n        if: ${{ !cancelled() }}\n        env:\n          EPC_MONTHLY_WATER_TASK: '1'\n        timeout-minutes: 9\n        run: |\n          python scripts/ci_native_test_budget.py --minutes 8 <<'NATIVE_TEST'\n          python scripts/qa_water_page_journey.py\n          NATIVE_TEST\n      - name: Native proposal and onsite row editing with actual output\n        if: ${{ !cancelled() }}\n        env:\n          EPC_MONTHLY_ROW_TASK: '1'\n        timeout-minutes: 9\n        run: |\n          python scripts/ci_native_test_budget.py --minutes 8 <<'NATIVE_TEST'\n          python scripts/qa_report_row_cards.py\n          NATIVE_TEST\n      - name: Preserve saved Water and row output evidence including first failures\n        if: always()\n        timeout-minutes: 2\n        uses: actions/upload-artifact@v4\n        with:\n          name: water-row-output-browser-evidence-${{ github.run_attempt }}\n          path: |\n            test-artifacts/water-page-journey/\n            test-artifacts/report-row-cards/\n          retention-days: 7\n          if-no-files-found: error\n\n"
ORIGINAL_WORKFLOW_SHA256 = '93cb2a0a6e15697491bdd4ec857f6a9d23da0ddade28c88f4f4ecac1bca4d9d3'
COMMANDS = ('qa_water_page_journey.py', 'qa_report_row_cards.py')

def validate_partition(text):
    parts = re.split(r'(?=^  [a-z][a-z-]+:\n)', text.split('jobs:\n', 1)[1], flags=re.M)
    jobs = {re.match(r'  ([\w-]+):', p).group(1):p for p in parts if p.strip()}
    assert 'water-row-output' in jobs
    assert jobs['water-row-output'] == EXPECTED_JOB
    # Reconstruct only the two approved relocations and compare the COMPLETE
    # original workflow, retaining every other gate/setup/pin/command/env byte.
    new_steps = re.split(r'(?=^      - )', EXPECTED_JOB, flags=re.M)
    moved = [s for s in new_steps if any('python scripts/'+c in s for c in COMMANDS)]
    assert len(moved) == 2
    for command in COMMANDS:
        assert text.count('python scripts/'+command) == 1
        assert command not in jobs['synthetic-dom']
    restored = jobs['synthetic-dom']
    marker = '      - name: Select explicitly requested one-shot native owner diagnostic\n'
    assert restored.count(marker) == 1
    originals = ''.join(s.replace('timeout-minutes: 9', 'timeout-minutes: 26').replace('--minutes 8', '--minutes 25') for s in moved)
    restored = restored.replace(marker, originals+marker)
    marker = '            test-artifacts/compact-contact-journey/\n'
    assert restored.count(marker) == 1
    restored = restored.replace(marker, '            test-artifacts/water-page-journey/\n            test-artifacts/report-row-cards/\n'+marker)
    reconstructed = text.replace(jobs['synthetic-dom'],restored).replace(EXPECTED_JOB,'')
    reconstructed = reconstructed.replace('# This lane retains its own 8-minute native ceiling; DOM remains25.', '# Native aggregate allowance rises from 25 to 33 minutes across these two jobs.')
    assert hashlib.sha256(reconstructed.encode()).hexdigest() == ORIGINAL_WORKFLOW_SHA256
    return jobs


def test_exact_workflow_partition_preserves_all_commands_pins_and_gates():
    jobs = validate_partition((ROOT/'.github/workflows/adaptive-workspaces.yml').read_text())
    assert len(jobs) == 14  # 13 previous Adaptive jobs plus mandatory Water/rows.
    assert '    if:' not in jobs['water-row-output'].split('    steps:',1)[0]
    assert 'continue-on-error' not in jobs['water-row-output']
    assert set(re.findall(r'--minutes (\d+)', jobs['water-row-output'])) == {'8'}
    assert set(re.findall(r'--minutes (\d+)', jobs['synthetic-dom'])) == {'25'}
    assert set(re.findall(r'--minutes (\d+)', jobs['fresh-water'])) == {'8'}
    # Only runtime installation repeats; acceptance commands remain exactly once.
    for command in COMMANDS:
        source=(ROOT/'scripts'/command).read_text()
        assert 'qa.main()' in source
    lifecycle=(ROOT/'scripts/qa_monthly_adaptive.py').read_text()
    assert 'tempfile.TemporaryDirectory(prefix="monthly-dom-synthetic-")' in lifecycle
    assert 'playwright.chromium' in lifecycle and 'playwright.webkit' in lifecycle


@pytest.mark.parametrize(('old','new'), [
    ('  water-row-output:', '  optional-water-row:'),
    ('    timeout-minutes: 15', '    timeout-minutes: 16'),
    ('        timeout-minutes: 5', '        timeout-minutes: 20'),
    ('--minutes 8', '--minutes 9'),
    ('--minutes 25', '--minutes 26'),
    ('chromium webkit', 'chromium'),
    ('playwright==1.58.0', 'playwright'),
    ("EPC_MONTHLY_WATER_TASK: '1'", "EPC_MONTHLY_WATER_TASK: '0'"),
    ("EPC_MONTHLY_ROW_TASK: '1'", "EPC_MONTHLY_ROW_TASK: '0'"),
    ('python scripts/qa_report_row_cards.py', 'true'),
    ('python scripts/qa_water_page_journey.py', 'python scripts/qa_water_page_journey.py --skip'),
    ('if: ${{ !cancelled() }}', 'if: success()'),
    ('if: always()', 'if: success()'),
    ('            test-artifacts/report-row-cards/', '            test-artifacts/other/'),
    ('retention-days: 7', 'retention-days: 1'),
    ('if-no-files-found: error', 'if-no-files-found: warn'),
])
def test_partition_rejects_lost_or_weakened_coverage(old,new):
    text=(ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    assert old in text
    with pytest.raises(AssertionError): validate_partition(text.replace(old,new))


def test_partition_rejects_duplicate_suite_or_conditional_job():
    text=(ROOT/'.github/workflows/adaptive-workspaces.yml').read_text()
    for changed in (text.replace('python scripts/qa_report_row_cards.py','python scripts/qa_report_row_cards.py\n          python scripts/qa_report_row_cards.py'), text.replace('  water-row-output:\n','  water-row-output:\n    if: false\n')):
        with pytest.raises(AssertionError):validate_partition(changed)
