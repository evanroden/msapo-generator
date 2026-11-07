"""Offline invented permit fixtures only. Nothing grants activation or runs UI."""
import copy
import inspect
from unittest.mock import Mock

import pytest
from scripts import qa_directory_retention_core_live as prepared
from scripts import qa_directory_retention_core as core
from scripts import qa_directory_retention_live as live


@pytest.fixture
def identities():
    # Deliberately invented identifiers: never save these as authority.
    permit = {"repository": prepared.REPOSITORY, "pull_request": 800,
              "head": "1" * 40, "tree": "2" * 40, "app_sha": prepared.AUDITED_APP_SHA,
              "run_id": "123456789", "attempt": "1", "nonce": "a" * 64,
              "job": "invented_core_live", "job_id": "111", "workflow_id": "222", "issued_at": 1000, "expires_at": 1600,
              "workflow_ref": prepared.REPOSITORY + "/" + prepared.WORKFLOW_PATH + "@refs/pull/800/merge",
              "workflow_sha": "3" * 40, "event_name": "pull_request", "event_sha": "4" * 40,
              "deployment_id": "invented-not-an-approval", "deployment_evidence_sha256": "b" * 64,
              "harness_digests": {name: "c" * 64 for name in prepared.HARNESS_FILES}}
    metadata = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": prepared.REPOSITORY,
                "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": permit["run_id"],
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKFLOW_REF": permit["workflow_ref"],
                "GITHUB_WORKFLOW_SHA": permit["workflow_sha"], "GITHUB_SHA": permit["event_sha"],
                "GITHUB_REF": "refs/pull/800/merge", "GITHUB_JOB": permit["job"]}
    event = {"number": 800, "repository": {"full_name": prepared.REPOSITORY},
             "pull_request": {"head": {"sha": permit["head"], "repo": {"full_name": prepared.REPOSITORY}},
                              "base": {"repo": {"full_name": prepared.REPOSITORY}},
                              "merge_commit_sha": permit["event_sha"]}}
    checkout = {"head": permit["head"], "tree": permit["tree"], "clean": True,
                "harness_digests": copy.deepcopy(permit["harness_digests"])}
    return permit, metadata, event, checkout


def test_validator_checks_consistency_but_does_not_activate(identities):
    permit, metadata, event, checkout = identities
    assert prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200) == permit
    assert "raise SafetyStop" in inspect.getsource(prepared.main)


@pytest.mark.parametrize("field", sorted(prepared.FIELDS))
def test_any_permit_field_change_is_rejected(identities, field):
    permit, metadata, event, checkout = identities
    authority = copy.deepcopy(permit)
    permit[field] = "wrong"
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, authority, metadata, event, checkout, now=1200)


@pytest.mark.parametrize("scope", ["repository", "pull_request", "attempt", "run_id", "nonce", "app_sha", "workflow_ref", "deployment_id", "deployment_evidence_sha256", "event_name", "head", "tree", "workflow_sha", "event_sha", "harness_digests"])
def test_even_matching_invalid_authority_is_rejected(identities, scope):
    permit, metadata, event, checkout = identities
    permit[scope] = ""
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200)


@pytest.mark.parametrize("field", ["GITHUB_ACTIONS", "GITHUB_REPOSITORY", "GITHUB_EVENT_NAME", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_WORKFLOW_REF", "GITHUB_WORKFLOW_SHA", "GITHUB_SHA", "GITHUB_REF"])
def test_current_event_metadata_must_match(identities, field):
    permit, metadata, event, checkout = identities
    metadata[field] = "wrong"
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200)


@pytest.mark.parametrize("mutation", ["fork", "head", "merge", "number", "empty", "dirty", "tree", "digest", "missing-digest"])
def test_event_and_measured_checkout_fail_closed(identities, mutation):
    permit, metadata, event, checkout = identities
    if mutation == "fork":
        event["pull_request"]["head"]["repo"]["full_name"] = "other/fork"
    elif mutation == "head":
        event["pull_request"]["head"]["sha"] = "f" * 40
    elif mutation == "merge":
        event["pull_request"]["merge_commit_sha"] = "f" * 40
    elif mutation == "number":
        event["number"] = 801
    elif mutation == "empty":
        event.clear()
    elif mutation == "dirty":
        checkout["clean"] = False
    elif mutation == "tree":
        checkout["tree"] = "f" * 40
    elif mutation == "digest":
        checkout["harness_digests"]["scripts/qa_directory_retention_core_live.py"] = "d" * 64
    else:
        checkout["harness_digests"].pop("scripts/qa_directory_retention_core_live.py")
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200)


