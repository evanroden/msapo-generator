"""The public Chromium acceptance workflow must not fight a new deployment.

This is a source-level guard; only a real successful workflow_run can prove
that Actions' event context and production browser behave as intended.
"""
from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/monthly-live-qa.yml"


def test_live_chromium_runs_serially_only_for_just_tested_main_commit():
    text = WORKFLOW.read_text()
    assert "workflow_run:" in text and "workflows: [Tests]" in text
    assert "group: monthly-isolated-live-production" in text
    assert "cancel-in-progress: false" in text
    assert "head_branch == 'main'" in text
    assert "conclusion == 'success'" in text
    assert "github.event.workflow_run.head_sha == github.sha" in text
    assert "Confirm original tested SHA still equals latest main" in text
    assert 'git ls-remote origin refs/heads/main' in text
    assert 'current" = "$TESTED_SHA' in text
    assert "id: still-current" in text
    assert text.count("if: steps.still-current.outputs.run == 'true'") >= 3
    assert "MONTHLY_QA_EXPECTED_COMMIT: ${{ github.event.workflow_run.head_sha }}" in text
    assert "if: always() && steps.still-current.outputs.run == 'true'" in text
    assert "python -m scripts.qa_monthly_live" in text
