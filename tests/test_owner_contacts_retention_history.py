"""Owner decisions for #21: owner-only contacts, two-year retention, PO history."""
import sqlite3
import time

import pytest

from app import memory
from app.memory import (
    CONTACT_RETENTION_SECONDS,
    contracts_with_saved_contacts,
    correct_vendor_contact,
    delete_vendor_contact,
    po_history,
    prune_stale_contacts,
    record_po_history,
    record_vendor_contact,
    remembered_vendor_contact,
    saved_vendor_contacts,
    vendor_reps,
)

ACCOUNT = "Rochester Regional Health"
OTHER = "UMMC"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "_last_prune_at", time.time())
    yield tmp_path


def _db(tmp_path):
    return sqlite3.connect(memory._db_path())


def _contact(contract=ACCOUNT, vendor="Trane", name="Rep One", email="rep1@example.com",
             ctx="pkg-1"):
    return record_vendor_contact(contract=contract, vendor=vendor, contact_name=name,
                                 contact_email=email, context_id=ctx)


# --- PO history ------------------------------------------------------------

def test_po_history_records_one_row_per_package_and_ignores_reruns():
    for _ in range(3):
        assert record_po_history(contract=ACCOUNT, context_id="ctx-1", vendor="Trane",
                                 total="1,250.00", quote_filename="uploads/Trane Quote.pdf")
    assert record_po_history(contract=ACCOUNT, context_id="ctx-2", vendor="Bailey Electric",
                             total="900.00", quote_filename="Bailey.pdf")
    rows = po_history(ACCOUNT)
    assert [r["quote_filename"] for r in rows] == ["Bailey.pdf", "Trane Quote.pdf"]
    assert rows[1]["vendor"] == memory._norm_vendor("Trane")
    assert rows[1]["total"] == "1,250.00"
    assert po_history(OTHER) == []


def test_po_history_rejects_missing_contract_or_context():
    assert not record_po_history(contract="", context_id="c", vendor="v", total="1",
                                 quote_filename="q")
    assert not record_po_history(contract=ACCOUNT, context_id=" ", vendor="v", total="1",
                                 quote_filename="q")
    assert po_history(ACCOUNT) == []


# --- Two-year retention -----------------------------------------------------

def test_contacts_unused_for_two_years_are_pruned_and_recent_or_unknown_kept(_isolated):
    _contact(name="Old Rep", email="old@example.com", ctx="old")
    _contact(name="New Rep", email="new@example.com", ctx="new")
    _contact(name="Unknown Rep", email="unknown@example.com", ctx="unknown")
    now = time.time()
    old = now - CONTACT_RETENTION_SECONDS - 86400
    with _db(_isolated) as conn:
        conn.execute("UPDATE vendor_contacts SET last_used=? WHERE name='Old Rep'", (old,))
        conn.execute("UPDATE vendor_contact_events SET recorded_at=? WHERE name='Old Rep'", (old,))
        conn.execute("UPDATE vendor_contacts SET last_used=0 WHERE name='Unknown Rep'")
    assert prune_stale_contacts(now) >= 2
    names = {r["name"] for r in saved_vendor_contacts(ACCOUNT)}
    assert names == {"New Rep", "Unknown Rep"}


def test_retention_never_prunes_po_history(_isolated):
    record_po_history(contract=ACCOUNT, context_id="ctx", vendor="Trane", total="1",
                      quote_filename="q.pdf")
    with _db(_isolated) as conn:
        conn.execute("UPDATE po_history SET recorded_at=1")
    prune_stale_contacts(time.time())
    assert len(po_history(ACCOUNT)) == 1


def test_prune_runs_at_most_once_a_day(monkeypatch):
    calls = []
    monkeypatch.setattr(memory, "prune_stale_contacts", lambda now=None: calls.append(now) or 0)
    monkeypatch.setattr(memory, "_last_prune_at", 0.0)
    memory._maybe_prune_stale_contacts()
    memory._maybe_prune_stale_contacts()
    assert len(calls) == 1


# --- Owner contact management ------------------------------------------------

def test_owner_can_list_delete_and_correct_contacts_for_one_account_only():
    _contact(name="Wrong Rep", email="wrong@example.com", ctx="a")
    _contact(contract=OTHER, name="Wrong Rep", email="wrong@example.com", ctx="b")
    assert contracts_with_saved_contacts() == sorted([ACCOUNT, OTHER])

    vendor = saved_vendor_contacts(ACCOUNT)[0]["vendor"]
    assert correct_vendor_contact(ACCOUNT, vendor, "Wrong Rep", "wrong@example.com",
                                  new_name="Right Rep", new_email="right@example.com")
    assert remembered_vendor_contact(ACCOUNT, "Trane") == ("Right Rep", "right@example.com")
    assert remembered_vendor_contact(OTHER, "Trane") == ("Wrong Rep", "wrong@example.com")

    assert delete_vendor_contact(ACCOUNT, vendor, "Right Rep", "right@example.com")
    assert vendor_reps(ACCOUNT, "Trane") == []
    assert vendor_reps(OTHER, "Trane") == [("Wrong Rep", "wrong@example.com")]


def test_correction_rejects_bad_email_and_merges_into_existing_pair():
    _contact(name="Rep A", email="a@example.com", ctx="1")
    _contact(name="Rep B", email="b@example.com", ctx="2")
    vendor = saved_vendor_contacts(ACCOUNT)[0]["vendor"]
    assert not correct_vendor_contact(ACCOUNT, vendor, "Rep A", "a@example.com",
                                      new_name="Rep A", new_email="not-an-email")
    assert correct_vendor_contact(ACCOUNT, vendor, "Rep A", "a@example.com",
                                  new_name="Rep B", new_email="b@example.com")
    rows = saved_vendor_contacts(ACCOUNT)
    assert len(rows) == 1 and rows[0]["count"] == 2


def test_deleted_contact_is_not_revived_by_a_later_correction_of_its_package():
    _contact(name="Gone Rep", email="gone@example.com", ctx="pkg")
    vendor = saved_vendor_contacts(ACCOUNT)[0]["vendor"]
    delete_vendor_contact(ACCOUNT, vendor, "Gone Rep", "gone@example.com")
    _contact(name="New Rep", email="new@example.com", ctx="pkg")
    assert vendor_reps(ACCOUNT, "Trane") == [("New Rep", "new@example.com")]


# --- Owner screen in the app ---------------------------------------------------

def _visible(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
    parts += [t.value for t in at.text_input]
    parts += [t.value.to_csv() for t in at.table]
    return "\n".join(str(p) for p in parts)


_SCRIPT = """
from app.owner_contacts_ui import render_owner_contacts
render_owner_contacts()
"""


def test_owner_screen_lists_nothing_until_opened_then_shows_contacts_and_history():
    from streamlit.testing.v1 import AppTest
    _contact()
    record_po_history(contract=ACCOUNT, context_id="ctx", vendor="Trane", total="1,250.00",
                      quote_filename="Trane Quote.pdf")
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert "rep1@example.com" not in _visible(at)
    at.checkbox(key="owner_contacts_open").check().run()
    assert not at.exception
    rendered = _visible(at)
    assert "rep1@example.com" in rendered
    assert "Trane Quote.pdf" in rendered


def test_owner_screen_delete_removes_the_contact():
    from streamlit.testing.v1 import AppTest
    _contact()
    at = AppTest.from_string(_SCRIPT).run()
    at.checkbox(key="owner_contacts_open").check().run()
    at.button(key="owner_delete_0").click().run()
    assert not at.exception
    assert saved_vendor_contacts(ACCOUNT) == []
