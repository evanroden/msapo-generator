"""PR heads coalesce; each Tests push on main must retain its own queue slot."""

from pathlib import Path
import re


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
EXEMPT = {
    "monthly-live-qa.yml",
    "shared-archive-redeploy-readonly.yml",
    "shared-fixture-redeploy-readonly.yml",
}
EXPECTED_GROUP = "  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) || github.event_name == 'push' && github.ref || github.run_id }}"
EXPECTED_TESTS_GROUP = "  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) || github.event_name == 'push' && format('push-{0}-{1}', github.ref, github.sha) || github.run_id }}"
EXPECTED_CANCEL = "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}"


def test_pr_push_workflows_share_per_pr_or_ref_concurrency():
    checked = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name in EXEMPT:
            continue
        content = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^  (?:pull_request|push):", content):
            continue
        checked.append(path.name)
        assert "\nconcurrency:\n" in "\n" + content, path.name
        expected = EXPECTED_TESTS_GROUP if path.name in {"tests.yml", "monthly-simplicity.yml"} else EXPECTED_GROUP
        assert expected in content, path.name
        assert EXPECTED_CANCEL in content, path.name

    assert checked, "Expected at least one PR/push workflow"


def test_monthly_simplicity_main_pushes_keep_unique_pending_slots():
    """Two pushed main SHAs must not compete for one pending acceptance run."""
    workflow = (WORKFLOWS / "monthly-simplicity.yml").read_text(encoding="utf-8")
    group = next(line.strip() for line in workflow.splitlines() if line.startswith("  group: "))
    ref = "refs/heads/main"
    first_sha, second_sha = "a" * 40, "b" * 40

    # Synthetic GitHub concurrency fixtures model the two supported push keys.
    # A ref-only rule is the historical failure: newer queued pushes evict old.
    def pending_key(commit_sha):
        if "format('push-{0}-{1}', github.ref, github.sha)" in group:
            return f"push-{ref}-{commit_sha}"
        return ref

    assert pending_key(first_sha) != pending_key(second_sha), (
        "Monthly simplicity pushes for distinct main commits share a pending slot"
    )
    assert EXPECTED_CANCEL in workflow, "PR-only cancellation must stay in place"
