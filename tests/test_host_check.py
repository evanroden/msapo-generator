"""The host check proves the data folder is safe and never prints a secret."""
import json
import sqlite3

import httpx
import pytest

from scripts import host_check
from scripts.azure_config_check import render_env

SECRET = "sk-synthetic-NEVER-PRINT-ME"
OFFLINE = ["--offline"]


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("SMARTSHEET_FORM_URL", "https://example.invalid/form/" + SECRET)
    monkeypatch.setenv("EXPENSE_ACCOUNT_DIRECTORS_JSON", json.dumps({"x": {"name": SECRET, "email": "a@example.invalid"}}))
    for name in host_check.FIXED[1:]:
        monkeypatch.setenv(name, "configured")
    monkeypatch.delenv("EPC_SQLITE_JOURNAL_MODE", raising=False)
    return tmp_path


def test_a_local_disk_passes_and_leaves_nothing_behind(host, capsys):
    assert host_check.main(OFFLINE) == 0
    out = capsys.readouterr().out
    for expected in ("owner-only folders stay owner-only", "flock locks are honoured",
                     "lockf locks are honoured", "SQLite works here in WAL mode"):
        assert any(line.startswith("PASS") and expected in line for line in out.splitlines()), expected
    assert SECRET not in out
    assert list(host.iterdir()) == []


def test_wal_on_a_network_share_fails(host, monkeypatch, capsys):
    monkeypatch.setattr(host_check, "filesystem_type", lambda path, mountinfo=None: "nfs4")
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", "wal")  # a deployment forcing the unsafe mode
    assert host_check.main(OFFLINE) == 1
    assert any(line.startswith("FAIL") and "SQLite works here in WAL mode (chosen for nfs4)" in line
               for line in capsys.readouterr().out.splitlines())


def test_a_share_that_ignores_locks_fails(host, monkeypatch, capsys):
    monkeypatch.setattr(host_check, "_lock_conflicts", lambda kind, path: False)
    assert host_check.main(OFFLINE) == 1
    out = capsys.readouterr().out
    assert "FAIL  flock locks are honoured between processes (they are not" in out
    assert "FAIL  lockf locks are honoured between processes (they are not" in out


def test_missing_secrets_fail_without_printing_values(host, monkeypatch, capsys):
    monkeypatch.delenv("SMARTSHEET_FORM_URL")
    assert host_check.main(OFFLINE) == 1
    out = capsys.readouterr().out
    assert "FAIL  secret SMARTSHEET_FORM_URL is missing" in out
    assert "PASS  secret ANTHROPIC_API_KEY is set" in out
    assert SECRET not in out


def test_existing_databases_report_their_mode_and_integrity(host, capsys):
    database = sqlite3.connect(host / "epc_memory.db")
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("CREATE TABLE t (x)")
    database.commit()
    database.close()
    (host / "smartsheet_submissions.db").write_bytes(b"SQLite format 3\x00" + b"\xff" * 2000)
    assert host_check.main(OFFLINE) == 1
    out = capsys.readouterr().out
    assert "PASS  epc_memory.db: WAL mode, integrity ok" in out
    assert any(line.startswith("FAIL") and "smartsheet_submissions.db" in line for line in out.splitlines())


def test_the_checked_settings_are_the_ones_render_yaml_declares():
    declared = render_env()
    assert set(host_check.SECRETS + host_check.OPTIONAL_SECRETS) == {name for name, value in declared if value is None}
    assert set(host_check.FIXED) == {name for name, value in declared if value is not None}


