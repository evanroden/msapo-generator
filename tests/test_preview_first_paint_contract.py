"""The new preview gate adds coverage without rewriting frozen native budgets."""
from pathlib import Path

from test_ci_native_test_budget import parse_jobs, validate_workflow

ROOT = Path(__file__).resolve().parents[1]


def test_preview_mount_gate_preserves_all_existing_native_jobs():
    text = (ROOT / '.github/workflows/adaptive-workspaces.yml').read_text()
    validate_workflow(text)
    job = ''.join(parse_jobs(text)['preview-first-paint'])
    for required in ('timeout-minutes: 30', 'timeout-minutes: 20',
                     'timeout-minutes: 6', '--minutes 5', 'timeout-minutes: 3',
                     'python scripts/qa_preview_first_paint.py', 'if: always()',
                     'playwright==1.58.0', 'chromium webkit',
                     'path: test-artifacts/adaptive-workspaces/preview-first-paint/'):
        assert required in job
    assert 'continue-on-error' not in job
    for path in ('scripts/qa_preview_first_paint.py',
                 'tests/test_preview_first_paint_contract.py'):
        assert text.count("- '" + path + "'") == 2
