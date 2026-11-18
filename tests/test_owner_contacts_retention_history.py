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


def test_ordinary_read_prunes_old_contacts_without_po_activity(_isolated, monkeypatch):
    contract = "Synthetic Retention Account"
    vendor = "Fixture Supplier"
    _contact(contract=contract, vendor=vendor, name="Expired Rep",
             email="expired@example.com", ctx="expired")
    _contact(contract=contract, vendor=vendor, name="Recent Rep",
             email="recent@example.com", ctx="recent")
    old = time.time() - CONTACT_RETENTION_SECONDS - 86400
    with _db(_isolated) as conn:
        conn.execute("UPDATE vendor_contacts SET last_used=? WHERE name='Expired Rep'", (old,))
        conn.execute("UPDATE vendor_contact_events SET recorded_at=? WHERE name='Expired Rep'", (old,))

    # No accepted PO: opening a normal memory read must run the daily prune.
    monkeypatch.setattr(memory, "_last_prune_at", 0.0)
    contacts = saved_vendor_contacts(contract)
    assert [(row["name"], row["email"]) for row in contacts] == [
        ("Recent Rep", "recent@example.com")
    ]
    with _db(_isolated) as conn:
        assert conn.execute("SELECT COUNT(*) FROM vendor_contact_events WHERE name='Expired Rep'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM vendor_contact_events WHERE name='Recent Rep'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM po_history").fetchone()[0] == 0


def test_prune_failure_does_not_interrupt_ordinary_memory_read(_isolated, monkeypatch):
    contract = "Synthetic Retention Account"
    _contact(contract=contract, vendor="Fixture Supplier", name="Current Rep",
             email="current@example.com", ctx="current")

    def broken_prune(now=None):
        raise RuntimeError("synthetic retention failure")

    monkeypatch.setattr(memory, "prune_stale_contacts", broken_prune)
    monkeypatch.setattr(memory, "_last_prune_at", 0.0)
    assert [row["name"] for row in saved_vendor_contacts(contract)] == ["Current Rep"]


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


def test_owner_screen_shows_contacts_and_history_without_a_disclosure_click():
    from streamlit.testing.v1 import AppTest
    _contact()
    record_po_history(contract=ACCOUNT, context_id="ctx", vendor="Trane", total="1,250.00",
                      quote_filename="Trane Quote.pdf")
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert not at.exception
    assert not any(box.key == "owner_contacts_open" for box in at.checkbox)
    rendered = _visible(at)
    assert "rep1@example.com" in rendered
    assert "Trane Quote.pdf" in rendered


def test_owner_screen_delete_removes_the_contact():
    from streamlit.testing.v1 import AppTest
    _contact()
    at = AppTest.from_string(_SCRIPT).run()
    # Buttons now identify a contact, not its former position in the list.
    at.button[1].click().run()
    assert not at.exception
    assert saved_vendor_contacts(ACCOUNT) == []


def test_owner_screen_delete_first_row_keeps_survivor_fields_and_only_edits_survivor():
    from streamlit.testing.v1 import AppTest

    contract = "Example Account Delete"
    vendor = "Example Vendor"
    _contact(contract=contract, vendor=vendor, name="First Example",
             email="first@example.test", ctx="first")
    _contact(contract=contract, vendor=vendor, name="Second Example",
             email="second@example.test", ctx="second")
    first, survivor = saved_vendor_contacts(contract)
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert [w.value for w in at.text_input] == [
        first["name"], first["email"], survivor["name"], survivor["email"]
    ]

    at.button[1].click().run()  # Delete the displayed first contact.
    assert not at.exception
    assert [w.value for w in at.text_input] == [survivor["name"], survivor["email"]]

    at.text_input[0].set_value("Corrected Survivor").run()
    at.button[0].click().run()  # Save the surviving contact with its own email.
    assert not at.exception
    assert [(r["name"], r["email"]) for r in saved_vendor_contacts(contract)] == [
        ("Corrected Survivor", survivor["email"])
    ]


