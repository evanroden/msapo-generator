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


def test_an_empty_director_map_is_a_warning(host, monkeypatch, capsys):
    from app import config
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTORS", {})
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTOR_PROBLEMS", [])
    assert host_check.main(OFFLINE) == 0
    assert any(line.startswith("WARN  expense directors configured for 0 of ")
               and line.endswith(": expense forms will name no director")
               for line in capsys.readouterr().out.splitlines())


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
