"""The host check proves the data folder is safe and never prints a secret."""
import json
import sqlite3

import pytest

from scripts import host_check

SECRET = "sk-synthetic-NEVER-PRINT-ME"


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
    assert host_check.main() == 0
    out = capsys.readouterr().out
    for expected in ("owner-only folders stay owner-only", "flock locks are honoured",
                     "lockf locks are honoured", "SQLite works here in WAL mode"):
        assert any(line.startswith("PASS") and expected in line for line in out.splitlines()), expected
    assert SECRET not in out
    assert list(host.iterdir()) == []


def test_wal_on_a_network_share_fails(host, monkeypatch, capsys):
    monkeypatch.setattr(host_check, "filesystem_type", lambda path, mountinfo=None: "nfs4")
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", "wal")  # a deployment forcing the unsafe mode
    assert host_check.main() == 1
    assert any(line.startswith("FAIL") and "SQLite works here in WAL mode (chosen for nfs4)" in line
               for line in capsys.readouterr().out.splitlines())


def test_a_share_that_ignores_locks_fails(host, monkeypatch, capsys):
    monkeypatch.setattr(host_check, "_lock_conflicts", lambda kind, path: False)
    assert host_check.main() == 1
    out = capsys.readouterr().out
    assert "FAIL  flock locks are honoured between processes (they are not" in out
    assert "FAIL  lockf locks are honoured between processes (they are not" in out


def test_missing_secrets_fail_without_printing_values(host, monkeypatch, capsys):
    monkeypatch.delenv("SMARTSHEET_FORM_URL")
    assert host_check.main() == 1
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
    assert host_check.main() == 1
    out = capsys.readouterr().out
    assert "PASS  epc_memory.db: WAL mode, integrity ok" in out
    assert any(line.startswith("FAIL") and "smartsheet_submissions.db" in line for line in out.splitlines())
