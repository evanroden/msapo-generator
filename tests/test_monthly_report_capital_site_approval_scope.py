"""Synthetic regression: capital approvals cannot reach unselected contract sites.

No production imports, source files, amounts, or user identities are used here.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pymupdf

import pytest

from app import monthly_report_library as library
from app.monthly_report_capital_master import (
    CapitalItem,
    capital_report_block,
    load_capital_master,
    save_capital_master,
    select_capital,
)
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, default_sections,
)
from app.monthly_report_setup import new_month_draft
from app.pdf_converter import convert_to_pdf
from tests.conftest import requires_libreoffice


@pytest.fixture
def scopes(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    a = Facility("a", "Synthetic North")
    b = Facility("b", "Synthetic South")
    contract = "Synthetic Contract A"
    both = ReportProfile(contract, "both", "Both synthetic sites", (a, b),
                         scope_type="multi_site")
    north = ReportProfile(contract, "north", "North only", (a,))
    south = ReportProfile(contract, "south", "South only", (b,))
    other = ReportProfile("Synthetic Contract B", "other", "Other contract",
                          (Facility("b", "Different South"),))
    return both, north, south, other


def approve(profile, rows, revision=0):
    return save_capital_master(
        profile, tuple(rows), expected_revision=revision,
        actor="Synthetic reviewer", confirmed=True,
    )


def existing(scopes):
    both, _, _, _ = scopes
    return approve(both, (
        CapitalItem("north-boiler", "High", "Review boiler replacement",
                    asset="BOILER-01", site_keys=("a",),
                    source_reference="synthetic:capital:row-a"),
        CapitalItem("south-chiller", "Medium", "Inspect chiller",
                    asset="CHILLER-02", site_keys=("b",),
                    extra_fields=(("Condition", "Inspection pending"),),
                    source_reference="synthetic:capital:row-b"),
    ))


def test_new_item_cannot_be_approved_for_unselected_but_known_site(scopes):
    both, north, south, other = scopes
    initial = existing(scopes)
    new_item = CapitalItem(
        "south-roof", "Review", "Inspect roof before renewal",
        site_keys=("b",), extra_fields=(("Notes", "Timing not supplied"),),
    )
    # The contract already knows site b. Merely knowing the site is not
    # permission for a site-a report to publish a new shared site-b item.
    with pytest.raises(ValueError, match="selected facilit"):
        approve(north, (*initial.items, new_item), revision=1)
    assert load_capital_master(both.contract) == initial
    assert load_capital_master(both.contract, 1) == initial
    assert load_capital_master(other.contract).revision == 0
    assert [entry.item.key for entry in
            select_capital(south, initial, ReportPeriod(2026, 10)).occurrences] == [
                "south-chiller",
            ]

    # A deliberately selected multi-site review can approve that same entry.
    second = approve(both, (*initial.items, new_item), revision=1)
    assert second.revision == 2
    assert [entry.item.key for entry in
            select_capital(south, second, ReportPeriod(2026, 11)).occurrences] == [
                "south-chiller", "south-roof",
            ]
    assert [entry.item.key for entry in
            select_capital(north, second, ReportPeriod(2026, 11)).occurrences] == [
                "north-boiler",
            ]
    assert load_capital_master(both.contract, 1) == initial


def test_existing_row_cannot_expand_its_applicability_to_unselected_site(scopes):
    both, north, south, _ = scopes
    initial = existing(scopes)
    expanded = replace(initial.items[0], site_keys=("a", "b"))
    with pytest.raises(ValueError, match="selected facilit"):
        approve(north, (expanded, initial.items[1]), revision=1)
    assert load_capital_master(both.contract) == initial

    # An explicit review including both sites is allowed, with history intact.
    revised = approve(both, (expanded, initial.items[1]), revision=1)
    assert revised.revision == 2
    assert load_capital_master(both.contract, 1) == initial
    assert [entry.item.key for entry in
            select_capital(south, revised, ReportPeriod(2026, 10)).occurrences] == [
                "north-boiler", "south-chiller",
            ]
    assert revised.items[1] == initial.items[1]


def test_same_site_priority_correction_preserves_other_site_and_versions(scopes):
    both, north, south, other = scopes
    initial = existing(scopes)
    corrected = replace(
        initial.items[0], priority="Urgent",
        extra_fields=(("Condition", "Operator review pending"),),
    )
    second = approve(north, (corrected, initial.items[1]), revision=1)
    assert second.revision == 2
    assert second.items[1] == initial.items[1]
    assert load_capital_master(both.contract, 1) == initial
    assert load_capital_master(other.contract).revision == 0

    north_row = select_capital(north, second, ReportPeriod(2026, 11)).occurrences
    south_row = select_capital(south, second, ReportPeriod(2026, 11)).occurrences
    assert north_row[0].item.priority == "Urgent"
    assert north_row[0].item.extra_fields == (
        ("Condition", "Operator review pending"),)
    assert south_row[0].item == initial.items[1]
    with pytest.raises(library.RevisionConflict):
        approve(north, initial.items, revision=1)


def test_unknown_timing_stays_blank_and_vendor_totals_cannot_be_promoted(scopes):
    both, _, _, _ = scopes
    first = existing(scopes)
    assert first.items[1].target_date == ""
    assert first.items[1].extra_fields == (
        ("Condition", "Inspection pending"),)
    forbidden = replace(first.items[0], extra_fields=(
        ("Vendor invoice total", "$7,500"),))
    with pytest.raises(ValueError, match="Financial|financial"):
        approve(both, (forbidden, first.items[1]), revision=1)
    assert load_capital_master(both.contract) == first


def _restored_rolled_south(scopes):
    both, _, south, _ = scopes
    master = existing(scopes)
    period = ReportPeriod(2026, 9)
    section = next(s for s in default_sections() if s.key == "capital")
    block = capital_report_block(south, select_capital(south, master, period))
    draft = ReportDraft(south, period, "Synthetic reviewer", (section,),
                        (block,), synthetic=True)
    library.save_snapshot(draft, expected_revision=0)
    restored = library.load_snapshot(south.contract, south.key, period).draft
    assert restored == draft

    # A later approved contract version must not rewrite a saved report.
    changed = replace(master.items[0], priority="Urgent")
    later = approve(both, (changed, master.items[1]), revision=1)
    assert later.revision == 2
    assert library.load_snapshot(south.contract, south.key, period).draft == draft
    next_month = new_month_draft(restored, ReportPeriod(2026, 10))
    assert next_month.blocks[0].references == (master.reference,)
    assert next_month.blocks[0].rows == block.rows
    assert len(next_month.blocks[0].rows) == 1
    return next_month


def test_saved_monthly_south_report_keeps_reviewed_rows_in_word(scopes):
    rolled = _restored_rolled_south(scopes)
    raw = assemble_docx(rolled, acknowledged_fingerprint=rolled.fingerprint)
    word = Document(BytesIO(raw))
    cells = [cell.text for table in word.tables
             for row in table.rows for cell in row.cells]
    assert cells.count("Inspect chiller") == 1
    assert cells.count("CHILLER-02") == 1
    assert "Review boiler replacement" not in cells
    assert "Synthetic North" not in cells
    assert "Medium" in cells


@requires_libreoffice
def test_saved_monthly_south_report_pdf_retains_scope_and_text(scopes, tmp_path):
    rolled = _restored_rolled_south(scopes)
    word = tmp_path / "synthetic-capital.docx"
    word.write_bytes(
        assemble_docx(rolled, acknowledged_fingerprint=rolled.fingerprint))
    pdf_path = convert_to_pdf(word)
    with pymupdf.open(str(pdf_path)) as pdf:
        assert len(pdf) >= 1
        readable = " ".join(" ".join(p.get_text().split()) for p in pdf)
        assert "Inspect chiller" in readable
        assert "CHILLER-02" in readable
        assert "Review boiler replacement" not in readable
        assert "Synthetic North" not in readable
