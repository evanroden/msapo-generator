"""Offline bootstrap tests. No GitHub requests, permits or browser runs."""
import copy
import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts import qa_directory_retention_core_live as runner
from scripts import qa_directory_retention_core_live_bootstrap as bootstrap
from test_qa_directory_retention_core_live import identities, authority_case


@pytest.fixture
def job_case(authority_case):
    authority, responses = authority_case
    p = authority.reviewed
    p["job"] = "core_live"
    authority.metadata["GITHUB_JOB"] = "core_live"
    responses["/actions/runs/" + p["run_id"] + "/attempts/1/jobs?per_page=100"]["jobs"][0]["name"] = "core_live"
    responses["/pulls/800"]["body"] = runner.PERMIT_BEGIN + json.dumps(p) + runner.PERMIT_END
    return authority, responses


def test_observed_provenance_contains_real_measured_fields_and_fresh_challenge(job_case, monkeypatch):
    a, _ = job_case
    monkeypatch.setattr(bootstrap.secrets, "token_hex", lambda n: "e" * (2 * n))
    observed = bootstrap.observe_job(a, a.metadata, a.event, runner.measure_checkout())
    assert observed["job_id"] == a.reviewed["job_id"]
    assert observed["workflow_id"] == a.reviewed["workflow_id"]
    assert observed["head"] == a.reviewed["head"]
    assert observed["tree"] == a.reviewed["tree"]
    assert observed["harness_digests"] == a.reviewed["harness_digests"]
    assert observed["nonce"] == "e" * 64
    assert "deployment_id" not in observed and "expires_at" not in observed
    assert "invented-test-token" not in json.dumps(observed)


@pytest.mark.parametrize("drift", ["attempt", "job", "ref", "head", "main", "run", "duplicate-job", "fork"])
def test_observe_job_rejects_source_or_identity_drift(job_case, drift):
    a, responses = job_case
    if drift == "attempt": a.metadata["GITHUB_RUN_ATTEMPT"] = "2"
    elif drift == "job": a.metadata["GITHUB_JOB"] = "other"
    elif drift == "ref": a.metadata["GITHUB_REF"] = "refs/heads/main"
    elif drift == "head": responses["/pulls/800"]["head"]["sha"] = "f" * 40
    elif drift == "main": responses["/git/ref/heads/main"]["object"]["sha"] = "f" * 40
    elif drift == "run": responses["/actions/runs/" + a.reviewed["run_id"]]["status"] = "completed"
    elif drift == "fork": a.event["pull_request"]["head"]["repo"]["full_name"] = "other/fork"
    else:
        jobs = responses["/actions/runs/" + a.reviewed["run_id"] + "/attempts/1/jobs?per_page=100"]
        jobs["jobs"].append(dict(jobs["jobs"][0], id=112))
        jobs["total_count"] = 2
    with pytest.raises(runner.SafetyStop):
        bootstrap.observe_job(a, a.metadata, a.event, runner.measure_checkout())


def permit_body(p, deployment):
    return (runner.PERMIT_BEGIN + json.dumps(p) + runner.PERMIT_END
            + bootstrap.DEPLOY_BEGIN + json.dumps(deployment) + bootstrap.DEPLOY_END)


def test_poll_returns_only_exact_observed_job_and_deployment(job_case):
    a, responses = job_case
    observed = {k: v for k, v in a.reviewed.items() if k not in {"issued_at", "expires_at", "deployment_id", "deployment_evidence_sha256"}}
    responses["/pulls/800"]["body"] = permit_body(a.reviewed, a.deployment)
    permit, deployment = bootstrap.await_permit(a, observed)
    assert permit == a.reviewed and deployment == a.deployment


@pytest.mark.parametrize("bad", ["nonce", "tree", "job-id", "digest", "missing-deployment", "duplicate-permit", "unknown-field"])
def test_poll_does_not_arm_ambiguous_or_wrong_current_run(job_case, bad):
    a, responses = job_case
    observed = {k: v for k, v in a.reviewed.items() if k not in {"issued_at", "expires_at", "deployment_id", "deployment_evidence_sha256"}}
    p = copy.deepcopy(a.reviewed)
    if bad == "nonce": p["nonce"] = "f" * 64
    elif bad == "tree": p["tree"] = "f" * 40
    elif bad == "job-id": p["job_id"] = "999"
    elif bad == "digest": p["harness_digests"][runner.WORKFLOW_PATH] = "f" * 64
    elif bad == "unknown-field": p["unknown"] = True
    body = permit_body(p, a.deployment)
    if bad == "missing-deployment": body = runner.PERMIT_BEGIN + json.dumps(p) + runner.PERMIT_END
    if bad == "duplicate-permit": body += body
    responses["/pulls/800"]["body"] = body
    with pytest.raises(runner.SafetyStop):
        bootstrap.await_permit(a, observed)


