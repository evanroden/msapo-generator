"""Learned-data storage outages must never interrupt a Purchase Order, Expense
or Monthly report workflow (issue #21, "Database outage degrades gracefully").

Every public memory function is exercised against a database that cannot be
opened: a corrupt file, and a data directory that cannot be created. Each must
return its documented empty/False result instead of raising, and learning
must resume once storage is healthy again. Synthetic values only.
"""
import pytest

from app import memory


CONTRACT = "Synthetic Contract"
VENDOR = "Synthetic Mechanical, Inc."
DEVICE = "synthetic-browser-token"


def _exercise_every_public_reader_and_writer():
    """Call each public function once; return what the readers produced."""
    assert memory.record_send(contract=CONTRACT, admin_email="admin@example.invalid",
                              vendor=VENDOR, contact_name="Synthetic Rep",
                              contact_email="rep@example.invalid") is False
    memory.record_vendor_contact(contract=CONTRACT, vendor=VENDOR,
                                 contact_name="Synthetic Rep",
                                 contact_email="rep@example.invalid",
                                 context_id="outage-package")
    memory.record_report_preparer(DEVICE, CONTRACT, "north", "Synthetic Preparer")
    memory.record_report_preferences(DEVICE, CONTRACT, "north")
    return {
        "admins": memory.suggest_admin_emails(CONTRACT),
        "contacts": memory.suggest_contacts(CONTRACT),
        "reps": memory.vendor_reps(CONTRACT, VENDOR),
        "remembered_rep": memory.remembered_vendor_contact(CONTRACT, VENDOR),
        "preparer": memory.remembered_report_preparer(DEVICE, CONTRACT, "north"),
        "preferences": memory.remembered_report_preferences(DEVICE),
        "approvers": memory.expense_approvers(CONTRACT),
    }


EMPTY = {
    "admins": [],
    "contacts": [],
    "reps": [],
    "remembered_rep": ("", ""),
    "preparer": "",
    "preferences": ("", ""),
    "approvers": [],
}


def test_corrupt_database_degrades_to_empty_results_without_raising(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    damaged = tmp_path / "epc_memory.db"
    damaged.write_bytes(b"this is not a SQLite database" * 64)

    assert memory._connect() is None
    assert _exercise_every_public_reader_and_writer() == EMPTY
    # The damaged file is left for an operator to inspect, never replaced.
    assert damaged.read_bytes() == b"this is not a SQLite database" * 64


def test_missing_storage_location_degrades_to_empty_results_without_raising(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where the data directory should be")
    monkeypatch.setenv("EPC_DATA_DIR", str(blocker / "nested"))

    assert memory._connect() is None
    assert _exercise_every_public_reader_and_writer() == EMPTY
    assert not (blocker.parent / "nested").exists()


def test_learning_resumes_after_storage_recovers(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    damaged = tmp_path / "epc_memory.db"
    damaged.write_bytes(b"corrupt" * 512)
    assert _exercise_every_public_reader_and_writer() == EMPTY

    # An operator restores healthy storage (here: removes the damaged file).
    damaged.unlink()
    memory.record_vendor_contact(contract=CONTRACT, vendor=VENDOR,
                                 contact_name="Synthetic Rep",
                                 contact_email="rep@example.invalid",
                                 context_id="after-recovery")
    memory.record_report_preparer(DEVICE, CONTRACT, "north", "Synthetic Preparer")

    assert memory.remembered_vendor_contact(CONTRACT, VENDOR) == (
        "Synthetic Rep", "rep@example.invalid")
    assert memory.remembered_report_preparer(DEVICE, CONTRACT, "north") == "Synthetic Preparer"


@pytest.mark.parametrize("failure", [OSError("disk full"), PermissionError("read-only")])
def test_unexpected_storage_errors_on_open_do_not_escape(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    def unavailable(*args, **kwargs):
        raise failure

    monkeypatch.setattr(memory.sqlite3, "connect", unavailable)
    assert _exercise_every_public_reader_and_writer() == EMPTY
