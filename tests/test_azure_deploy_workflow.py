"""The Deploy to Azure workflow: after Tests on main only, off until enabled, no names.

A source-level guard; only a real run signed in as the deploy identity can
prove the Azure side. scripts/azure_release.py has its own tests.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/azure-deploy.yml"
SECRETS = {
    "AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP", "AZURE_APP", "AZURE_BACKUP_JOB", "AZURE_PUBLIC_ORIGIN",
}


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_runs_only_after_tests_or_by_hand():
    content = text()
    assert "  workflow_run:\n    workflows: [Tests]\n    types: [completed]\n    branches: [main]\n" in content
    assert "  workflow_dispatch:\n" in content
    assert not re.search(r"(?m)^  (?:push|pull_request|pull_request_target|schedule):", content)


def test_automatic_runs_need_the_switch_a_green_push_on_main_and_this_repository():
    condition = text().split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
    assert "github.event_name == 'workflow_dispatch' ||" in condition
    for clause in (
        "vars.AZURE_DEPLOY_ENABLED == 'true'",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
    ):
        assert clause in condition


def test_one_deploy_at_a_time_never_cancelled():
    content = text()
    assert "concurrency:\n  group: azure-deploy\n  cancel-in-progress: false\n" in content


def test_least_privilege_and_the_azure_environment():
    content = text()
    assert content.count("permissions:") == 2
    assert "\npermissions:\n  contents: read\n\n" in content
    assert ("    permissions:\n      contents: read\n      actions: read\n      id-token: write\n"
            in content)
    assert "    environment: azure\n" in content
    assert content.count("persist-credentials: false") == 2


def test_azure_names_come_only_from_the_environment_secrets():
    content = text()
    assert set(re.findall(r"secrets\.([A-Z_]+)", content)) == SECRETS
    assert "azurecr.io" not in content
    assert not re.search(r"\b(?:az|docker) ", content.split("steps:", 1)[1].replace("azure/login", ""))


def test_inputs_reach_the_script_through_environment_variables():
    content = text()
    for line in content.splitlines():
        if line.strip().startswith("run:"):
            assert "${{" not in line, line
    assert "REQUESTED_COMMIT: ${{ inputs.commit }}" in content
    assert 'python3 tool/scripts/azure_release.py choose --commit "$REQUESTED_COMMIT"' in content
    assert "RELEASE_COMMIT: ${{ steps.choose.outputs.commit }}" in content
    assert ('python3 tool/scripts/azure_release.py deploy --commit "$RELEASE_COMMIT" --context build'
            in content)


def test_the_release_is_built_from_its_own_checkout_by_mains_script():
    content = text()
    assert "          ref: main\n          path: tool\n" in content
    assert "          ref: ${{ steps.choose.outputs.commit }}\n          path: build\n" in content
    assert content.count("if: steps.choose.outputs.commit != ''") == 2
    assert content.index("path: tool") < content.index("azure/login@v2") < content.index("id: choose")
