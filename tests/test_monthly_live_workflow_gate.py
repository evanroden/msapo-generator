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
    assert "MONTHLY_QA_RUN_LABEL=first python -m scripts.qa_monthly_live" in text
    assert "MONTHLY_QA_RUN_LABEL=second python -m scripts.qa_monthly_live" in text
    assert text.index("MONTHLY_QA_RUN_LABEL=first") < text.index("MONTHLY_QA_RUN_LABEL=second")


def test_live_gate_includes_a_distinct_same_browser_two_tab_reset_rejection():
    """Not a source substitute for the real scheduled Chromium live pass."""
    script = (Path(__file__).resolve().parents[1] / "scripts/qa_monthly_live.py").read_text()
    assert 'verify_stale_second_tab_after_reset(ctx, page, final_state)' in script
    assert 'if RUN_LABEL == "second":' in script
    assert 'stale second-tab edit cannot repopulate reset namespace' in script
    assert 'await_fixture_state(other, "known-value prefill"' in script
    assert 'other.reload(wait_until="domcontentloaded"' in script
    assert 'reset_fixture(primary, loaded, "other-tab-still-mounted")' in script
    assert 'observed_primary["revision"] == 0' in script
