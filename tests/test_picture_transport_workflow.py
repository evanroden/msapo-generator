"""Transport-only changes must still run actual synthetic browser gates."""
from pathlib import Path
import re


def test_transport_and_protocol_changes_trigger_both_browser_workflows():
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    sections = re.split(r'^  (pull_request|push):\n', workflow.split('\npermissions:', 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    required = {'scripts/streamlit_forward_cache.py', 'tests/test_streamlit_forward_cache.py',
                'scripts/qa_wire_totals.py', 'tests/test_qa_wire_totals.py',
                'tests/test_picture_group_media.py', 'tests/test_picture_group_load_gate.py',
                'tests/test_picture_media_recovery.py',
                'tests/picture_group_load_gate_test.cjs', 'tests/test_picture_group_browser.py',
                'tests/test_picture_transport_workflow.py'}
    for event in ('push', 'pull_request'):
        assert required <= set(re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
    progress = workflow.split('\n  synthetic-progress-photos:', 1)[1].split('\n  synthetic-dom:', 1)[0]
    assert "EPC_REQUIRE_PICTURE_BROWSER: '1'" in progress
    assert 'python -m pytest tests/test_picture_group_browser.py -q' in progress


def test_progress_setup_and_tests_have_separate_bounded_budgets():
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    progress = workflow.split('\n  synthetic-progress-photos:', 1)[1].split('\n  synthetic-history:', 1)[0]
    assert '    timeout-minutes: 45\n' in progress
    steps = re.split(r'^      - name: ', progress, flags=re.MULTILINE)[1:]
    setup, browser, evidence = steps
    assert not re.search(r'^        if:', setup, flags=re.MULTILINE)
    assert not re.search(r'^        if:', browser, flags=re.MULTILINE)
    assert setup.startswith('Install locked app and native Progress photos harness\n')
    assert '        timeout-minutes: 20\n' in setup
    assert 'sudo apt-get update -qq' in setup
    assert 'sudo apt-get install -y --no-install-recommends libreoffice-writer' in setup
    assert 'python -m pip install -r requirements-dev.lock' in setup
    assert 'python scripts/patch_streamlit_frontend.py' in setup
    assert 'python -m pip install playwright==1.58.0' in setup
    assert 'python -m playwright install --with-deps chromium webkit' in setup
    assert '        timeout-minutes: 15\n' in browser
    assert "EPC_REQUIRE_PICTURE_BROWSER: '1'" in browser
    assert browser.split('        run: |\n', 1)[1].splitlines() == [
        '          set -e',
        '          python -m pytest tests/test_picture_group_browser.py -q',
        '          python scripts/qa_progress_photo_journey.py',
    ]
    assert '        if: always()\n' in evidence
    assert '        timeout-minutes: 3\n' in evidence
    assert 'uses: actions/upload-artifact@v4' in evidence
    assert 'path: test-artifacts/progress-photo-journey/' in evidence
    assert 'continue-on-error' not in progress
