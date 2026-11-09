"""Merged vendor group auto-import must never invent unnamed contact records.

Refs #789 and #455. Synthetic physical source rows only; no shared data.
"""

from types import SimpleNamespace

from app.monthly_report_model import ReportTable
from app.monthly_report_vendor_groups import grouped_vendor_contacts


def original(rows, *, merged=(1,)):
    return SimpleNamespace(rows=rows, merged_title_rows=merged)


def test_phone_only_detail_inside_real_band_requires_manual_mapping():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("HVAC", "", ""),
        ("Invented Vendor", "Invented Technician", "555-0101"),
        ("", "", "Call to confirm an appointment before assigning."),
    )
    item = original(rows)
    assert grouped_vendor_contacts(item) is None
    # An unsafe automatic grouping must never remove or edit the source table.
    assert item.rows == rows


def test_blank_name_with_other_detail_is_not_an_invented_vendor():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("HVAC", "", ""),
        ("Invented Vendor", "Invented Technician", "555-0101"),
        ("", "", "555-0199"),
    )
    assert grouped_vendor_contacts(original(rows)) is None


def test_named_contact_with_blank_vendor_is_still_a_record():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("HVAC", "", ""),
        ("Invented Vendor", "Invented Technician", "555-0101"),
        ("", "Additional Invented Contact", "555-0102"),
    )
    assert grouped_vendor_contacts(original(rows)) == ReportTable(
        ("Discipline", "Vendor", "Contact", "Phone"),
        (("HVAC", "Invented Vendor", "Invented Technician", "555-0101"),
         ("HVAC", "", "Additional Invented Contact", "555-0102")),
    )


def test_named_vendor_with_blank_contact_remains_a_record():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("Electrical", "", ""),
        ("Invented Electrical Co", "", "555-0103"),
    )
    assert grouped_vendor_contacts(original(rows)) == ReportTable(
        ("Discipline", "Vendor", "Contact", "Phone"),
        (("Electrical", "Invented Electrical Co", "", "555-0103"),),
    )


def test_grouped_vendor_ignores_only_true_spacers_and_repeated_headers():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("HVAC", "", ""),
        ("Invented HVAC Co", "", "555-0101"),
        ("", "", ""),
        ("Vendor", "Contact", "Phone"),
        ("Electrical", "", ""),
        ("Invented Electrical Co", "", "555-0103"),
    )
    assert grouped_vendor_contacts(original(rows, merged=(1, 5))) == ReportTable(
        ("Discipline", "Vendor", "Contact", "Phone"),
        (("HVAC", "Invented HVAC Co", "", "555-0101"),
         ("Electrical", "Invented Electrical Co", "", "555-0103")),
    )


def test_category_column_does_not_turn_a_note_into_contact():
    rows = (
        ("Trade", "Vendor", "Contact", "Phone"),
        ("Electrical", "", "", ""),
        ("", "Invented Electrical Co", "", "555-0103"),
        ("", "", "", "Call vendor next month."),
    )
    assert grouped_vendor_contacts(original(rows)) is None
    assert rows[3][-1] == "Call vendor next month."


def test_named_contact_with_explicit_category_preserves_original_column_order():
    rows = (
        ("Trade", "Vendor", "Contact", "Phone"),
        ("Electrical", "", "", ""),
        ("", "", "Additional Invented Contact", "555-0102"),
    )
    assert grouped_vendor_contacts(original(rows)) == ReportTable(
        ("Trade", "Vendor", "Contact", "Phone"),
        (("Electrical", "", "Additional Invented Contact", "555-0102"),),
    )


def test_single_non_identifying_row_without_any_valid_contact_is_not_auto_imported():
    rows = (
        ("Vendor", "Contact", "Phone"),
        ("Electrical", "", ""),
        ("", "", "555-0103"),
    )
    assert grouped_vendor_contacts(original(rows)) is None
