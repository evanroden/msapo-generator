import sqlite3

from app.memory import (
    record_send,
    record_vendor_contact,
    remembered_vendor_contact,
    vendor_reps,
)


def test_verified_vendor_representative_is_recalled_only_for_vendor_and_account(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    record_vendor_contact(
        contract="Rochester Regional Health",
        vendor="Acme Mechanical, Inc.",
        contact_name="Ashley Vendor",
        contact_email="ashley@example.com",
        context_id="package-1",
    )

    assert remembered_vendor_contact(
        "Rochester Regional Health", "ACME Mechanical"
    ) == ("Ashley Vendor", "ashley@example.com")
    assert remembered_vendor_contact("Another Account", "Acme Mechanical") == (
        "",
        "",
    )
    assert remembered_vendor_contact(
        "Rochester Regional Health", "Acme Controls"
    ) == ("", "")


def test_vendor_contact_events_are_idempotent_and_corrections_replace_the_pair(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    for _ in range(5):
        assert record_vendor_contact(
            contract="Rochester Regional Health",
            vendor="Trane",
            contact_name="Wrong Representative",
            contact_email="wrong@example.com",
            context_id="same-package",
        ) == 1

    assert record_vendor_contact(
        contract="Rochester Regional Health",
        vendor="Trane",
        contact_name="Correct Representative",
        contact_email="correct@example.com",
        context_id="same-package",
    ) == 1
    assert vendor_reps("Rochester Regional Health", "Trane") == [
        ("Correct Representative", "correct@example.com")
    ]

    with sqlite3.connect(tmp_path / "epc_memory.db") as conn:
        rows = conn.execute(
            "SELECT name,email,count FROM vendor_contacts"
        ).fetchall()
        events = conn.execute(
            "SELECT vendor,name,email FROM vendor_contact_events"
        ).fetchall()
    assert rows == [("Correct Representative", "correct@example.com", 1)]
    assert events == [("trane", "Correct Representative", "correct@example.com")]


def test_current_quote_contact_selects_the_matching_historical_pair(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    record_vendor_contact(
        contract="Rochester Regional Health",
        vendor="Carrier",
        contact_name="Most Recent Rep",
        contact_email="recent@example.com",
        context_id="package-1",
    )
    record_vendor_contact(
        contract="Rochester Regional Health",
        vendor="Carrier",
        contact_name="Quote-Matched Rep",
        contact_email="matched@example.com",
        context_id="package-2",
    )

    assert remembered_vendor_contact(
        "Rochester Regional Health",
        "Carrier",
        contact_name="Quote-Matched Rep",
    ) == ("Quote-Matched Rep", "matched@example.com")
    assert remembered_vendor_contact(
        "Rochester Regional Health",
        "Carrier",
        contact_email="recent@example.com",
    ) == ("Most Recent Rep", "recent@example.com")


def test_legacy_vendor_history_remains_available(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))

    assert record_send(
        contract="Rochester Regional Health",
        vendor="Johnson Controls",
        contact_name="Legacy Representative",
        contact_email="legacy@example.com",
    )

    assert remembered_vendor_contact(
        "Rochester Regional Health", "Johnson Controls"
    ) == ("Legacy Representative", "legacy@example.com")
