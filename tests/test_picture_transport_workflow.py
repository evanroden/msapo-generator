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
    assert 'run: python -m pytest tests/test_picture_group_browser.py -q' in progress