def test_no_permit_wait_is_bounded_without_browser_or_execution(job_case, monkeypatch):
    a, responses = job_case
    observed = {k: v for k, v in a.reviewed.items() if k not in {"issued_at", "expires_at", "deployment_id", "deployment_evidence_sha256"}}
    responses["/pulls/800"]["body"] = "No authorization"
    clock = {"now": 0}
    monkeypatch.setattr(bootstrap.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(bootstrap.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    get = Mock(wraps=a._get)
    a._get = get
    execute = Mock()
    monkeypatch.setattr(runner, "execute", execute)
    with pytest.raises(runner.SafetyStop, match="bounded wait"):
        bootstrap.await_permit(a, observed)
    assert get.call_count == bootstrap.WAIT_SECONDS // bootstrap.POLL_SECONDS == 108
    assert 108 + 8 < runner.RESERVED_PERMIT_POLL_GETS
    execute.assert_not_called()


def test_bootstrap_get_cap_is_120_and_blocks_before_network():
    api = bootstrap.BootstrapGitHub("invented-secret", "123")
    api.get_count = 120
    api._opener = Mock()
    with pytest.raises(runner.SafetyStop, match="allocation"):
        api._get("/pulls/800")
    api._opener.open.assert_not_called()
    assert runner.RESERVED_PERMIT_POLL_GETS + runner.MAX_EXECUTION_GETS == 720


@pytest.mark.parametrize("bad", [None, "outside", "symlink", "oversize"])
def test_event_read_is_bounded_confined_and_no_follow(tmp_path, monkeypatch, bad):
    root = tmp_path / "runner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "RUNNER_TEMP_ROOT", root)
    metadata = {"RUNNER_TEMP": str(root)}
    event = root / "event.json"
    event.write_text('{"number":800}')
    if bad == "outside":
        event = tmp_path / "elsewhere.json"
        event.write_text("{}")
    elif bad == "symlink":
        event.unlink()
        event.symlink_to(tmp_path / "outside.json")
    elif bad == "oversize": event.write_bytes(b"x" * (runner.MAX_API_BYTES + 1))
    if bad:
        with pytest.raises((runner.SafetyStop, OSError)):
            bootstrap.read_event(metadata, str(event))
    else:
        assert bootstrap.read_event(metadata, str(event)) == {"number": 800}


def test_concrete_arm_requires_challenge_and_fresh_api_not_callback(job_case):
    a, responses = job_case
    assert not a.armed
    with pytest.raises(runner.SafetyStop):
        a.arm("wrong")
    assert not a.armed
    a.arm(a.reviewed["nonce"])
    assert a.armed
    responses["/pulls/800"]["body"] = "revoked"
    with pytest.raises(runner.SafetyStop):
        a.check_current_state()


def test_workflow_installs_before_poll_and_has_no_unscoped_triggers_or_write_permissions():
    text = (runner.ROOT / runner.WORKFLOW_PATH).read_text()
    assert text.index('pip install') < text.index('qa_directory_retention_core_live_bootstrap.py')
    for required in ('pull_request:', 'types: [opened, synchronize, reopened]', 'github.event.pull_request.number == 800',
                     'github.run_attempt == 1', 'persist-credentials: false', 'pull-requests: read', 'actions: read',
                     'contents: read', 'playwright==1.58.0', 'requirements-dev.lock', 'timeout-minutes: 26',
                     'name: core_live', 'ref: ${{ github.event.pull_request.head.sha }}', 'github.run_id'):
        assert required in text
    for forbidden in ('workflow_dispatch', 'pull_request_target', 'push:', ': write', 'prodoptin', 'qa_directory_retention_native'):
        assert forbidden not in text
    assert 'core_live_bootstrap' in str(runner.HARNESS_FILES)
    assert runner.WORKFLOW_PATH in runner.HARNESS_FILES


def test_bootstrap_publishes_challenge_artifact_before_wait_and_arm():
    text = (runner.ROOT / runner.WORKFLOW_PATH).read_text()
    assert text.index('bootstrap.py --prepare') < text.index('name: Publish challenge artifact') < text.index('bootstrap.py --execute')
    assert 'steps.prepare.outputs.job_id' in text
    assert 'group: monthly-isolated-live-production' in text
    assert 'cancel-in-progress: false' in text
    source = inspect.getsource(bootstrap.execute_prepared)
    assert source.index('await_permit(') < source.index('authority.arm(') < source.index('runner.execute(')
    assert 'os.environ.pop("GITHUB_TOKEN", "")' in inspect.getsource(bootstrap.main)
    assert 'exist_ok=False' in inspect.getsource(bootstrap.prepare)
    assert '"failure_type"' in source and '"stage"' in source and '"reason"' in source


@pytest.fixture
def prepared_case(job_case, tmp_path, monkeypatch):
    a, responses = job_case
    root = tmp_path / "runner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "RUNNER_TEMP_ROOT", root)
    a.metadata["RUNNER_TEMP"] = str(root)
    out = tmp_path / "evidence"
    monkeypatch.setattr(bootstrap, "OUT", out)
    outputs = root / "_runner_file_commands"
    outputs.mkdir()
    output = outputs / "set_output_abcdef-1234"
    output.write_text("")
    get = a._get
    def counted(endpoint):
        a.get_count += 1
        return get(endpoint)
    a._get = counted
    monkeypatch.setattr(bootstrap.secrets, "token_hex", lambda n: "e" * (2 * n))
    bootstrap.prepare(a, a.metadata, a.event, runner.measure_checkout(), str(output))
    return a, responses, root, out, output


def test_prepare_persists_exact_immutable_private_and_public_challenge(prepared_case):
    a, _, root, out, output = prepared_case
    state = json.loads((root / bootstrap.STATE_NAME).read_text())
    artifact = json.loads((out / "observed-job.json").read_text())
    assert state["observed"] == artifact
    assert state["bootstrap_gets"] == 4
    assert state["metadata"] == a.metadata
    assert output.read_text() == "job_id=" + artifact["job_id"] + "\n"
    with pytest.raises(FileExistsError):
        bootstrap.write_state(a.metadata, state)


def test_resume_remeasures_same_job_source_and_preserves_get_budget(prepared_case, monkeypatch):
    a, _, root, out, _ = prepared_case
    before = json.loads((root / bootstrap.STATE_NAME).read_text())["observed"]
    def no_permit(api, observed):
        assert api.get_count == 8
        assert observed == before
        raise runner.SafetyStop("No operator permit")
    monkeypatch.setattr(bootstrap, "await_permit", no_permit)
    execute = Mock()
    monkeypatch.setattr(runner, "execute", execute)
    with pytest.raises(runner.SafetyStop):
        bootstrap.execute_prepared(a, "invented", a.metadata, a.event, runner.measure_checkout())
    receipt = json.loads((out / "bootstrap-receipt.json").read_text())
    assert receipt["stage"] == "permit-poll" and receipt["bootstrap_gets"] == 8
    assert receipt["reason"] == "No operator permit"
    assert json.loads((root / bootstrap.STATE_NAME).read_text())["observed"] == before
    execute.assert_not_called()
    with pytest.raises(FileExistsError):
        bootstrap.execute_prepared(a, "invented", a.metadata, a.event, runner.measure_checkout())
    assert json.loads((out / "bootstrap-receipt.json").read_text()) == receipt


@pytest.mark.parametrize("bad", ["missing", "symlink", "count", "metadata", "head", "tree", "digest", "job", "nonce"])
def test_resume_rejects_missing_or_drifted_state_without_recreating_challenge(prepared_case, monkeypatch, bad):
    a, responses, root, out, _ = prepared_case
    path = root / bootstrap.STATE_NAME
    state = json.loads(path.read_text())
    checkout = runner.measure_checkout()
    if bad == "missing": path.unlink()
    elif bad == "symlink":
        path.unlink()
        path.symlink_to(root / "outside")
    elif bad == "count": state["bootstrap_gets"] = 0
    elif bad == "metadata": state["metadata"]["GITHUB_RUN_ATTEMPT"] = "2"
    elif bad == "head": responses["/pulls/800"]["head"]["sha"] = "f" * 40
    elif bad == "tree": checkout["tree"] = "f" * 40
    elif bad == "digest": checkout["harness_digests"][runner.WORKFLOW_PATH] = "f" * 64
    elif bad == "job": responses["/actions/runs/" + a.reviewed["run_id"] + "/attempts/1/jobs?per_page=100"]["jobs"][0]["id"] = 999
    else: state["observed"]["nonce"] = "bad"
    if bad not in {"missing", "symlink"}: path.write_text(json.dumps(state))
    poll = Mock()
    monkeypatch.setattr(bootstrap, "await_permit", poll)
    with pytest.raises((runner.SafetyStop, OSError)):
        bootstrap.execute_prepared(a, "invented", a.metadata, a.event, checkout)
    poll.assert_not_called()
    assert not (out / "execution-started.json").exists()
    if bad == "missing": assert not path.exists()


def test_output_command_refuses_arbitrary_paths(tmp_path, monkeypatch):
    root = tmp_path / "runner"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(runner, "RUNNER_TEMP_ROOT", root)
    for path in (str(tmp_path / "outside"), str(root / "other")):
        with pytest.raises(runner.SafetyStop):
            bootstrap.emit_job_output({"RUNNER_TEMP": str(root)}, path, "123")
