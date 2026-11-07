"""Disabled preparation for one exact PR/run/job's live UI-only observation.

Authenticated GitHub GETs verify a currently present, exact PR-body permit,
reviewed checkout/harness identities and the current first-attempt job. A fresh
separately reviewed Render receipt is required. The page code caption remains an
operational assertion, not cryptographic attestation. Trusted reviewed workflow,
GitHub/Render control planes and an exclusive unmodified hosted job filesystem
are assumptions. A fsynced O_EXCL claim is never removed, including on failure.
The direct CLI stays disabled. Only the concrete PR bootstrap can arm one exact
run/job after current authenticated checks; no permit means no browser.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path
import re
import secrets
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_directory_retention_core as core
from scripts import qa_directory_retention_live as live
from scripts.qa_directory_retention_live import (
    SafetyStop, ACTOR, SHEET, CONFIRM, IMPORT_DISCLOSURE, STORAGE_DISCLOSURE,
    validate_route,
)

REPOSITORY = "evanroden/msapo-generator"
AUDITED_APP_SHA = "df8b748325bd096a7affcf4f30671e82e852ae00"
OUT = ROOT / "test-artifacts/directory-retention-core-live"
WORKFLOW_PATH = ".github/workflows/directory-retention-core-live.yml"
HARNESS_FILES = frozenset({"scripts/qa_directory_retention_" + name + ".py"
                           for name in ("core_live", "core_live_bootstrap", "core", "live", "local")}
                          | {WORKFLOW_PATH})
FIELDS = {"repository", "pull_request", "head", "tree", "app_sha", "run_id",
          "attempt", "nonce", "workflow_ref", "workflow_sha", "event_name", "event_sha",
          "deployment_id", "deployment_evidence_sha256", "harness_digests",
          "job", "job_id", "workflow_id", "issued_at", "expires_at"}


def validate_permit(candidate, authority, metadata, event, checkout, *, now):
    """Pure consistency validator, NOT authentication or an activation grant.

    authority and checkout must come from trusted independent measurements in
    the future executing integration. Tests use invented values, not approvals.
    """
    if not isinstance(authority, dict) or set(authority) != FIELDS:
        raise SafetyStop("Reviewed execution/deployment authority is unavailable")
    if (not isinstance(candidate, dict) or set(candidate) != FIELDS
            or json.dumps(candidate, sort_keys=True) != json.dumps(authority, sort_keys=True)):
        raise SafetyStop("Candidate permit differs from the exact reviewed authority")
    p = candidate
    if (p["repository"] != REPOSITORY or type(p["pull_request"]) is not int
            or p["pull_request"] != 800 or p["app_sha"] != AUDITED_APP_SHA
            or p["attempt"] != "1" or not isinstance(p["run_id"], str)
            or not re.fullmatch(r"[1-9][0-9]*", p["run_id"])
            or not isinstance(p["nonce"], str) or not re.fullmatch(r"[0-9a-f]{64}", p["nonce"])
            or p["event_name"] != "pull_request"):
        raise SafetyStop("Invalid exact one-shot permit scope")
    if (type(p["issued_at"]) is not int or type(p["expires_at"]) is not int
            or not p["issued_at"] <= now < p["expires_at"]
            or not 0 < p["expires_at"] - p["issued_at"] <= 900
            or not isinstance(p["job"], str) or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", p["job"])):
        raise SafetyStop("Permit job or bounded execution window is invalid")
    for key in ("job_id", "workflow_id"):
        if not isinstance(p[key], str) or not re.fullmatch(r"[1-9][0-9]*", p[key]):
            raise SafetyStop("Invalid numeric execution identity")
    for key in ("head", "tree", "app_sha", "workflow_sha", "event_sha"):
        if not isinstance(p[key], str) or not re.fullmatch(r"[0-9a-f]{40}", p[key]):
            raise SafetyStop("Invalid full source identity")
    if (not isinstance(p["workflow_ref"], str)
            or not re.fullmatch(re.escape(REPOSITORY + "/" + WORKFLOW_PATH + "@refs/pull/800/merge"), p["workflow_ref"])
            or not isinstance(p["deployment_id"], str) or not p["deployment_id"]
            or not isinstance(p["deployment_evidence_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", p["deployment_evidence_sha256"])):
        raise SafetyStop("Exact workflow/deployment binding is missing")
    expected = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
                "GITHUB_EVENT_NAME": p["event_name"], "GITHUB_RUN_ID": p["run_id"],
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKFLOW_REF": p["workflow_ref"],
                "GITHUB_WORKFLOW_SHA": p["workflow_sha"], "GITHUB_SHA": p["event_sha"],
                "GITHUB_REF": "refs/pull/800/merge", "GITHUB_JOB": p["job"]}
    if any(metadata.get(k) != v for k, v in expected.items()):
        raise SafetyStop("Current runner metadata differs from permit")
    try:
        if (event["number"] != 800 or type(event["number"]) is not int
                or event["repository"]["full_name"] != REPOSITORY
                or event["pull_request"]["head"]["sha"] != p["head"]
                or p["workflow_sha"] != p["event_sha"]
                or event["pull_request"]["head"]["repo"]["full_name"] != REPOSITORY
                or event["pull_request"]["base"]["repo"]["full_name"] != REPOSITORY):
            raise SafetyStop("Current PR event differs from permit")
    except (KeyError, TypeError):
        raise SafetyStop("Current PR event is incomplete") from None
    digests = p["harness_digests"]
    files = HARNESS_FILES
    if (not isinstance(digests, dict) or set(digests) != files
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in digests.values())
            or json.dumps(checkout, sort_keys=True) != json.dumps(
                {"head": p["head"], "tree": p["tree"], "clean": True, "harness_digests": digests}, sort_keys=True)):
        raise SafetyStop("Measured checkout or exact harness digests differ")
    return dict(p)


def verify_event_commit(value, event_sha, workflow_sha, head, tree):
    """Bind GitHub's immutable executing merge, not stale webhook merge fields.

    Exact ordered parents and identical tree prove the executed workflow merge
    contains only the audited base and reviewed PR head, with no extra merge
    content. The authenticated fixed GitHub GET supplies value.
    """
    if (any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{40}", v)
            for v in (event_sha, workflow_sha, head, tree)) or workflow_sha != event_sha):
        raise SafetyStop("Executing workflow/merge SHA identity differs")
    try:
        if (value["sha"] != event_sha or not isinstance(value["parents"], list)
                or [parent["sha"] for parent in value["parents"]] != [AUDITED_APP_SHA, head]
                or value["tree"]["sha"] != tree):
            raise SafetyStop("Executing merge commit parent/tree proof differs")
    except (KeyError, TypeError):
        raise SafetyStop("Executing merge commit proof is incomplete") from None


PERMIT_BEGIN = "<!-- directory-retention-core-live-permit:begin -->"
PERMIT_END = "<!-- directory-retention-core-live-permit:end -->"
API_ROOT = "https://api.github.com/repos/" + REPOSITORY
RUNNER_TEMP_ROOT = Path("/home/runner/work/_temp")
MAX_API_BYTES = 1024 * 1024
MAX_EXECUTION_GETS = 600
RESERVED_PERMIT_POLL_GETS = 120  # Future bootstrap must enforce this allocation.
# 93 guards * 2 phases * 2 current-state GETs + 7 full checks * 6 = 414.
# Runtime cap plus polling allocation is 720, leaving 280 for other activity.
IDENTITY_ACTIONS = frozenset({"Upload invented workbook", "Save contract directory", "Check available storage"})


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SafetyStop("Duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SafetyStop("Malformed JSON") from None


def body_permit(body):
    if (not isinstance(body, str) or len(body.encode()) > 65536
            or body.count(PERMIT_BEGIN) != 1 or body.count(PERMIT_END) != 1):
        raise SafetyStop("Missing or ambiguous current PR permit")
    start = body.index(PERMIT_BEGIN) + len(PERMIT_BEGIN)
    end = body.index(PERMIT_END)
    if start >= end:
        raise SafetyStop("Invalid permit delimiters")
    value = strict_json(body[start:end])
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise SafetyStop("Unknown or missing permit fields")
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SafetyStop("GitHub authority redirect refused")


def measure_checkout():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    digests = {}
    for relative in sorted(HARNESS_FILES):
        path = ROOT / relative
        if path.is_symlink() or path.parent.is_symlink() or path.resolve() != path:
            raise SafetyStop("Harness path is not a regular checkout path")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_API_BYTES:
                raise SafetyStop("Harness source exceeds bounded regular file limits")
            raw = os.read(fd, MAX_API_BYTES + 1)
            if len(raw) != info.st_size:
                raise SafetyStop("Harness changed during measurement")
            digests[relative] = sha256(raw).hexdigest()
        finally:
            os.close(fd)
    return {"head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "clean": not bool(git("status", "--porcelain", "--untracked-files=no")),
            "harness_digests": digests}


class FixedGitHubAuthority:
    """Authenticated read-only current-state checks. Never logs response/token.

    reviewed is supplied by independently reviewed runner code, not PR content.
    deployment is a separately reviewed control-plane receipt, not a page claim.
    Trusted runner identity and exclusive job-local filesystem remain assumptions.
    """
    def __init__(self, token, reviewed, metadata, event, deployment):
        if not isinstance(token, str) or not token or re.search(r"\s", token):
            raise SafetyStop("GitHub read credential is missing or malformed")
        self._token = token
        self.reviewed = json.loads(json.dumps(reviewed))
        self.metadata = dict(metadata)
        self.event = json.loads(json.dumps(event))
        self.deployment = json.loads(json.dumps(deployment))
        self._opener = build_opener(ProxyHandler({}), NoRedirect())
        self.failed = False
        self.claimed = False
        self.armed = False
        self.get_count = 0
        self._allowed = {"/pulls/800", "/git/ref/heads/main"}
        if not isinstance(reviewed, dict):
            raise SafetyStop("Reviewed authority missing")
        for key in ("run_id", "job_id", "workflow_id"):
            if not isinstance(reviewed.get(key), str) or not re.fullmatch(r"[1-9][0-9]*", reviewed[key]):
                raise SafetyStop("Exact numeric runner identities missing")
        if not isinstance(reviewed.get("event_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", reviewed["event_sha"]):
            raise SafetyStop("Exact immutable executing SHA missing")
        self._allowed.update({"/git/commits/" + reviewed["event_sha"],
                              "/actions/runs/" + reviewed["run_id"],
                              "/actions/runs/" + reviewed["run_id"] + "/attempts/1/jobs?per_page=100",
                              "/actions/workflows/" + reviewed["workflow_id"]})

    def _get(self, endpoint):
        if self.failed or endpoint not in self._allowed or self.get_count >= MAX_EXECUTION_GETS:
            self.failed = True
            raise SafetyStop("GitHub authority failed or endpoint outside fixed scope")
        self.get_count += 1  # Count attempts, including failed reads; never retry silently.
        request = Request(API_ROOT + endpoint, headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "directory-core-disabled-preparation"}, method="GET")
        try:
            with self._opener.open(request, timeout=8) as response:
                if response.status != 200 or response.geturl() != request.full_url:
                    raise SafetyStop("Unexpected GitHub authority status or redirect")
                raw = response.read(MAX_API_BYTES + 1)
                if len(raw) > MAX_API_BYTES:
                    raise SafetyStop("GitHub authority response exceeded budget")
                return strict_json(raw)
        except Exception:
            self.failed = True
            raise SafetyStop("GitHub authority read failed; no further action allowed") from None

    def _deployment(self, now):
        d = self.deployment
        required = {"service_id", "deploy_id", "status", "commit", "repository", "branch", "url",
                    "checked_at", "instances", "disk_id", "disk_mount", "maintenance"}
        if (not isinstance(d, dict) or set(d) != required
                or d["service_id"] != "srv-d6fi5pldi7vc73eotc00"
                or d["deploy_id"] != self.reviewed["deployment_id"] or d["status"] != "live"
                or d["commit"] != AUDITED_APP_SHA
                or d["repository"] != "https://github.com/" + REPOSITORY
                or d["branch"] != "main" or d["url"] != live.ORIGIN
                or type(d["checked_at"]) is not int or not 0 <= now - d["checked_at"] <= 900
                or type(d["instances"]) is not int or d["instances"] != 1
                or d["disk_id"] != "dsk-d97p5gutrd3s739fmltg" or d["disk_mount"] != "/test1"
                or d["maintenance"] is not False
                or sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    != self.reviewed["deployment_evidence_sha256"]):
            raise SafetyStop("Fresh reviewed deployment receipt is unsatisfied")

    def check_current_state(self):
        """Two fresh GETs each phase: permit/revocation/PR source and main.

        Also remeasure checkout and enforce expiry/deployment-receipt freshness.
        This makes no claim that dynamic execution identity was just refreshed.
        """
        self._check(full_identity=False)

    def check_identity(self):
        """Six fresh GETs: current state, immutable merge proof, workflow/run/job."""
        self._check(full_identity=True)

    def _check(self, *, full_identity):
        if self.failed:
            raise SafetyStop("Authority is sticky-failed")
        try:
            now = int(time.time())
            self._deployment(now)
            p = self.reviewed
            validate_permit(p, p, self.metadata, self.event, measure_checkout(), now=now)
            pr = self._get("/pulls/800")
            current = body_permit(pr.get("body"))
            if (json.dumps(current, sort_keys=True) != json.dumps(p, sort_keys=True)
                    or pr["number"] != 800 or pr["state"] != "open" or pr["merged"] is not False
                    or pr["head"]["sha"] != p["head"] or pr["base"]["sha"] != AUDITED_APP_SHA
                    or pr["base"]["ref"] != "main"
                    or pr["head"]["repo"]["full_name"] != REPOSITORY
                    or pr["base"]["repo"]["full_name"] != REPOSITORY):
                raise SafetyStop("Permit revoked or PR source changed")
            if self._get("/git/ref/heads/main")["object"]["sha"] != AUDITED_APP_SHA:
                raise SafetyStop("Audited main changed")
            if full_identity:
                verify_event_commit(self._get("/git/commits/" + p["event_sha"]),
                                    p["event_sha"], p["workflow_sha"], p["head"], p["tree"])
                run = self._get("/actions/runs/" + p["run_id"])
                path = p["workflow_ref"].split("/", 2)[2].split("@", 1)[0]
                if (type(run["id"]) is not int or str(run["id"]) != p["run_id"]
                        or type(run["run_attempt"]) is not int or run["run_attempt"] != 1
                        or run["event"] != "pull_request" or run["status"] != "in_progress"
                        or run["head_sha"] != p["head"] or run["repository"]["full_name"] != REPOSITORY
                        or type(run["workflow_id"]) is not int or str(run["workflow_id"]) != p["workflow_id"] or run["path"] != path
                        or [x["number"] for x in run["pull_requests"]] != [800]):
                    raise SafetyStop("Current executing run differs")
                workflow = self._get("/actions/workflows/" + p["workflow_id"])
                if (type(workflow["id"]) is not int or str(workflow["id"]) != p["workflow_id"]
                        or workflow["path"] != path or workflow["state"] != "active"):
                    raise SafetyStop("Workflow path identity differs")
                jobs = self._get("/actions/runs/" + p["run_id"] + "/attempts/1/jobs?per_page=100")
                if (type(jobs["total_count"]) is not int or not 1 <= jobs["total_count"] <= 100
                        or len(jobs["jobs"]) != jobs["total_count"]):
                    raise SafetyStop("Incomplete job identity listing")
                matches = [j for j in jobs["jobs"] if str(j["id"]) == p["job_id"]]
                if (len(matches) != 1 or sum(j["name"] == p["job"] for j in jobs["jobs"]) != 1
                        or type(matches[0]["id"]) is not int
                        or matches[0]["name"] != p["job"] or matches[0]["status"] != "in_progress"
                        or str(matches[0]["run_id"]) != p["run_id"]
                        or type(matches[0]["run_attempt"]) is not int or matches[0]["run_attempt"] != 1):
                    raise SafetyStop("Current numeric job differs")
            # Expiry might pass while bounded API reads are in flight.
            if not p["issued_at"] <= int(time.time()) < p["expires_at"]:
                raise SafetyStop("Permit expired during current-state checks")
        except SafetyStop:
            self.failed = True
            raise  # All SafetyStop messages here are fixed, sanitized diagnostics.
        except Exception:
            self.failed = True
            raise SafetyStop("Authority metadata invalid; no further action allowed") from None

    def arm(self, challenge):
        # The authenticated PR body is the coordinator's one-run authorization
        # channel. Repository writers/workflow code must be trusted. This is not
        # a generic callback: verify API identities AND independent local bytes.
        if self.reviewed["nonce"] != challenge:
            raise SafetyStop("Coordinator permit does not match this job challenge")
        self.check_identity()
        self.armed = True

    def claim(self):
        if not self.armed:
            raise SafetyStop("Exact job authority is not armed")
        self.check_identity()
        claim_once(self.reviewed, self.metadata)
        self.claimed = True


def runner_temp(metadata):
    root = RUNNER_TEMP_ROOT
    if metadata.get("RUNNER_TEMP") != str(root) or not root.is_absolute() or root.resolve() != root:
        raise SafetyStop("RUNNER_TEMP is not the reviewed hosted-runner path")
    for path in (root, *root.parents):
        if path.is_symlink():
            raise SafetyStop("RUNNER_TEMP contains a symlink")
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise SafetyStop("RUNNER_TEMP is not private to the current runner user")
    return root


def claim_once(permit, metadata):
    root = runner_temp(metadata)
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open("directory-retention-core-live.claim", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            record = {k: permit[k] for k in ("run_id", "attempt", "job_id", "nonce")}
            raw = json.dumps(record, sort_keys=True).encode()
            if os.write(fd, raw) != len(raw):
                raise SafetyStop("One-shot claim write incomplete")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory)
    except OSError:
        raise SafetyStop("One-shot job claim unavailable or already consumed") from None
    finally:
        os.close(directory)


def browser_environment(home):
    if not home.is_absolute() or home.resolve() != home or home.is_symlink() or any(home.iterdir()):
        raise SafetyStop("Browser HOME must be a fresh private temporary directory")
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_CACHE_HOME": str(home / "cache"), "XDG_DATA_HOME": str(home / "data")}




class LiveCoreJourney(live.Journey):
    # Reuse native actions and exact history-panel observation without inheriting
    # LocalJourney or its disposable-filesystem accessors.
    confirm_review = core.CoreJourney.confirm_review
    snapshot_history = core.CoreJourney.snapshot_history

    def sticky_boundary(self):
        if (self.faults or self.blocked or self.page.is_closed()
                or self.context.pages != [self.page] or self.browser.contexts != [self.context]
                or not self.browser.is_connected()):
            raise SafetyStop("Sticky browser page/context boundary failed")

    def guard(self):
        self.sticky_boundary()
        self.authority.check_current_state()
        super().guard()
        self.authority.check_current_state()  # Assertions may have waited across expiry or revocation.
        self.boundary()  # Revalidate URL/cookie after the final authority request.
        self.sticky_boundary()

    def action(self, name, operation):
        if name in IDENTITY_ACTIONS:
            self.sticky_boundary()
            self.authority.check_identity()
        return super().action(name, operation)

    def install_event_guards(self):
        self.expected_context_close = False
        self.expected_browser_close = False
        def fault(kind):
            if kind not in self.faults:
                self.faults.append(kind)
        self.page.on("pageerror", lambda _: fault("pageerror"))
        self.page.on("popup", lambda _: fault("popup"))
        self.context.on("page", lambda _: fault("extra-page"))
        self.context.on("close", lambda: None if self.expected_context_close else fault("context-closed"))
        self.page.on("crash", lambda: fault("page-crashed"))
        self.browser.on("disconnected", lambda: None if self.expected_browser_close else fault("browser-disconnected"))
        def download(item):
            fault("unexpected-download")
            item.cancel()
        def dialog(item):
            fault("unexpected-dialog")
            item.dismiss()
        self.page.on("download", download)
        self.page.on("dialog", dialog)

    def teardown(self, *, passed):
        # A success must still be verified before expected closure. Cleanup
        # always runs, even if that final guard fails, without masking faults.
        try:
            if passed:
                self.guard()
        finally:
            try:
                self.expected_context_close = True
                self.context.close()
            finally:
                # A browser disconnect during context.close remains unexpected.
                self.expected_browser_close = True
                self.browser.close()

    def initial_navigation(self):
        self.sticky_boundary()
        self.authority.check_identity()
        live.validate_identity(self.context.cookies([live.ORIGIN]), self.token)
        if self.page.url != "about:blank":
            raise SafetyStop("Initial page is not fresh")
        self.events.append({"action": "Open isolated directory", "status": "attempted"})
        self.page.goto(self.config.address("directory"), wait_until="domcontentloaded", timeout=65000)
        self.guard()
        self.events[-1]["status"] = "completed"

    def navigate(self, label, kind):
        self.guard()
        link = self.page.get_by_role("link", name=label, exact=True)
        from playwright.sync_api import expect
        expect(link).to_have_count(1)
        expect(link).to_be_visible()
        validate_route(self.config.origin + "/" + link.get_attribute("href"), kind)
        self.guard()  # Recheck permit after locator waits before changing route.
        self.events.append({"action": "Navigate to " + label, "status": "attempted"})
        self.kind = kind
        link.click()
        self.guard()
        self.events[-1]["status"] = "completed"

    def snapshot(self, name):
        path = self.output / (name + ".png")
        try:
            self.guard()
            self.page.screenshot(path=str(path), full_page=True)
            self.guard()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def download_grid(self, *args, **kwargs):
        raise SafetyStop("CSV is outside live core UI-only acceptance")

    def saved_receipt(self, contract, stage):
        from playwright.sync_api import expect
        self.radio("Review saved directory")
        saved = self.page.get_by_role("combobox", name="Saved contract directory", exact=True)
        expect(saved).to_be_visible()
        self.action("Inspect saved directory choices", saved.click)
        options = self.page.get_by_role("option")
        expect(options).to_have_count(1)
        expect(options).to_have_text([contract])
        self.action("Select synthetic directory", lambda: self.page.get_by_role("option", name=contract, exact=True).click())
        history = self.expand("History and restoration")
        caption = history.get_by_text(re.compile(r"^Version 1 · " + re.escape(ACTOR) + r" · .+ · save$"))
        expect(caption).to_have_count(1)
        expect(caption).to_be_visible()
        expect(history.get_by_role("spinbutton", name="Directory version to inspect", exact=True)).to_have_value("1")
        expect(history.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(history.get_by_test_id("stDataFrame")).to_be_visible()
        contacts = self.expand("All included contacts before saving")
        expect(contacts.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(contacts.get_by_test_id("stDataFrame")).to_be_visible()
        self.snapshot(stage)
        self.snapshot_history(stage)
        self.guard()
        return {"caption": caption.inner_text()}

    def run(self, raw, contract):
        from playwright.sync_api import expect
        self.initial_navigation()
        self.fill("Directory editor name", ACTOR)
        self.radio("Review saved directory")
        expect(self.page.get_by_text("No directory has been saved yet. Import a workbook to begin.", exact=True)).to_be_visible()
        expect(self.page.get_by_role("combobox", name="Saved contract directory", exact=True)).to_have_count(0)
        self.radio("Import a workbook")
        expect(self.page.get_by_text(IMPORT_DISCLOSURE, exact=True)).to_be_visible()
        self.snapshot("empty-import-disclosure")
        uploader = self.page.get_by_test_id("stFileUploader").filter(has=self.page.get_by_text("Contract / site directory workbook", exact=True))
        self.action("Upload invented workbook", lambda: uploader.locator("input[type=file]").set_input_files({
            "name": "synthetic-directory-retention.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": raw}))
        self.button("Read workbook")
        worksheet = self.page.get_by_role("combobox", name="Contract worksheet", exact=True)
        expect(worksheet).to_have_count(1)
        expect(worksheet).to_be_visible()
        expect(worksheet).to_have_value(SHEET)
        self.fill("Contract name", contract)
        expect(self.page.get_by_text("Saving 1 reviewed site records; 0 other saved records remain unchanged. Other workbook tabs are not imported into this contract.", exact=True)).to_be_visible()
        preview = self.expand("All included contacts before saving")
        expect(preview.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(preview.get_by_test_id("stDataFrame")).to_be_visible()
        expect(self.page.get_by_role("button", name="Save contract directory", exact=True)).to_be_disabled()
        self.confirm_review()
        self.button("Save contract directory")
        expect(self.page.get_by_text("Directory saved. Existing reports and their selected sites were not changed. You can review another tab or return to report setup.", exact=True)).to_be_visible()
        before = self.saved_receipt(contract, "saved")
        self.action("Reload saved synthetic directory", self.page.reload)
        self.fill("Directory editor name", ACTOR)
        reloaded = self.saved_receipt(contract, "reloaded")
        if reloaded != before:
            raise SafetyStop("Saved history/contact receipts changed across reload.")
        self.navigate("Storage", "storage")
        self.button("Check available storage")
        expect(self.page.get_by_text(STORAGE_DISCLOSURE, exact=False)).to_be_visible()
        self.snapshot("storage-retention-disclosure")
        self.navigate("Directory", "directory")
        self.fill("Directory editor name", ACTOR)
        after = self.saved_receipt(contract, "after-storage")
        if after != before:
            raise SafetyStop("Storage check changed saved directory history/contact receipts.")
        return {"history_caption": before["caption"]}


def finalize_report(report, journey, blocked):
    """Keep a late genuine event from coexisting with a passed receipt."""
    report["events"] = journey.events if journey else []
    report["blocked_requests"] = len(blocked)
    report["browser_faults"] = list(journey.faults) if journey else []
    downgraded = report["result"].startswith("passed") and bool(blocked or report["browser_faults"])
    if downgraded:
        report["result"] = "failed final browser boundary checks"
        report["failure_type"] = "SafetyStop"
    return downgraded


def execute(candidate, metadata, event, checkout, authority_service):
    """Execute only a concretely armed, authenticated single-job authority."""
    if type(authority_service) is not FixedGitHubAuthority or not authority_service.armed:
        raise SafetyStop("Live core runner is disabled: no armed concrete job authority")
    permit = validate_permit(candidate, authority_service.reviewed, metadata, event, checkout, now=int(time.time()))
    authority_service.claim()  # Rechecks source, permit, deployment, and consumes this job permanently.
    OUT.mkdir(parents=True, exist_ok=False)
    from playwright.sync_api import sync_playwright
    token = secrets.token_hex(16)
    config = live.Config(permit["app_sha"])
    raw = live.workbook()
    report = {"result": "not completed", "coverage": "live UI-only synthetic retention evidence",
              "app_sha": config.commit, "run_id": permit["run_id"], "job_id": permit["job_id"], "attempt": "1",
              "raw_storage_verified": False, "physical_namespace_verified": False,
              "native_csv_acceptance": False, "source_sha256": sha256(raw).hexdigest(),
              "limits": ["Original-byte/lifecycle proof remains local; no hosted filesystem reads.",
                         "No remote physical-root proof from screenshots or cookies alone.",
                         "No elapsed-30-day, retention-clock, aging, deletion or physical-device acceptance.",
                         "Shared deployment startup/catalog/cache/config and disk capacity may be used.",
                         "Canvas values require screenshot inspection, not caption equality.",
                         "Replay claim assumes trusted exclusive hosted job storage is not erased or cloned."]}
    journey = None
    browser = context = None
    blocked = []
    try:
        with tempfile.TemporaryDirectory(prefix="directory-live-browser-", dir=runner_temp(metadata)) as home:
            env = browser_environment(Path(home))
            # Start the Playwright driver before scrubbing browser HOME, so its
            # pinned downloaded executable is resolved from the installed cache.
            with sync_playwright() as playwright:
                try:
                    authority_service.check_identity()  # Fresh execution identity immediately pre-browser.
                    browser = playwright.chromium.launch(headless=True, env=env)
                    context = browser.new_context(accept_downloads=False, service_workers="block",
                                                  viewport={"width": 1440, "height": 1000})
                    if context.cookies():
                        raise SafetyStop("Fresh context contains cookies")
                    context.add_cookies([{"name": "epc_device_id", "value": token, "url": live.ORIGIN,
                                         "secure": True, "sameSite": "Lax"}])
                    page = context.new_page()
                    page.set_default_timeout(30000)
                    journey = LiveCoreJourney(page, context, token, config, OUT)
                    journey.authority = authority_service
                    journey.browser = browser
                    journey.faults = []
                    journey.blocked = blocked
                    journey.install_event_guards()
                    def route_gate(route):
                        if live.request_allowed(route.request.url, journey.kind,
                                top_level=route.request.is_navigation_request() and route.request.frame.parent_frame is None):
                            route.continue_()
                        else:
                            blocked.append("Unexpected origin or top-level route")
                            route.abort()
                    def websocket_gate(socket):
                        parsed = urlsplit(socket.url)
                        if ((parsed.scheme, parsed.netloc, parsed.path) ==
                                ("wss", "msapo-generator.onrender.com", "/_stcore/stream")
                                and not parsed.query and not parsed.fragment):
                            socket.connect_to_server()
                        else:
                            blocked.append("Unexpected websocket")
                            socket.close()
                    context.route("**/*", route_gate)
                    context.route_web_socket("**/*", websocket_gate)
                    try:
                        report.update(journey.run(raw, "Synthetic Retention 291 " + secrets.token_hex(5)))
                        journey.guard()
                        report["result"] = "passed live UI-only controls and history captions; inspect screenshots"
                    except Exception:
                        try:
                            journey.snapshot("first-failure")
                        except Exception:
                            pass  # Never preserve an unverified screenshot.
                        raise
                finally:
                    if journey is not None:
                        journey.teardown(passed=report["result"].startswith("passed"))
                    else:
                        try:
                            if context is not None:
                                context.close()
                        finally:
                            if browser is not None:
                                browser.close()
    except Exception as exc:
        report["result"] = "failed"
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        downgraded = finalize_report(report, journey, blocked)
        (OUT / "receipt.json").write_text(json.dumps(report, indent=2))
        if downgraded:
            raise SafetyStop("Late browser faults invalidated the completed journey")


def main():
    # No CLI/env permit can enable this preparation. Do not add a fallback.
    raise SafetyStop("Live core runner is disabled pending reviewed run and deployment authority")


if __name__ == "__main__":
    main()