def test_owner_screen_switch_account_shows_its_contact_and_only_edits_that_account():
    from streamlit.testing.v1 import AppTest

    first_account = "Example Account A"
    second_account = "Example Account B"
    vendor = "Example Vendor"
    _contact(contract=first_account, vendor=vendor, name="Account A Contact",
             email="account-a@example.test", ctx="a")
    _contact(contract=second_account, vendor=vendor, name="Account B Contact",
             email="account-b@example.test", ctx="b")
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert at.selectbox(key="owner_contract").value == first_account
    assert [w.value for w in at.text_input] == [
        "Account A Contact", "account-a@example.test"
    ]

    at.selectbox(key="owner_contract").set_value(second_account).run()
    assert not at.exception
    assert [w.value for w in at.text_input] == [
        "Account B Contact", "account-b@example.test"
    ]

    at.text_input[0].set_value("Corrected Account B").run()
    at.button[0].click().run()
    assert not at.exception
    assert [(r["name"], r["email"]) for r in saved_vendor_contacts(first_account)] == [
        ("Account A Contact", "account-a@example.test")
    ]
    assert [(r["name"], r["email"]) for r in saved_vendor_contacts(second_account)] == [
        ("Corrected Account B", "account-b@example.test")
    ]


def test_contact_date_formatter_uses_browser_zone_and_configured_fallback(monkeypatch):
    """AppTest in Streamlit 1.61.1 has no context; exercise both zones directly."""
    from datetime import datetime, timezone

    from app import config
    from app.owner_contacts_ui import _when

    timestamp = datetime(2026, 1, 1, 2, 30, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(config, "EPC_TIMEZONE", "America/Los_Angeles")
    assert _when(timestamp) == "2025-12-31"
    assert _when(timestamp, "Asia/Tokyo") == "2026-01-01"
    assert _when(timestamp, "Not/A_Zone") == "2025-12-31"
    assert _when(0) == "unknown"


def test_owner_screen_contact_labels_are_plain_text():
    from streamlit.testing.v1 import AppTest

    _contact(contract="Example Account Labels", vendor="Example Vendor",
             name="*Literal* Contact", email="literal@example.test")
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert any("*Literal* Contact <literal@example.test>" in element.value
               for element in at.text)
    assert not any("literal@example.test" in element.value for element in at.markdown)


def test_owner_screen_same_click_save_reloads_and_cannot_change_other_contact():
    """One save activation uses the selected identity; a fresh session sees it."""
    from streamlit.testing.v1 import AppTest

    contract = "Synthetic A67 Same Click"
    vendor = "A67 Fixture Vendor"
    _contact(contract=contract, vendor=vendor, name="First Rep",
             email="first@example.invalid", ctx="one")
    _contact(contract=contract, vendor=vendor, name="Other Rep",
             email="other@example.invalid", ctx="two")
    before = saved_vendor_contacts(contract)
    at = AppTest.from_string(_SCRIPT).run()
    assert not at.exception
    assert len(at.text_input) == 4
    original_index = [widget.value for widget in at.text_input].index("First Rep") // 2
    at.text_input[original_index * 2].set_value("Corrected First Rep")
    at.button[original_index * 2].click().run()  # No independent input rerun required.
    assert not at.exception
    rows = saved_vendor_contacts(contract)
    assert len(rows) == 2
    assert ("Corrected First Rep", "first@example.invalid") in {
        (row["name"], row["email"]) for row in rows
    }
    assert ("Other Rep", "other@example.invalid") in {
        (row["name"], row["email"]) for row in rows
    }
    assert {row["vendor"] for row in rows} == {before[0]["vendor"]}

    reopened = AppTest.from_string(_SCRIPT).run()
    assert not reopened.exception
    assert "Corrected First Rep" in [widget.value for widget in reopened.text_input]
    assert "Other Rep" in [widget.value for widget in reopened.text_input]


def test_owner_screen_two_sessions_stale_identity_cannot_overwrite_updated_row():
    """A concurrent accepted correction retires the old original tuple."""
    from streamlit.testing.v1 import AppTest

    contract = "Synthetic A67 Concurrency"
    vendor = "A67 Supplier"
    _contact(contract=contract, vendor=vendor, name="Original Rep",
             email="original@example.invalid", ctx="one")
    older = AppTest.from_string(_SCRIPT).run()
    newer = AppTest.from_string(_SCRIPT).run()
    assert not older.exception and not newer.exception
    newer.text_input[0].set_value("Current Rep").run()
    newer.button[0].click().run()
    assert not newer.exception
    older.text_input[0].set_value("Stale Rep")
    older.button[0].click().run()
    assert not older.exception
    assert [(row["name"], row["email"]) for row in saved_vendor_contacts(contract)] == [
        ("Current Rep", "original@example.invalid")
    ]
    # The old identity-hashed Save widget is no longer rendered when the
    # other session changes that identity. Its obsolete click is a no-op,
    # rather than a database correction attempt that must show st.error.
    assert [widget.value for widget in older.text_input] == [
        "Current Rep", "original@example.invalid"
    ]
    assert "Stale Rep" not in [widget.value for widget in older.text_input]
