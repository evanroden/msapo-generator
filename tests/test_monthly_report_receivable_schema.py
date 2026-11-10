"""Synthetic schema discovery; no invoice intake or output policy approval."""
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from app.monthly_report_content_policy import table_has_pricing
from app.monthly_report_model import ReportTable
from app.monthly_report_receivable_schema import inspect_receivable_schema


DIGEST = sha256(b"synthetic original invoice source").hexdigest()


def source_table():
    return ReportTable(
        ("Invoice #", "Facility", "Status", "Invoice Date", "Due Date", "Aging as of",
         "Amount Due", "Current", "31-60", "Credit Amount", "Custom review note"),
        (("INV-001", "Synthetic North", "Partially paid", "2026-09-01", "", "2026-10-28",
          "500", "250", "250", "", "Date awaiting review"),
         ("INV-002", "Synthetic South", "Credit", "03/04/2026", "", "",
          "-25", "", "", "25", "Preserve source credit")),
        "synthetic-source:word/document.xml:table:4",
    )


def test_inventory_preserves_all_cells_and_candidates_without_computing_aging_or_balances():
    table = source_table()
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert tuple(row.cells for row in review.rows) == table.rows
    assert [column.candidate_role for column in review.columns] == [
        "invoice_id", "site", "status", "invoice_date", "due_date", "as_of_date",
        "balance", "aging_bucket", "aging_bucket", "credit_amount", "",
    ]
    assert review.rows[0].blank_roles == ("due_date", "credit_amount")
    assert review.rows[1].cells[3] == "03/04/2026"  # Date locale is unresolved.
    assert review.rows[1].blank_roles == ("due_date", "as_of_date", "aging_bucket", "aging_bucket")
    assert review.unknown_columns == (10,)
    assert review.missing_roles == ()
    assert len(review.pending_decisions) == 4
    assert review.rows[0].reference == table.reference + ":row:1"


def test_diagnostic_is_immutable_and_has_no_effect_on_existing_output_policy():
    table = source_table()
    before = table_has_pricing(table.columns, table.rows)
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert before and table_has_pricing(table.columns, table.rows)
    assert [c.index for c in review.columns if c.policy_controlled] == [6, 7, 8, 9]
    with pytest.raises(FrozenInstanceError):
        review.source_sha256 = "0" * 64
    assert source_table() == table


def test_repeated_conflicting_or_credit_invoice_rows_are_not_deduplicated_or_filtered():
    table = source_table()
    table = replace(table, rows=(table.rows[0], table.rows[0],
        (*table.rows[0][:2], "Closed", *table.rows[0][3:]), table.rows[1]))
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert tuple(row.cells for row in review.rows) == table.rows
    assert [row.position for row in review.rows] == [1, 2, 3, 4]
    assert len({row.reference for row in review.rows}) == 4


def test_duplicate_mapping_and_unknown_fields_stay_visible():
    table = ReportTable(("Invoice", "Invoice Number", "Date", "Amount of water", "Item"),
        (("INV-A", "INV-B", "03/04/26", "250 gallons", "CCJ-77"),), "source:table:1")
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert review.duplicate_roles == ("invoice_id",)
    assert review.unknown_columns == (2, 3, 4)
    assert review.missing_roles == ("site", "status", "due_date", "as_of_date")
    assert not any(column.policy_controlled for column in review.columns)
    assert review.rows[0].cells == table.rows[0]


def test_blank_invoice_identity_and_status_are_not_invented():
    table = ReportTable(("Invoice", "Facility", "Status"), (("", "", ""),), "source:1")
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert review.rows[0].blank_roles == ("invoice_id", "site", "status")
    assert review.rows[0].cells == ("", "", "")


@pytest.mark.parametrize("change", [
    {"reference": "source:other-table"},
    {"columns": ("Invoice number",)},
    {"rows": (("INV-2",),)},
])
def test_identity_changes_with_exact_source_table_contents(change):
    table = ReportTable(("Invoice",), (("INV-1",),), "source:table:1")
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert inspect_receivable_schema(table, source_sha256=DIGEST) == review
    assert inspect_receivable_schema(replace(table, **change), source_sha256=DIGEST).fingerprint != review.fingerprint
    assert inspect_receivable_schema(table, source_sha256="0" * 64).fingerprint != review.fingerprint


@pytest.mark.parametrize("digest", ["", "bad", "A" * 64, "g" * 64, None])
def test_missing_or_invalid_source_identity_is_rejected(digest):
    with pytest.raises(ValueError, match="SHA-256"):
        inspect_receivable_schema(source_table(), source_sha256=digest)


@pytest.mark.parametrize("table", [
    ReportTable(("Invoice",), (("INV-1",),), ""),
    ReportTable((), (), "source:1"),
    ReportTable(("Invoice",), (("INV-1", "extra"),), "source:1"),
    ReportTable(("Invoice",), ((None,),), "source:1"),
])
def test_unidentified_or_nonrectangular_source_is_rejected_without_padding(table):
    with pytest.raises(ValueError):
        inspect_receivable_schema(table, source_sha256=DIGEST)


def test_technical_current_and_ranges_are_not_mapped_as_aging():
    table = ReportTable(("Facility", "Current", "31-60", "Capacity"),
                        (("Synthetic North", "500", "600", "700"),), "source:1")
    review = inspect_receivable_schema(table, source_sha256=DIGEST)
    assert review.unknown_columns == (1, 2, 3)
    assert not any(column.policy_controlled for column in review.columns)
