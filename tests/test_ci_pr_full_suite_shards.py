"""Guard the PR full-suite fallback against silently running one giant job."""

from pathlib import Path
import re


WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml")


def jobs() -> dict[str, str]:
    text = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n", 1)[1]
    matches = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]*):\n", text))
    return {
        match.group(1): text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        for index, match in enumerate(matches)
    }


def test_pr_selector_runs_before_costly_test_jobs():
    select = jobs()["select-pr-tests"]
    assert "if: github.event_name == 'pull_request'" in select
    assert "fetch-depth: 0" in select
    assert "scripts/ci_select_tests.py" in select
    assert 'echo "mode=affected"' in select
    assert 'echo "mode=full"' in select


def test_affected_prs_use_only_the_single_job():
    affected = jobs()["pytest"]
    assert "needs: select-pr-tests" in affected
    assert "outputs.mode == 'affected'" in affected
    assert "test -s selected-tests.txt" in affected
    assert "python -m pytest -q" in affected


def test_full_pr_fallback_and_main_push_use_the_same_five_shards():
    shards = jobs()["pytest-shards"]
    assert "needs: select-pr-tests" in shards
    assert "always() && !cancelled()" in shards
    assert "github.event_name == 'push'" in shards
    assert "outputs.mode == 'full'" in shards
    assert "needs.select-pr-tests.result == 'success'" in shards
    assert "matrix:" in shards
    assert "shard: [0, 1, 2, 3, 4]" in shards
    assert "scripts/ci_full_test_shards.py" in shards
    assert "test -s selected-tests.txt" in shards


def test_single_required_result_gates_both_pr_selection_modes_and_main():
    complete = jobs()["complete"]
    assert "name: Tests complete" in complete
    assert "needs: [select-pr-tests, pytest, pytest-shards, container, monthly-report-resources]" in complete
    assert 'test "$PR_SELECTION" = success' in complete
    assert 'if [ "$PR_MODE" = full ]; then' in complete
    assert 'test "$PR_MODE" = affected' in complete
    assert 'test "$FULL_SHARDS" = success' in complete
    assert 'test "$PR_PYTEST" = success' in complete