def test_main_and_executor_cannot_be_enabled_by_environment_or_valid_fixture(identities, monkeypatch, tmp_path):
    for key, value in identities[1].items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MONTHLY_QA_DIRECTORY_ACCEPTANCE", live.OPT_IN)
    monkeypatch.setattr(prepared, "OUT", tmp_path / "must-not-exist")
    authority_service = Mock()
    with pytest.raises(live.SafetyStop, match="disabled"):
        prepared.main()
    with pytest.raises(live.SafetyStop, match="disabled"):
        prepared.execute(*identities, authority_service)
    authority_service.verify_and_consume.assert_not_called()
    assert not prepared.OUT.exists()


def test_live_ui_has_no_local_storage_inheritance_or_export():
    assert prepared.LiveCoreJourney.__bases__ == (live.Journey,)
    for name in ("boundary", "radio", "fill", "expand", "button"):
        assert getattr(prepared.LiveCoreJourney, name) is getattr(live.Journey, name)
    assert prepared.LiveCoreJourney.confirm_review is core.CoreJourney.confirm_review
    assert prepared.LiveCoreJourney.snapshot_history is core.CoreJourney.snapshot_history
    assert not hasattr(prepared.LiveCoreJourney, "store_receipt")
    with pytest.raises(live.SafetyStop, match="CSV"):
        prepared.LiveCoreJourney.__new__(prepared.LiveCoreJourney).download_grid(None)
    source = inspect.getsource(prepared.LiveCoreJourney)
    for forbidden in ("read_owned", "verify_source_pair", "store_receipt", "force=", "showSaveFilePicker", "expect_download"):
        assert forbidden not in source
    run = inspect.getsource(prepared.LiveCoreJourney.run)
    for expected in ('self.confirm_review()', 'self.button("Save contract directory")', 'self.page.reload',
                     'self.button("Check available storage")', 'IMPORT_DISCLOSURE', 'STORAGE_DISCLOSURE'):
        assert expected in run
    receipt = inspect.getsource(prepared.LiveCoreJourney.saved_receipt)
    assert 'self.snapshot(stage)' in receipt and 'self.snapshot_history(stage)' in receipt


def test_disabled_executor_orders_authority_before_browser_and_preserves_limits():
    source = inspect.getsource(prepared.execute)
    assert source.index('not authority_service.armed') < source.index('validate_permit(')
    assert source.index('authority_service.claim(') < source.index('OUT.mkdir(') < source.index('from playwright.sync_api')
    for text in ('exist_ok=False', 'accept_downloads=False', 'service_workers="block"',
                 'if context.cookies()', 'context.route("**/*"', 'context.route_web_socket(',
                 'not parsed.query and not parsed.fragment', '"raw_storage_verified": False',
                 '"physical_namespace_verified": False', '"native_csv_acceptance": False'):
        assert text in source
    assert 'os.environ' not in inspect.getsource(prepared)


@pytest.mark.parametrize("now", [999, 1600, 2000])
def test_expired_or_not_yet_valid_permit_is_rejected(identities, now):
    permit, metadata, event, checkout = identities
    with pytest.raises(live.SafetyStop, match="window"):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=now)


def test_job_and_excessive_permit_window_fail_closed(identities):
    permit, metadata, event, checkout = identities
    metadata["GITHUB_JOB"] = "wrong_job"
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200)
    metadata["GITHUB_JOB"] = permit["job"]
    permit["expires_at"] = 5000
    with pytest.raises(live.SafetyStop):
        prepared.validate_permit(permit, copy.deepcopy(permit), metadata, event, checkout, now=1200)