def _anthropic(monkeypatch, capsys, respond):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-synthetic-model")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    seen = []

    def handler(request):
        seen.append(request)
        return respond(request)

    report = host_check.Report()
    host_check.check_anthropic(report, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = capsys.readouterr().out
    assert SECRET not in out
    assert [(request.method, request.url.path) for request in seen] == [("GET", "/v1/models/claude-synthetic-model")]
    assert seen[0].headers["x-api-key"] == SECRET
    return report, out


def _error(status):
    return lambda request: httpx.Response(status, json={"type": "error", "error": {
        "type": "synthetic", "message": "echoed " + SECRET}})


def test_the_api_check_proves_key_network_and_model(monkeypatch, capsys):
    report, out = _anthropic(monkeypatch, capsys, lambda request: httpx.Response(200, json={
        "type": "model", "id": "claude-synthetic-model", "display_name": "Synthetic",
        "created_at": "2026-01-01T00:00:00Z"}))
    assert report.failures == 0
    assert "PASS  Anthropic API reachable from this host, key accepted, model claude-synthetic-model available" in out


@pytest.mark.parametrize("status, expected", [
    (401, "FAIL  Anthropic rejected ANTHROPIC_API_KEY (401)"),
    (403, "FAIL  the API key may not use model claude-synthetic-model (403)"),
    (404, "FAIL  model claude-synthetic-model is not available to this key (404)"),
    (400, "FAIL  Anthropic answered 400"),
    (429, "WARN  Anthropic answered 429 (rate limited)"),
    (529, "WARN  Anthropic answered 529; a problem on Anthropic's side"),
])
def test_api_answers_are_explained_without_echoing_them(monkeypatch, capsys, status, expected):
    report, out = _anthropic(monkeypatch, capsys, _error(status))
    assert expected in out
    assert "echoed" not in out
    assert report.failures == (1 if expected.startswith("FAIL") else 0)


def test_a_blocked_network_path_fails_and_says_what_to_open(monkeypatch, capsys):
    def refuse(request):
        raise httpx.ConnectError("refused while sending " + SECRET, request=request)

    report, out = _anthropic(monkeypatch, capsys, refuse)
    assert report.failures == 1
    assert "FAIL  cannot reach the Anthropic API from this host (ConnectError): allow outbound https to " \
           "api.anthropic.com" in out


def test_offline_skips_the_api(host, monkeypatch, capsys):
    import anthropic

    def forbidden(*args, **kwargs):
        raise AssertionError("--offline must not call Anthropic")

    monkeypatch.setattr(anthropic, "Anthropic", forbidden)
    assert host_check.main(OFFLINE) == 0
    assert "INFO  Anthropic API not checked (--offline)" in capsys.readouterr().out


def test_an_empty_director_map_is_expected_not_a_warning(host, monkeypatch, capsys):
    """Directors are learned from filed reports, so none configured is normal."""
    from app import config
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTORS", {})
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTOR_PROBLEMS", [])
    assert host_check.main(OFFLINE) == 0
    out = capsys.readouterr().out
    assert any(line.startswith("INFO  expense directors configured for 0 of ")
               and line.endswith(": each account's first expense form asks for its director")
               for line in out.splitlines())
    assert "WARN  expense directors" not in out


def test_learned_directors_are_counted_without_printing_them(host, monkeypatch, capsys):
    from app import config, contracts, memory
    learned_account = contracts.contract_names()[0]
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTORS", {})
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTOR_PROBLEMS", [])
    assert memory.record_expense_approver(
        account=learned_account, approver_name="Synthetic Learned",
        approver_email="learned@example.invalid", context_id="report-1") == 1
    before = (host / "epc_memory.db").read_bytes()
    assert host_check.main(OFFLINE) == 0
    out = capsys.readouterr().out
    assert "learned from filed reports for 1 more" in out
    assert "Synthetic Learned" not in out and "example.invalid" not in out
    assert (host / "epc_memory.db").read_bytes() == before


def test_the_director_count_never_creates_the_memory_database(host):
    assert host_check.learned_director_accounts() == set()
    assert not (host / "epc_memory.db").exists()


def test_a_configured_director_map_passes(host, monkeypatch, capsys):
    from app import config, contracts
    account = contracts.contract_names()[0]
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTORS", {
        config._account_match_key(account): ("Synthetic Director", "director@example.invalid")})
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTOR_PROBLEMS", [])
    assert host_check.main(OFFLINE) == 0
    out = capsys.readouterr().out
    assert "PASS  expense directors configured for 1 of " in out
    assert "Synthetic Director" not in out and "example.invalid" not in out


FOUNDRY_TOKEN = "entra-token-NEVER-PRINT-ME"


