"""Learned memory stays optional, but its failures are no longer invisible.

Synthetic accounts, names and addresses only. Each test here failed before the
reliability changes: failures were neither logged nor counted, a busy database
lost the write or the recall outright, a write lock held during initialization
made every recall come back empty, the same person typed with invisible or
compatibility characters became several entries, and a directory row missing
beside its event row was never restored by a rerun.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import subprocess

import pytest

from app import expense_ui, memory

ACCOUNT = "SYNTHETIC ACCOUNT"
NAME = "Synthetic Director"
EMAIL = "director@example.invalid"
TOKEN = "synthetic-browser-token"


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EPC_MEMORY_STATUS_DIR", str(tmp_path / "status"))
    monkeypatch.setenv("EPC_SQLITE_JOURNAL_MODE", "delete")  # the Azure Files NFS mode
    getattr(memory, "_reset_failure_state", lambda: None)()
    memory._INITIALIZED_DATABASES.clear()
    yield tmp_path
    getattr(memory, "_reset_failure_state", lambda: None)()
    memory._INITIALIZED_DATABASES.clear()


def _short_timeout(monkeypatch, seconds=0.1):
    real = sqlite3.connect

    def connect(*args, **kwargs):
        kwargs["timeout"] = seconds
        return real(*args, **kwargs)

    monkeypatch.setattr(memory.sqlite3, "connect", connect)
    return real


def test_a_swallowed_failure_is_logged_counted_and_published_without_personal_data(store, caplog):
    data = store / "data"
    data.mkdir()
    (data / "epc_memory.db").write_bytes(b"TEST ONLY corrupt, keep for recovery")
    with caplog.at_level(logging.WARNING, logger="app.memory"):
        assert memory.record_expense_approver(account=ACCOUNT, approver_name=NAME,
                                              approver_email=EMAIL, context_id="ctx-1") == 0
        assert memory.remembered_device_account_manager(TOKEN, ACCOUNT) == ""

    summary = memory.failure_summary()
    assert summary["failures"] == 2
    assert any(label.startswith("record_expense_approver/connect") for label in summary["counts"])
    lines = [record.getMessage() for record in caplog.records if record.name == "app.memory"]
    assert lines and "record_expense_approver" in lines[0] and "DatabaseError" in lines[0]
    published = memory._status_path(data).read_text(encoding="utf-8")
    assert json.loads(published)["failures"] >= 1
    for text in (*lines, published):
        for private in (ACCOUNT, NAME, EMAIL, TOKEN, str(data)):
            assert private not in text
    # The bad database is still never erased or replaced.
    assert (data / "epc_memory.db").read_bytes() == b"TEST ONLY corrupt, keep for recovery"


def test_failure_logging_is_rate_limited_but_every_failure_is_counted(store, caplog, monkeypatch):
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("TEST ONLY disk unavailable")

    monkeypatch.setattr(memory.sqlite3, "connect", broken)
    with caplog.at_level(logging.WARNING, logger="app.memory"):
        for _ in range(25):
            memory.remembered_report_preparer(TOKEN, ACCOUNT, "water")
    assert memory.failure_summary()["failures"] == 25
    assert len([r for r in caplog.records if r.name == "app.memory"]) == 1


def test_a_busy_write_is_retried_instead_of_lost(store, monkeypatch):
    assert memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer") is None
    real = _short_timeout(monkeypatch)
    blocker = real(store / "data" / "epc_memory.db", timeout=5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")  # another request holds the write lock

    released = []

    def release_then_wait(seconds):
        if blocker.in_transaction:
            blocker.execute("COMMIT")
            released.append(seconds)

    monkeypatch.setattr(memory, "_sleep", release_then_wait, raising=False)
    count = memory.record_expense_approver(account=ACCOUNT, approver_name=NAME,
                                           approver_email=EMAIL, context_id="ctx-busy")
    blocker.close()
    assert count == 1
    assert released, "the busy attempt was never retried"
    assert memory.failure_summary()["failures"] == 0
    assert memory.failure_summary()["retried_busy"] == 1
    assert memory.expense_approvers(ACCOUNT) == [(NAME, EMAIL)]


def test_a_busy_read_is_retried_instead_of_recalling_nothing(store, monkeypatch):
    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer")
    real = _short_timeout(monkeypatch)
    blocker = real(store / "data" / "epc_memory.db", timeout=5, isolation_level=None)
    blocker.execute("BEGIN EXCLUSIVE")  # a commit in progress keeps readers out

    def release_then_wait(seconds):
        if blocker.in_transaction:
            blocker.execute("COMMIT")

    monkeypatch.setattr(memory, "_sleep", release_then_wait, raising=False)
    assert memory.remembered_report_preparer(TOKEN, ACCOUNT, "water") == "Synthetic Preparer"
    blocker.close()
    assert memory.failure_summary()["failures"] == 0


def test_a_lock_that_never_clears_is_given_up_on_and_counted(store, monkeypatch):
    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer")
    real = _short_timeout(monkeypatch)
    blocker = real(store / "data" / "epc_memory.db", timeout=5, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr(memory, "_sleep", lambda seconds: None, raising=False)
    try:
        assert memory.record_expense_approver(account=ACCOUNT, approver_name=NAME,
                                              approver_email=EMAIL, context_id="ctx-stuck") == 0
    finally:
        blocker.close()
    summary = memory.failure_summary()
    assert summary["failures"] == 1
    assert summary["retried_busy"] == memory.BUSY_ATTEMPTS - 1
    assert any("SQLITE_BUSY" in label for label in summary["counts"])


def test_concurrent_sessions_do_not_lose_writes_on_slow_storage(store, monkeypatch):
    """Streamlit serves each browser on its own thread; on the NFS share a
    commit is slow. SQLite's busy handler is not fair between those threads,
    so some writes used to time out and vanish while others kept the lock."""
    import threading
    import time

    real = sqlite3.connect

    class SlowCommit(sqlite3.Connection):
        def commit(self):
            if self.in_transaction:
                time.sleep(0.03)  # a slow network-share commit, lock held
            return super().commit()

    def connect(*args, **kwargs):
        kwargs["timeout"] = 0.05
        kwargs["factory"] = SlowCommit
        return real(*args, **kwargs)

    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer")  # create the file
    monkeypatch.setattr(memory.sqlite3, "connect", connect)
    monkeypatch.setattr(memory, "_sleep", lambda seconds: None, raising=False)
    results = []

    def session(number):
        results.append(memory.record_expense_approver(
            account=ACCOUNT, approver_name=f"Synthetic Director {number}",
            approver_email=f"director{number}@example.invalid", context_id=f"report-{number}"))

    threads = [threading.Thread(target=session, args=(n,)) for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == [1] * 10
    assert len(memory.expense_approvers(ACCOUNT)) == 10


def _storage_error(code: str) -> sqlite3.OperationalError:
    error = sqlite3.OperationalError("TEST ONLY storage refused the write")
    error.sqlite_errorname = code
    return error


@pytest.mark.parametrize("code", ["SQLITE_FULL", "SQLITE_READONLY", "SQLITE_READONLY_DBMOVED"])
def test_recall_still_works_when_initialization_cannot_write(store, monkeypatch, code):
    """A full or read-only disk used to blank every recall after a deploy.

    Measured on a full tmpfs: after a deploy that adds a table, initialization
    fails with SQLITE_FULL and every recall came back empty, although every
    learned row was still readable.
    """
    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer")
    memory.record_device_account_manager(device_token=TOKEN, account=ACCOUNT,
                                         manager_name="Synthetic Manager", context_id="ctx-1")
    memory._INITIALIZED_DATABASES.clear()  # as after an app restart

    def refuse(*args, **kwargs):
        raise _storage_error(code)

    monkeypatch.setattr(memory, "_initialize", refuse)
    assert memory.remembered_report_preparer(TOKEN, ACCOUNT, "water") == "Synthetic Preparer"
    assert memory.remembered_device_account_manager(TOKEN, ACCOUNT) == "Synthetic Manager"
    # Not cached as initialized, so a later connection initializes again ...
    assert memory._INITIALIZED_DATABASES == {}
    # ... and the operator is told that storage refused a write.
    assert any(code in label for label in memory.failure_summary()["counts"])


def test_an_unsupported_schema_still_turns_memory_off(store, monkeypatch):
    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "Synthetic Preparer")
    memory._INITIALIZED_DATABASES.clear()

    def refuse(*args, **kwargs):
        raise sqlite3.OperationalError("Unsupported expense approver schema")

    monkeypatch.setattr(memory, "_initialize", refuse)
    assert memory.remembered_report_preparer(TOKEN, ACCOUNT, "water") == ""
    assert memory.failure_summary()["failures"] == 1


def test_corruption_and_unknown_errors_still_return_safe_defaults(store, monkeypatch):
    data = store / "data"
    data.mkdir()
    (data / "epc_memory.db").write_bytes(b"TEST ONLY not a database")
    assert memory.remembered_report_preparer(TOKEN, ACCOUNT, "water") == ""
    assert memory.record_report_preferences(TOKEN, ACCOUNT, "water") is None
    assert (data / "epc_memory.db").read_bytes() == b"TEST ONLY not a database"


@pytest.mark.parametrize("typed", [
    "  synthetic   DIRECTOR ",
    "Synthetic Director",
    "Synthetic​ Director",
    "Synthetic Dir­ector",
    "Synthｅtic Director",
])
def test_the_same_director_typed_differently_is_one_entry(store, typed):
    memory.record_expense_approver(account=ACCOUNT, approver_name=NAME, approver_email=EMAIL, context_id="a")
    memory.record_expense_approver(account=ACCOUNT, approver_name=typed,
                                   approver_email=" Director@Example.invalid​", context_id="b")
    entries = memory.expense_approvers(ACCOUNT)
    assert len(entries) == 1 and entries[0][1] == EMAIL
    # The expense form's own pairing key must agree with memory's.
    assert expense_ui._employee_name_key(typed) == memory._requester_key(NAME)
    assert expense_ui._approver_identity_key(typed, EMAIL.upper()) == \
        expense_ui._approver_identity_key(NAME, EMAIL)


def test_composed_and_decomposed_accents_are_one_person_and_one_vendor(store):
    composed, decomposed = "José Example", "José Example"
    memory.record_expense_approver(account=ACCOUNT, approver_name=composed,
                                   approver_email="jose@example.invalid", context_id="a")
    memory.record_expense_approver(account=ACCOUNT, approver_name=decomposed,
                                   approver_email="jose@example.invalid", context_id="b")
    assert len(memory.expense_approvers(ACCOUNT)) == 1
    memory.record_vendor_contact(contract=ACCOUNT, vendor="Café Supply", contact_name="Synthetic Rep",
                                 contact_email="rep@example.invalid", context_id="v")
    assert memory.remembered_vendor_contact(ACCOUNT, "Café Supply") == ("Synthetic Rep", "rep@example.invalid")


@pytest.mark.parametrize("email", ["director@exam\nple.invalid", "director@\texample.invalid"])
def test_an_address_with_hidden_whitespace_is_not_learned(store, email):
    assert memory.record_expense_approver(account=ACCOUNT, approver_name=NAME,
                                          approver_email=email, context_id="a") == 0
    assert memory.expense_approvers(ACCOUNT) == []


def test_a_report_preparer_is_remembered_in_its_normal_form(store):
    memory.record_report_preparer(TOKEN, ACCOUNT, "water", "  Synthetic   Preparer​ ")
    assert memory.remembered_report_preparer(TOKEN, ACCOUNT, "water") == "Synthetic Preparer"


def test_a_rerun_restores_a_vendor_representative_missing_beside_its_event(store):
    kwargs = dict(contract=ACCOUNT, vendor="Synthetic Supply", contact_name="Synthetic Rep",
                  contact_email="rep@example.invalid", context_id="pkg-1")
    assert memory.record_vendor_contact(**kwargs) == 1
    with sqlite3.connect(store / "data" / "epc_memory.db") as conn:
        conn.execute("DELETE FROM vendor_contacts")
    assert memory.record_vendor_contact(**kwargs) == 1
    assert memory.remembered_vendor_contact(ACCOUNT, "Synthetic Supply") == ("Synthetic Rep", "rep@example.invalid")
    assert memory.record_vendor_contact(**kwargs) == 1  # still idempotent


def test_a_rerun_restores_a_requester_missing_beside_its_event(store):
    kwargs = dict(device_token=TOKEN, account=ACCOUNT, manager_name="Synthetic Manager", context_id="pkg-1")
    assert memory.record_device_account_manager(**kwargs) == 1
    with sqlite3.connect(store / "data" / "epc_memory.db") as conn:
        conn.execute("DELETE FROM device_account_managers")
    assert memory.record_device_account_manager(**kwargs) == 1
    assert memory.remembered_device_account_manager(TOKEN, ACCOUNT) == "Synthetic Manager"
    assert memory.record_device_account_manager(**kwargs) == 1


NODE = shutil.which("node")


def _run_cookie_script(existing_cookie: str) -> list[str]:
    from app.device_identity import cookie_bootstrap_html
    script = cookie_bootstrap_html(reload_parent=False)
    body = script.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    harness = (
        "const writes = [];\n"
        f"let jar = {json.dumps(existing_cookie)};\n"
        "globalThis.document = { get cookie() { return jar; }, set cookie(v) { writes.push(v);"
        " const pair = v.split(';')[0]; jar = jar ? jar + '; ' + pair : pair; } };\n"
        "globalThis.window = { location: { protocol: 'https:' }, crypto: require('crypto').webcrypto,"
        " parent: { location: { reload() {} } } };\n"
        "globalThis.sessionStorage = { getItem() { return null; }, setItem() {} };\n"
        + body + "\nconsole.log(JSON.stringify(writes));\n"
    )
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_browser_identity_cookie_is_renewed_on_every_visit():
    token = "0123456789abcdef0123456789abcdef"
    writes = _run_cookie_script(f"other=1; epc_device_id={token}")
    assert len(writes) == 1
    assert writes[0].startswith(f"epc_device_id={token}; Max-Age=31536000")
    # A value that is not our own token is never renewed or replaced here.
    assert _run_cookie_script("epc_device_id=not-a-token") == []
    # A browser without the cookie still gets a fresh random token.
    fresh = _run_cookie_script("")
    assert len(fresh) == 1 and fresh[0].startswith("epc_device_id=") and token not in fresh[0]