@pytest.fixture
def authority_case(identities, monkeypatch):
    import json
    from hashlib import sha256
    p, metadata, event, checkout = identities
    deployment = {"service_id": "srv-d6fi5pldi7vc73eotc00", "deploy_id": p["deployment_id"],
                  "status": "live", "commit": prepared.AUDITED_APP_SHA,
                  "repository": "https://github.com/" + prepared.REPOSITORY, "branch": "main",
                  "url": live.ORIGIN, "checked_at": 1150, "instances": 1,
                  "disk_id": "dsk-d97p5gutrd3s739fmltg", "disk_mount": "/test1", "maintenance": False}
    p["deployment_evidence_sha256"] = sha256(json.dumps(deployment, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    monkeypatch.setattr(prepared.time, "time", lambda: 1200)
    monkeypatch.setattr(prepared, "measure_checkout", lambda: copy.deepcopy(checkout))
    authority = prepared.FixedGitHubAuthority("invented-test-token", p, metadata, event, deployment)
    pr = {"number": 800, "state": "open", "merged": False,
          "body": prepared.PERMIT_BEGIN + json.dumps(p) + prepared.PERMIT_END,
          "head": copy.deepcopy(event["pull_request"]["head"]),
          "base": {"sha": prepared.AUDITED_APP_SHA, "ref": "main", "repo": {"full_name": prepared.REPOSITORY}}}
    path = prepared.WORKFLOW_PATH
    responses = {"/pulls/800": pr, "/git/ref/heads/main": {"object": {"sha": prepared.AUDITED_APP_SHA}},
                 "/actions/runs/" + p["run_id"]: {"id": int(p["run_id"]), "run_attempt": 1,
                    "event": "pull_request", "status": "in_progress", "head_sha": p["head"],
                    "repository": {"full_name": prepared.REPOSITORY}, "workflow_id": 222,
                    "path": path, "pull_requests": [{"number": 800}]},
                 "/actions/workflows/222": {"id": 222, "path": path, "state": "active"},
                 "/actions/runs/" + p["run_id"] + "/attempts/1/jobs?per_page=100": {
                    "total_count": 1, "jobs": [{"id": 111, "name": p["job"], "status": "in_progress",
                                                "run_id": int(p["run_id"]), "run_attempt": 1}]}}
    def get(endpoint):
        return copy.deepcopy(responses[endpoint])
    monkeypatch.setattr(authority, "_get", get)
    return authority, responses


def test_concrete_authority_current_state_and_recheck(authority_case):
    authority, responses = authority_case
    authority.check_identity()
    responses["/pulls/800"]["body"] = "revoked"
    with pytest.raises(live.SafetyStop):
        authority.check_identity()
    assert authority.failed
    with pytest.raises(live.SafetyStop, match="sticky"):
        authority.check_identity()


@pytest.mark.parametrize("mutation", ["head", "base", "main", "fork", "closed", "merged", "run-id", "attempt", "event", "run-status", "run-head", "run-workflow", "run-path", "workflow-path", "job-id", "job-name", "job-status", "job-run", "job-attempt", "pagination", "expiry", "deployment", "deployment-age", "checkout"])
def test_current_authority_drift_fails_sticky(authority_case, monkeypatch, mutation):
    authority, responses = authority_case
    p = authority.reviewed
    pr = responses["/pulls/800"]
    run = responses["/actions/runs/" + p["run_id"]]
    jobs = responses["/actions/runs/" + p["run_id"] + "/attempts/1/jobs?per_page=100"]
    if mutation == "head": pr["head"]["sha"] = "f" * 40
    elif mutation == "base": pr["base"]["sha"] = "f" * 40
    elif mutation == "main": responses["/git/ref/heads/main"]["object"]["sha"] = "f" * 40
    elif mutation == "fork": pr["head"]["repo"]["full_name"] = "other/fork"
    elif mutation == "closed": pr["state"] = "closed"
    elif mutation == "merged": pr["merged"] = True
    elif mutation == "run-id": run["id"] += 1
    elif mutation == "attempt": run["run_attempt"] = 2
    elif mutation == "event": run["event"] = "push"
    elif mutation == "run-status": run["status"] = "completed"
    elif mutation == "run-head": run["head_sha"] = "f" * 40
    elif mutation == "run-workflow": run["workflow_id"] = 999
    elif mutation == "run-path": run["path"] = ".github/workflows/other.yml"
    elif mutation == "workflow-path": responses["/actions/workflows/222"]["path"] = "other"
    elif mutation == "job-id": jobs["jobs"][0]["id"] = 112
    elif mutation == "job-name": jobs["jobs"][0]["name"] = "other"
    elif mutation == "job-status": jobs["jobs"][0]["status"] = "completed"
    elif mutation == "job-run": jobs["jobs"][0]["run_id"] = 999
    elif mutation == "job-attempt": jobs["jobs"][0]["run_attempt"] = 2
    elif mutation == "pagination": jobs["total_count"] = 101
    elif mutation == "expiry": monkeypatch.setattr(prepared.time, "time", lambda: 1600)
    elif mutation == "deployment": authority.deployment["commit"] = "f" * 40
    elif mutation == "deployment-age": authority.deployment["checked_at"] = 1
    elif mutation == "checkout": monkeypatch.setattr(prepared, "measure_checkout", lambda: {})
    with pytest.raises(live.SafetyStop):
        authority.check_identity()
    assert authority.failed


@pytest.mark.parametrize("raw", ['{"a":1,"a":2}', '{"a":NaN}', '{', '[1,2]', '{}'])
def test_strict_json_and_permit_reject_malformed_duplicate_or_unknown(raw):
    body = prepared.PERMIT_BEGIN + raw + prepared.PERMIT_END
    with pytest.raises(live.SafetyStop):
        prepared.body_permit(body)


def test_permit_requires_unique_ordered_markers(identities):
    import json
    body = prepared.PERMIT_BEGIN + json.dumps(identities[0]) + prepared.PERMIT_END
    assert prepared.body_permit(body) == identities[0]
    for bad in (body + body, prepared.PERMIT_END + prepared.PERMIT_BEGIN, 'x' * 65537):
        with pytest.raises(live.SafetyStop):
            prepared.body_permit(bad)
    permit = dict(identities[0], unexpected=True)
    with pytest.raises(live.SafetyStop):
        prepared.body_permit(prepared.PERMIT_BEGIN + json.dumps(permit) + prepared.PERMIT_END)


@pytest.mark.parametrize("failure", [None, "redirect", "status", "oversize", "exception", "bad-json", "endpoint"])
def test_authenticated_get_is_fixed_bounded_no_redirect_and_no_secret_error(identities, failure):
    authority = prepared.FixedGitHubAuthority("invented-secret", identities[0], identities[1], identities[2], None)
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status = 302 if failure == "status" else 200
    response.geturl.return_value = "https://other.invalid" if failure == "redirect" else prepared.API_ROOT + "/pulls/800"
    response.read.return_value = (b'x' * (prepared.MAX_API_BYTES + 1) if failure == "oversize" else
                                  b'{' if failure == "bad-json" else b'{"ok":true}')
    authority._opener = Mock()
    authority._opener.open.return_value = response
    if failure == "exception":
        authority._opener.open.side_effect = RuntimeError("invented-secret")
    endpoint = "/pulls/800?evil=1" if failure == "endpoint" else "/pulls/800"
    if failure:
        with pytest.raises(live.SafetyStop) as exc:
            authority._get(endpoint)
        assert "invented-secret" not in str(exc.value)
        if failure == "endpoint":
            authority._opener.open.assert_not_called()
    else:
        assert authority._get(endpoint) == {"ok": True}
        request = authority._opener.open.call_args.args[0]
        assert request.method == "GET"
        assert request.full_url == prepared.API_ROOT + "/pulls/800"
        assert request.get_header("Authorization") == "Bearer invented-secret"
        assert authority._opener.open.call_args.kwargs == {"timeout": 8}
        response.read.assert_called_once_with(prepared.MAX_API_BYTES + 1)
    with pytest.raises(live.SafetyStop):
        prepared.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid")


def test_claim_is_exclusive_fsynced_and_never_removed(identities, tmp_path, monkeypatch):
    import os
    root = tmp_path / "private-runner-temp"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(prepared, "RUNNER_TEMP_ROOT", root)
    metadata = dict(identities[1], RUNNER_TEMP=str(root))
    fsync = Mock(wraps=os.fsync)
    monkeypatch.setattr(prepared.os, "fsync", fsync)
    prepared.claim_once(identities[0], metadata)
    claim = root / "directory-retention-core-live.claim"
    assert claim.is_file() and fsync.call_count == 2
    with pytest.raises(live.SafetyStop):
        prepared.claim_once(identities[0], metadata)
    assert claim.is_file()


@pytest.mark.parametrize("mutation", ["wrong-env", "symlink-root", "symlink-claim", "world-writable", "relative"])
def test_claim_rejects_malicious_paths(identities, tmp_path, monkeypatch, mutation):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    metadata = dict(identities[1], RUNNER_TEMP=str(root))
    if mutation == "wrong-env": metadata["RUNNER_TEMP"] = str(tmp_path)
    elif mutation == "symlink-root":
        linked = tmp_path / "linked"
        linked.symlink_to(root, target_is_directory=True)
        root = linked
        metadata["RUNNER_TEMP"] = str(root)
    elif mutation == "symlink-claim": (root / "directory-retention-core-live.claim").symlink_to(tmp_path / "outside")
    elif mutation == "world-writable": root.chmod(0o777)
    elif mutation == "relative":
        from pathlib import Path
        root = Path("relative")
        metadata["RUNNER_TEMP"] = str(root)
    monkeypatch.setattr(prepared, "RUNNER_TEMP_ROOT", root)
    with pytest.raises(live.SafetyStop):
        prepared.claim_once(identities[0], metadata)


def test_browser_environment_drops_credentials_proxy_and_uses_fresh_home(tmp_path, monkeypatch):
    for key in ("GITHUB_TOKEN", "GH_TOKEN", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "HOME", "PATH"):
        monkeypatch.setenv(key, "invented-secret")
    env = prepared.browser_environment(tmp_path)
    assert set(env) == {"PATH", "LANG", "LC_ALL", "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"}
    assert "invented-secret" not in str(env)
    assert env["HOME"] == str(tmp_path)
    (tmp_path / "not-fresh").write_text("synthetic")
    with pytest.raises(live.SafetyStop):
        prepared.browser_environment(tmp_path)


@pytest.fixture
def fake_journey():
    j = prepared.LiveCoreJourney.__new__(prepared.LiveCoreJourney)
    j.page, j.context, j.browser = Mock(), Mock(), Mock()
    j.faults, j.blocked, j.events = [], [], []
    j.page.is_closed.return_value = False
    j.context.pages = [j.page]
    j.browser.contexts = [j.context]
    j.browser.is_connected.return_value = True
    j.authority = Mock()
    return j


@pytest.mark.parametrize("kind", ["pageerror", "popup", "extra-page", "context-closed", "page-crashed", "browser-disconnected", "unexpected-download", "unexpected-dialog"])
def test_browser_events_are_immediately_sticky_and_reject_dialog_download(fake_journey, kind):
    j = fake_journey
    j.install_event_guards()
    mapping = {"pageerror": (j.page, "pageerror"), "popup": (j.page, "popup"),
               "extra-page": (j.context, "page"), "context-closed": (j.context, "close"),
               "page-crashed": (j.page, "crash"), "browser-disconnected": (j.browser, "disconnected"),
               "unexpected-download": (j.page, "download"), "unexpected-dialog": (j.page, "dialog")}
    target, event = mapping[kind]
    callback = next(call.args[1] for call in target.on.call_args_list if call.args[0] == event)
    item = Mock()
    if kind in {"context-closed", "page-crashed", "browser-disconnected"}:
        callback()
    else:
        callback(item)
    assert j.faults == [kind]
    if kind == "unexpected-download": item.cancel.assert_called_once_with()
    if kind == "unexpected-dialog": item.dismiss.assert_called_once_with()
    with pytest.raises(live.SafetyStop):
        j.guard()
    j.authority.check_current_state.assert_not_called()


def test_action_rechecks_authority_and_retains_attempt_on_uncertainty(fake_journey, monkeypatch):
    j = fake_journey
    monkeypatch.setattr(live.Journey, "guard", lambda self: None)
    monkeypatch.setattr(live.Journey, "boundary", lambda self: None)
    j.action("synthetic action", Mock())
    assert j.authority.check_current_state.call_count == 4
    def uncertain():
        raise RuntimeError("uncertain synthetic action")
    with pytest.raises(RuntimeError):
        j.action("uncertain", uncertain)
    assert j.events[-1] == {"action": "uncertain", "status": "attempted"}
    j.authority.check_current_state.side_effect = live.SafetyStop("revoked")
    operation = Mock()
    with pytest.raises(live.SafetyStop):
        j.action("must not happen", operation)
    operation.assert_not_called()


@pytest.mark.parametrize("mutation", ["extra-page", "extra-context", "closed", "disconnected", "blocked"])
def test_context_structure_guard_detects_unreported_drift(fake_journey, mutation):
    j = fake_journey
    if mutation == "extra-page": j.context.pages.append(Mock())
    elif mutation == "extra-context": j.browser.contexts.append(Mock())
    elif mutation == "closed": j.page.is_closed.return_value = True
    elif mutation == "disconnected": j.browser.is_connected.return_value = False
    else: j.blocked.append("blocked request")
    with pytest.raises(live.SafetyStop):
        j.sticky_boundary()


@pytest.mark.parametrize("failure", [None, "pre", "post", "screenshot"])
def test_live_viewport_evidence_guarded_and_discarded(fake_journey, tmp_path, failure):
    j = fake_journey
    j.output = tmp_path
    j.guard = Mock()
    if failure == "pre": j.guard.side_effect = live.SafetyStop("pre")
    elif failure == "post": j.guard.side_effect = [None, live.SafetyStop("post")]
    path = tmp_path / "first-failure.png"
    def capture(**kwargs):
        assert kwargs == {"path": str(path), "full_page": True}
        path.write_bytes(b"synthetic image placeholder")
        if failure == "screenshot": raise RuntimeError("capture")
    j.page.screenshot.side_effect = capture
    if failure:
        with pytest.raises((live.SafetyStop, RuntimeError)):
            j.snapshot("first-failure")
        assert not path.exists()
    else:
        j.snapshot("first-failure")
        assert path.exists() and j.guard.call_count == 2
    if failure == "pre": j.page.screenshot.assert_not_called()


def test_navigation_and_executor_keep_pre_post_checks_and_uncertain_receipts():
    initial = inspect.getsource(prepared.LiveCoreJourney.initial_navigation)
    assert initial.index('self.authority.check_identity()') < initial.index('self.page.goto(') < initial.index('self.guard()')
    navigate = inspect.getsource(prepared.LiveCoreJourney.navigate)
    assert navigate.index('self.guard()') < navigate.index('validate_route(') < navigate.index('link.click()')
    assert navigate.rindex('self.guard()') > navigate.index('link.click()')
    assert navigate.index('"status": "attempted"') < navigate.index('link.click()')
    execute = inspect.getsource(prepared.execute)
    assert execute.index('with sync_playwright()') < execute.index('env=env')
    assert 'journey.snapshot("first-failure")' in execute
    assert 'authority_service.check_identity()  # Fresh execution identity immediately pre-browser.' in execute



def test_duplicate_display_job_names_cannot_resolve_numeric_identity(authority_case):
    authority, responses = authority_case
    jobs = responses["/actions/runs/" + authority.reviewed["run_id"] + "/attempts/1/jobs?per_page=100"]
    duplicate = dict(jobs["jobs"][0], id=112)
    jobs["jobs"].append(duplicate)
    jobs["total_count"] = 2
    with pytest.raises(live.SafetyStop):
        authority.check_identity()



@pytest.mark.parametrize("change", ["expiry", "revocation"])
def test_authority_change_during_playwright_wait_prevents_action(fake_journey, monkeypatch, change):
    j = fake_journey
    state = {"changed": False}
    def authority_check():
        if state["changed"]:
            raise live.SafetyStop(change + " during assertion wait")
    j.authority.check_current_state.side_effect = authority_check
    def waiting_guard(self):
        state["changed"] = True  # Deterministic event during Playwright's waits.
    monkeypatch.setattr(live.Journey, "guard", waiting_guard)
    monkeypatch.setattr(live.Journey, "boundary", lambda self: None)
    operation = Mock()
    with pytest.raises(live.SafetyStop, match=change):
        j.action("must not execute", operation)
    operation.assert_not_called()
    assert j.events == []
    assert j.authority.check_current_state.call_count == 2


def test_guard_revalidates_url_cookie_and_sticky_after_last_authority(fake_journey, monkeypatch):
    j = fake_journey
    order = []
    j.sticky_boundary = lambda: order.append("sticky")
    j.authority.check_current_state.side_effect = lambda: order.append("authority")
    monkeypatch.setattr(live.Journey, "guard", lambda self: order.append("playwright-waits"))
    monkeypatch.setattr(live.Journey, "boundary", lambda self: order.append("URL-cookie"))
    j.guard()
    assert order == ["sticky", "authority", "playwright-waits", "authority", "URL-cookie", "sticky"]


@pytest.mark.parametrize("late", [None, "pageerror", "unexpected-disconnect", "blocked-request", "guard-revoked"])
def test_final_receipt_distinguishes_expected_teardown_and_late_faults(fake_journey, tmp_path, late):
    import json
    j = fake_journey
    j.install_event_guards()
    def callback(target, event):
        return next(call.args[1] for call in target.on.call_args_list if call.args[0] == event)
    context_closed = callback(j.context, "close")
    disconnected = callback(j.browser, "disconnected")
    pageerror = callback(j.page, "pageerror")
    j.guard = Mock()
    if late == "guard-revoked":
        j.guard.side_effect = live.SafetyStop("revoked before teardown")
    def close_context():
        if late == "pageerror": pageerror(RuntimeError("synthetic late error"))
        if late == "unexpected-disconnect": disconnected()
        if late == "blocked-request": j.blocked.append("late denied request")
        context_closed()
    j.context.close.side_effect = close_context
    j.browser.close.side_effect = disconnected
    report = {"result": "passed synthetic test"}
    try:
        j.teardown(passed=True)
    except live.SafetyStop:
        report["result"] = "failed"
    downgraded = prepared.finalize_report(report, j, j.blocked)
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(report))
    receipt = json.loads(path.read_text())
    j.guard.assert_called_once_with()
    j.context.close.assert_called_once_with()
    j.browser.close.assert_called_once_with()
    assert "context-closed" not in receipt["browser_faults"]
    if late is None:
        assert receipt["result"].startswith("passed") and receipt["browser_faults"] == []
        assert not downgraded
    else:
        assert receipt["result"].startswith("failed")
        assert downgraded == (late != "guard-revoked")
    if late == "unexpected-disconnect":
        assert receipt["browser_faults"] == ["browser-disconnected"]
    if late == "pageerror":
        assert receipt["browser_faults"] == ["pageerror"]


def test_current_state_has_two_fresh_gets_and_identity_has_five(authority_case):
    authority, _ = authority_case
    get = Mock(wraps=authority._get)
    authority._get = get
    authority.check_current_state()
    authority.check_current_state()
    assert [c.args[0] for c in get.call_args_list] == ["/pulls/800", "/git/ref/heads/main"] * 2
    get.reset_mock()
    authority.check_identity()
    assert get.call_count == 5


@pytest.mark.parametrize("drift", ["revoked", "head", "base", "main"])
def test_fresh_current_state_detects_drift_during_every_guard_wait(authority_case, fake_journey, monkeypatch, drift):
    authority, responses = authority_case
    j = fake_journey
    j.authority = authority
    get = Mock(wraps=authority._get)
    authority._get = get
    def waits(self):
        pr = responses["/pulls/800"]
        if drift == "revoked": pr["body"] = "revoked"
        elif drift == "head": pr["head"]["sha"] = "f" * 40
        elif drift == "base": pr["base"]["sha"] = "f" * 40
        else: responses["/git/ref/heads/main"]["object"]["sha"] = "f" * 40
    monkeypatch.setattr(live.Journey, "guard", waits)
    monkeypatch.setattr(live.Journey, "boundary", lambda self: None)
    operation = Mock()
    with pytest.raises(live.SafetyStop):
        j.action("ordinary UI control", operation)
    operation.assert_not_called()
    assert [c.args[0] for c in get.call_args_list][:3] == ["/pulls/800", "/git/ref/heads/main", "/pulls/800"]
    if drift == "main":
        assert get.call_args_list[-1].args[0] == "/git/ref/heads/main"


@pytest.mark.parametrize("changed", ["run", "workflow", "job"])
def test_dynamic_identity_is_refetched_not_assumed_fresh(authority_case, changed):
    authority, responses = authority_case
    authority.check_identity()
    p = authority.reviewed
    if changed == "run": responses["/actions/runs/" + p["run_id"]]["status"] = "completed"
    elif changed == "workflow": responses["/actions/workflows/222"]["state"] = "disabled_manually"
    else: responses["/actions/runs/" + p["run_id"] + "/attempts/1/jobs?per_page=100"]["jobs"][0]["status"] = "completed"
    authority.check_current_state()  # Explicitly not an execution-status claim.
    with pytest.raises(live.SafetyStop):
        authority.check_identity()  # Refetches and rejects changed identity.


@pytest.mark.parametrize("name", sorted(prepared.IDENTITY_ACTIONS))
def test_major_mutations_have_full_identity_check_before_operation(fake_journey, monkeypatch, name):
    j = fake_journey
    monkeypatch.setattr(live.Journey, "guard", lambda self: None)
    monkeypatch.setattr(live.Journey, "boundary", lambda self: None)
    order = []
    j.authority.check_identity.side_effect = lambda: order.append("identity")
    j.authority.check_current_state.side_effect = lambda: order.append("current")
    j.action(name, lambda: order.append("operation"))
    assert order == ["identity", "current", "current", "operation", "current", "current"]
    j.authority.check_identity.side_effect = live.SafetyStop("run no longer active")
    operation = Mock()
    with pytest.raises(live.SafetyStop):
        j.action(name, operation)
    operation.assert_not_called()


def test_full_identity_check_at_startup_prebrowser_and_initial_navigation():
    assert 'self.check_identity()' in inspect.getsource(prepared.FixedGitHubAuthority.claim)
    execute = inspect.getsource(prepared.execute)
    assert execute.index('authority_service.check_identity()') < execute.index('playwright.chromium.launch(')
    initial = inspect.getsource(prepared.LiveCoreJourney.initial_navigation)
    assert initial.index('self.authority.check_identity()') < initial.index('self.page.goto(')


def test_request_budget_is_conservative_and_hard_capped(identities):
    # Allow 120 guards rather than observed 93, all double-phased, plus
    # arm/claim/pre-browser/initial-navigation/upload/save/Storage full checks.
    conservative_execution = 120 * 2 * 2 + 7 * 5
    assert conservative_execution == 515
    assert conservative_execution < prepared.MAX_EXECUTION_GETS == 600
    assert prepared.RESERVED_PERMIT_POLL_GETS == 120
    assert prepared.MAX_EXECUTION_GETS + prepared.RESERVED_PERMIT_POLL_GETS == 720 < 1000
    authority = prepared.FixedGitHubAuthority("invented-test-token", identities[0], identities[1], identities[2], None)
    authority.get_count = prepared.MAX_EXECUTION_GETS
    authority._opener = Mock()
    with pytest.raises(live.SafetyStop):
        authority._get("/pulls/800")
    authority._opener.open.assert_not_called()
    assert authority.failed
