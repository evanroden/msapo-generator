"""Every PR/push CI workflow must coalesce superseded queued runs."""

from pathlib import Path
import re


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
EXEMPT = {
    "monthly-live-qa.yml",
    "shared-archive-redeploy-readonly.yml",
    "shared-fixture-redeploy-readonly.yml",
}
EXPECTED_GROUP = "  group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && format('pr-{0}', github.event.pull_request.number) || github.event_name == 'push' && github.ref || github.run_id }}"
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
        assert EXPECTED_GROUP in content, path.name
        assert EXPECTED_CANCEL in content, path.name

    assert checked, "Expected at least one PR/push workflow"