def _foundry(monkeypatch, capsys, respond):
    """The check against Claude in Microsoft Foundry, signing in with a managed identity."""
    from app import ai_client
    ai_client._PROVIDERS.clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)  # present on purpose: it must never be sent
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "example-resource")
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-guid")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-synthetic-deployment")
    monkeypatch.setattr(ai_client, "fetch_identity_token", lambda client_id="": (FOUNDRY_TOKEN, 4102444800.0))
    seen = []

    def handler(request):
        seen.append(request)
        return respond(request)

    report = host_check.Report()
    host_check.check_anthropic(report, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    out = capsys.readouterr().out
    ai_client._PROVIDERS.clear()
    assert SECRET not in out and FOUNDRY_TOKEN not in out
    assert [(request.method, str(request.url)) for request in seen] == [
        ("POST", "https://example-resource.services.ai.azure.com/anthropic/v1/messages")]
    assert seen[0].headers["Authorization"] == "Bearer " + FOUNDRY_TOKEN
    assert "x-api-key" not in seen[0].headers
    assert json.loads(seen[0].content)["max_tokens"] == 1
    return report, out


def test_the_foundry_check_proves_sign_in_network_and_deployment(monkeypatch, capsys):
    report, out = _foundry(monkeypatch, capsys, lambda request: httpx.Response(200, json={
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-synthetic-deployment",
        "content": [{"type": "text", "text": "OK"}], "stop_reason": "max_tokens", "stop_sequence": None,
        "usage": {"input_tokens": 9, "output_tokens": 1}}))
    assert report.failures == 0
    assert ("PASS  Microsoft Foundry reachable from this host, sign-in accepted, deployment "
            "claude-synthetic-deployment answered") in out


@pytest.mark.parametrize("status, expected", [
    (401, "FAIL  Foundry rejected the sign-in (401): give the app's identity the Cognitive Services User role"),
    (403, "FAIL  Foundry refused the request (403)"),
    (404, "FAIL  Foundry has no deployment named claude-synthetic-deployment (404)"),
    (400, "FAIL  Foundry answered 400"),
    (429, "WARN  Foundry answered 429 (rate limited)"),
    (529, "WARN  Foundry answered 529; a problem on the service's side"),
])
def test_foundry_answers_are_explained_without_echoing_them(monkeypatch, capsys, status, expected):
    report, out = _foundry(monkeypatch, capsys, _error(status))
    assert expected in out
    assert "echoed" not in out
    assert report.failures == (1 if expected.startswith("FAIL") else 0)


def test_foundry_settings_replace_the_claude_key_in_the_settings_check(host, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_RESOURCE", "example-resource")
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_API_KEY", raising=False)
    assert host_check.main(OFFLINE) == 0
    out = capsys.readouterr().out
    assert ("INFO  Claude runs through Microsoft Foundry at https://example-resource.services.ai.azure.com/"
            "anthropic/, signing in with the app's managed identity; ANTHROPIC_API_KEY is not needed") in out
    assert "secret ANTHROPIC_API_KEY is missing" not in out


def test_swallowed_memory_failures_are_reported_as_a_warning(host, monkeypatch, capsys, tmp_path_factory):
    """The app never stops for a memory failure, so the check must surface them."""
    from app import memory
    monkeypatch.setenv("EPC_MEMORY_STATUS_DIR", str(tmp_path_factory.mktemp("status")))
    memory._reset_failure_state()
    try:
        assert host_check.main(OFFLINE) == 0
        assert "INFO  learned memory: the running app has reported no failures" in capsys.readouterr().out
        (host / "epc_memory.db").write_bytes(b"TEST ONLY corrupt")
        assert memory.remembered_report_preparer("synthetic-browser", "SYNTHETIC ACCOUNT", "water") == ""
        report = host_check.Report()
        host_check.check_memory_health(report, host)
        out = capsys.readouterr().out
    finally:
        memory._reset_failure_state()
    assert report.warnings == 1 and report.failures == 0
    assert "WARN  learned memory: 1 failure(s) since the app started" in out
    assert "remembered_report_preparer/connect: DatabaseError" not in out  # code only, no message
    assert "remembered_report_preparer/connect" in out
    assert "synthetic-browser" not in out and "SYNTHETIC ACCOUNT" not in out


def test_counts_left_by_a_process_that_has_ended_are_only_information(host, monkeypatch, capsys, tmp_path_factory):
    from app import memory
    monkeypatch.setenv("EPC_MEMORY_STATUS_DIR", str(tmp_path_factory.mktemp("status")))
    path = memory._status_path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"failures": 3, "pid": 2 ** 22 + 7, "counts": {"vendor_reps": 3}}))
    report = host_check.Report()
    host_check.check_memory_health(report, host)
    assert report.warnings == 0
    assert "INFO  learned memory: an earlier app process reported 3 failure(s)" in capsys.readouterr().out


def test_a_data_folder_on_container_storage_warns_on_azure(host, monkeypatch, capsys):
    monkeypatch.setenv("CONTAINER_APP_REVISION", "synthetic--rev1")
    monkeypatch.setattr(host_check, "filesystem_type", lambda path, mountinfo=None: "overlay")
    monkeypatch.setattr(host_check, "on_network_filesystem", lambda path, mountinfo=None: False)
    assert host_check.main(OFFLINE) == 0
    assert "WARN  the data folder is on overlay, not on a network share" in capsys.readouterr().out
