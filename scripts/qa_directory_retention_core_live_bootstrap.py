"""PR800 one-job bootstrap. Without an exact coordinator permit, no browser runs.

Trusted workflow/repository writers are the authorization boundary for PR body
metadata. The bootstrap independently measures source and authenticated API run
identities; the operator supplies a fresh reviewed Render receipt in a second
uniquely delimited block. Neither credentials nor arbitrary targets are accepted
as CLI arguments. Preparation tests never call GitHub or the live app.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time
from urllib.request import build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_directory_retention_core_live as runner

DEPLOY_BEGIN = "<!-- directory-retention-core-live-deployment:begin -->"
DEPLOY_END = "<!-- directory-retention-core-live-deployment:end -->"
OUT = ROOT / "test-artifacts/directory-retention-core-live-bootstrap"
WAIT_SECONDS = 540
POLL_SECONDS = 5
META_KEYS = {"GITHUB_ACTIONS", "GITHUB_REPOSITORY", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID",
             "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA", "GITHUB_SHA",
             "GITHUB_REF", "GITHUB_JOB", "RUNNER_TEMP"}


class BootstrapGitHub(runner.FixedGitHubAuthority):
    """Only bootstrap GET transport; cannot arm/claim or execute a journey."""
    def __init__(self, token, run_id, event_sha):
        if (not isinstance(token, str) or not token or re.search(r"\s", token)
                or not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]*", run_id)
                or not isinstance(event_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", event_sha)):
            raise runner.SafetyStop("Exact bootstrap credential/run identity missing")
        self._token = token
        self.failed = False
        self.get_count = 0
        self._opener = build_opener(ProxyHandler({}), runner.NoRedirect())
        self._allowed = {"/pulls/800", "/git/ref/heads/main", "/git/commits/" + event_sha, "/actions/runs/" + run_id,
                         "/actions/runs/" + run_id + "/attempts/1/jobs?per_page=100"}

    def _get(self, endpoint):
        if self.get_count >= runner.RESERVED_PERMIT_POLL_GETS:
            self.failed = True
            raise runner.SafetyStop("Bootstrap authenticated GET allocation exhausted")
        return super()._get(endpoint)


def read_event(metadata, path):
    """Bounded no-follow event read only underneath the verified runner temp."""
    root = runner.runner_temp(metadata)
    target = Path(path)
    if not target.is_absolute() or ".." in target.parts:
        raise runner.SafetyStop("Invalid event path")
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        raise runner.SafetyStop("Event is outside verified runner temp") from None
    if not parts:
        raise runner.SafetyStop("Event file missing")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            info = os.fstat(leaf)
            if not stat.S_ISREG(info.st_mode) or info.st_size > runner.MAX_API_BYTES:
                raise runner.SafetyStop("Event is not a bounded regular file")
            raw = os.read(leaf, runner.MAX_API_BYTES + 1)
            if len(raw) != info.st_size:
                raise runner.SafetyStop("Event changed during read")
            return runner.strict_json(raw)
        finally:
            os.close(leaf)
    finally:
        os.close(fd)


def event_checkout_diagnostic(metadata, event, checkout):
    """Allowlisted comparisons only; never serialize event/body/environment."""
    def field(value, *keys):
        for key in keys:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value
    def sha(value):
        return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) else None
    number = field(event, "number")
    event_head = field(event, "pull_request", "head", "sha")
    event_merge = field(event, "pull_request", "merge_commit_sha")
    checkout_head = field(checkout, "head")
    github_sha = field(metadata, "GITHUB_SHA")
    return {"stage": "event-checkout-preflight", "result": "stopped before GitHub API or browser",
            "checks": {
                "event_number_equals_800": number == 800,
                "event_number_is_integer": type(number) is int,
                "event_repository_matches": field(event, "repository", "full_name") == runner.REPOSITORY,
                "head_repository_matches": field(event, "pull_request", "head", "repo", "full_name") == runner.REPOSITORY,
                "base_repository_matches": field(event, "pull_request", "base", "repo", "full_name") == runner.REPOSITORY,
                "event_head_equals_checkout": event_head == checkout_head,
                "workflow_sha_equals_github_sha": field(metadata, "GITHUB_WORKFLOW_SHA") == github_sha,
                "checkout_clean_is_true": field(checkout, "clean") is True},
            "validated_sha_or_null": {
                "event_head": sha(event_head), "event_merge": sha(event_merge),
                "checkout_head": sha(checkout_head), "checkout_tree": sha(field(checkout, "tree")),
                "github_sha": sha(github_sha), "workflow_sha": sha(field(metadata, "GITHUB_WORKFLOW_SHA"))}}


class EventCheckoutMismatch(runner.SafetyStop):
    def __init__(self, diagnostic):
        super().__init__("Bootstrap event/checkout differs")
        self.diagnostic = diagnostic


def observe_job(api, metadata, event, checkout, *, nonce=None):
    """Measure run/job identities before publishing the one-run challenge."""
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": runner.REPOSITORY,
                "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ATTEMPT": "1",
                "GITHUB_REF": "refs/pull/800/merge", "GITHUB_JOB": "core_live",
                "GITHUB_WORKFLOW_REF": runner.REPOSITORY + "/" + runner.WORKFLOW_PATH + "@refs/pull/800/merge"}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise runner.SafetyStop("Bootstrap is outside the exact first-attempt PR workflow")
    for key in ("GITHUB_SHA", "GITHUB_WORKFLOW_SHA"):
        if not re.fullmatch(r"[0-9a-f]{40}", metadata.get(key, "")):
            raise runner.SafetyStop("Bootstrap source provenance incomplete")
    try:
        if (event["number"] != 800 or type(event["number"]) is not int
                or event["repository"]["full_name"] != runner.REPOSITORY
                or event["pull_request"]["head"]["repo"]["full_name"] != runner.REPOSITORY
                or event["pull_request"]["base"]["repo"]["full_name"] != runner.REPOSITORY
                or event["pull_request"]["head"]["sha"] != checkout["head"]
                or metadata["GITHUB_WORKFLOW_SHA"] != metadata["GITHUB_SHA"]
                or checkout["clean"] is not True):
            raise EventCheckoutMismatch(event_checkout_diagnostic(metadata, event, checkout))
        pr = api._get("/pulls/800")
        if (pr["state"] != "open" or pr["merged"] is not False
                or pr["head"]["sha"] != checkout["head"]
                or pr["head"]["repo"]["full_name"] != runner.REPOSITORY
                or pr["base"]["repo"]["full_name"] != runner.REPOSITORY
                or pr["base"]["ref"] != "main" or pr["base"]["sha"] != runner.AUDITED_APP_SHA
                or api._get("/git/ref/heads/main")["object"]["sha"] != runner.AUDITED_APP_SHA):
            raise runner.SafetyStop("Bootstrap current source differs")
        runner.verify_event_commit(api._get("/git/commits/" + metadata["GITHUB_SHA"]),
                                   metadata["GITHUB_SHA"], metadata["GITHUB_WORKFLOW_SHA"],
                                   checkout["head"], checkout["tree"])
        run_id = metadata["GITHUB_RUN_ID"]
        run = api._get("/actions/runs/" + run_id)
        if (str(run["id"]) != run_id or type(run["id"]) is not int
                or run["run_attempt"] != 1 or type(run["run_attempt"]) is not int
                or run["head_sha"] != checkout["head"] or run["event"] != "pull_request"
                or run["status"] != "in_progress" or run["path"] != runner.WORKFLOW_PATH
                or run["repository"]["full_name"] != runner.REPOSITORY
                or [p["number"] for p in run["pull_requests"]] != [800]
                or type(run["workflow_id"]) is not int or run["workflow_id"] <= 0):
            raise runner.SafetyStop("Bootstrap run identity differs")
        jobs = api._get("/actions/runs/" + run_id + "/attempts/1/jobs?per_page=100")
        if (type(jobs["total_count"]) is not int or not 1 <= jobs["total_count"] <= 100
                or jobs["total_count"] != len(jobs["jobs"])):
            raise runner.SafetyStop("Bootstrap job listing is incomplete")
        matches = [j for j in jobs["jobs"] if j["name"] == metadata["GITHUB_JOB"]]
        if (len(matches) != 1 or type(matches[0]["id"]) is not int or matches[0]["id"] <= 0
                or matches[0]["status"] != "in_progress" or str(matches[0]["run_id"]) != run_id
                or type(matches[0]["run_attempt"]) is not int or matches[0]["run_attempt"] != 1):
            raise runner.SafetyStop("Bootstrap numeric job is not unique/current")
    except (KeyError, TypeError):
        raise runner.SafetyStop("Bootstrap API metadata incomplete") from None
    return {"repository": runner.REPOSITORY, "pull_request": 800, "head": checkout["head"],
            "tree": checkout["tree"], "harness_digests": checkout["harness_digests"],
            "app_sha": runner.AUDITED_APP_SHA, "run_id": run_id, "attempt": "1",
            "job": metadata["GITHUB_JOB"], "job_id": str(matches[0]["id"]),
            "workflow_id": str(run["workflow_id"]), "workflow_ref": metadata["GITHUB_WORKFLOW_REF"],
            "workflow_sha": metadata["GITHUB_WORKFLOW_SHA"], "event_name": "pull_request",
            "event_sha": metadata["GITHUB_SHA"], "nonce": secrets.token_hex(32) if nonce is None else nonce}


def deployment_from_body(body):
    if (body.count(DEPLOY_BEGIN) != 1 or body.count(DEPLOY_END) != 1
            or body.index(DEPLOY_END) <= body.index(DEPLOY_BEGIN)):
        raise runner.SafetyStop("Fresh reviewed deployment block missing or ambiguous")
    return runner.strict_json(body.split(DEPLOY_BEGIN, 1)[1].split(DEPLOY_END, 1)[0])


def await_permit(api, observed):
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        pr = api._get("/pulls/800")
        if (pr["state"] != "open" or pr["head"]["sha"] != observed["head"]
                or pr["base"]["sha"] != runner.AUDITED_APP_SHA):
            raise runner.SafetyStop("PR source changed while awaiting permit")
        body = pr.get("body") or ""
        if not isinstance(body, str) or len(body.encode()) > 65536:
            raise runner.SafetyStop("Invalid permit metadata body")
        if runner.PERMIT_BEGIN in body or runner.PERMIT_END in body:
            permit = runner.body_permit(body)
            # A prior run's completed permit does not arm this fresh job.
            if permit["run_id"] == observed["run_id"]:
                if any(permit.get(k) != v for k, v in observed.items()):
                    raise runner.SafetyStop("Coordinator permit differs from observed job/source challenge")
                deployment = deployment_from_body(body)
                return permit, deployment
        time.sleep(min(POLL_SECONDS, max(0, deadline - time.monotonic())))
    raise runner.SafetyStop("No exact coordinator permit arrived before the bounded wait ended")


STATE_NAME = "directory-retention-core-live-observed.json"
OBSERVED_FIELDS = runner.FIELDS - {"issued_at", "expires_at", "deployment_id", "deployment_evidence_sha256"}


def write_state(metadata, record):
    root = runner.runner_temp(metadata)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(STATE_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            raw = json.dumps(record, sort_keys=True).encode()
            if len(raw) > 65536 or os.write(fd, raw) != len(raw):
                raise runner.SafetyStop("Observed challenge write incomplete")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


def emit_job_output(metadata, output_path, job_id):
    root = runner.runner_temp(metadata)
    target = Path(output_path)
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise runner.SafetyStop("GitHub output path outside verified runner temp") from None
    if not re.fullmatch(r"_runner_file_commands/set_output_[0-9a-f-]+", str(relative)):
        raise runner.SafetyStop("GitHub output path is not the fixed output-command family")
    directory = os.open(root / "_runner_file_commands", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(relative.name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536 or not re.fullmatch(r"[1-9][0-9]*", job_id):
                raise runner.SafetyStop("Invalid bounded GitHub output file or job ID")
            raw = ("job_id=" + job_id + "\n").encode()
            if os.write(fd, raw) != len(raw):
                raise runner.SafetyStop("GitHub job output incomplete")
        finally:
            os.close(fd)
    finally:
        os.close(directory)


def prepare(api, metadata, event, checkout, output_path):
    try:
        observed = observe_job(api, metadata, event, checkout)
    except EventCheckoutMismatch as exc:
        # Preserve the failing guard. Emit only bounded, allowlisted evidence;
        # no challenge, private handoff, permit, browser, or API call is created.
        encoded = json.dumps(exc.diagnostic, sort_keys=True)
        if len(encoded.encode()) > 4096:
            raise runner.SafetyStop("Early diagnostic exceeded fixed budget") from None
        OUT.mkdir(parents=True, exist_ok=False)
        with (OUT / "early-preflight.json").open("x") as handle:
            handle.write(encoded)
        print("STOPPED EARLY PREFLIGHT " + encoded, flush=True)
        raise
    record = {"observed": observed, "metadata": metadata, "bootstrap_gets": api.get_count}
    write_state(metadata, record)  # Permanent private handoff; never overwritten.
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / "observed-job.json").write_text(json.dumps(observed, indent=2))
    emit_job_output(metadata, output_path, observed["job_id"])
    print("PREPARED EXACT ONE-RUN CHALLENGE " + json.dumps(observed, sort_keys=True), flush=True)


def execute_prepared(api, token, metadata, event, checkout):
    if (OUT / "execution-started.json").exists() or (OUT / "execution-started.json").is_symlink():
        raise FileExistsError("This prepared job resume was already attempted")
    root = runner.runner_temp(metadata)
    record = read_event(metadata, str(root / STATE_NAME))
    if (not isinstance(record, dict) or set(record) != {"observed", "metadata", "bootstrap_gets"}
            or record["metadata"] != metadata or type(record["bootstrap_gets"]) is not int
            or record["bootstrap_gets"] != 5 or not isinstance(record["observed"], dict)
            or set(record["observed"]) != OBSERVED_FIELDS):
        raise runner.SafetyStop("Missing or invalid exact prepare-step handoff")
    observed = record["observed"]
    if not isinstance(observed["nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", observed["nonce"]):
        raise runner.SafetyStop("Prepared challenge nonce invalid")
    api.get_count = record["bootstrap_gets"]  # Same 120-GET allocation across processes.
    refreshed = observe_job(api, metadata, event, checkout, nonce=observed["nonce"])
    if json.dumps(refreshed, sort_keys=True) != json.dumps(observed, sort_keys=True):
        raise runner.SafetyStop("Prepared job/source differs from fresh measured resume state")
    # A duplicate resume must not overwrite prior evidence or poll again.
    with (OUT / "execution-started.json").open("x") as handle:
        json.dump({"run_id": observed["run_id"], "job_id": observed["job_id"]}, handle)
    status = {"stage": "permit-poll", "result": "waiting", "run_id": observed["run_id"], "job_id": observed["job_id"]}
    try:
        permit, deployment = await_permit(api, observed)
        status["stage"] = "authority-arm"
        authority = runner.FixedGitHubAuthority(token, permit, metadata, event, deployment)
        authority.arm(observed["nonce"])
        status["result"] = "armed exact first-attempt job"
        status["stage"] = "one-shot-execution"
        runner.execute(permit, metadata, event, checkout, authority)
        status["result"] = "finished exact first-attempt job"
    except Exception as exc:
        status["result"] = "stopped without completion"
        status["failure_type"] = type(exc).__name__
        status["reason"] = str(exc)[:240] if isinstance(exc, runner.SafetyStop) else "Unexpected failure; response and exception details excluded"
        raise runner.SafetyStop("One-run bootstrap stopped; inspect bounded synthetic receipts") from None
    finally:
        status["bootstrap_gets"] = api.get_count
        with (OUT / "bootstrap-receipt.json").open("x") as handle:
            json.dump(status, handle, indent=2)
        print("ONE-RUN BOOTSTRAP STATUS " + json.dumps(status, sort_keys=True), flush=True)


def main():
    if sys.argv[1:] not in (["--prepare"], ["--execute"]):
        raise runner.SafetyStop("Only fixed --prepare or --execute phases are supported")
    metadata = {k: os.environ.get(k, "") for k in META_KEYS}
    token = os.environ.pop("GITHUB_TOKEN", "")  # Never inherited by driver/browser subprocesses.
    event = read_event(metadata, os.environ.get("GITHUB_EVENT_PATH", ""))
    checkout = runner.measure_checkout()
    api = BootstrapGitHub(token, metadata["GITHUB_RUN_ID"], metadata["GITHUB_SHA"])
    if sys.argv[1:] == ["--prepare"]:
        prepare(api, metadata, event, checkout, os.environ.get("GITHUB_OUTPUT", ""))
    else:
        execute_prepared(api, token, metadata, event, checkout)


if __name__ == "__main__":
    main()
