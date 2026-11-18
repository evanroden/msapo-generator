"""Synthetic directory source: unnamed detail is reviewable, never a person.

Refs #270 #288 #289 #789. No customer contacts or workbook bytes are stored.
"""
from dataclasses import replace

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from test_monthly_report_directory_batch import workbook, summary, detail


@pytest.fixture(autouse=True)
def isolated_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def _source():
    # Two sites intentionally share a person's display name, not their phone.
    # Another legitimate person has the same role at North. C14 belongs to
    # nobody: a role band and phone are not evidence of an individual.
    cells = detail(
        B9="Synthetic Shared Lead", B10="202-555-0101",
        C6="Synthetic South", C9="Synthetic Shared Lead", C10="202-555-0102",
        A13="Facility Director", A14="Phone", A15="Email",
        B13="Synthetic Alternate Lead", B14="202-555-0103",
        C14="202-555-0199",
    )
    return workbook((
        ("Active Contracts", summary()),
        ("Synthetic Contract Sites", cells),
        # A copied site heading on an unknown contract tab is not membership.
        ("Unreviewed Other Contract Sites", detail(B9="Synthetic Foreign Lead")),
    ))


def _parsed(raw):
    book = directory.inspect_workbook(raw)
    sheet = next(s for s in book.sheets if s.name == "Synthetic Contract Sites")
    return book, sheet, directory.suggest_matrix(sheet)


def _by_site(sites):
    return {site.title: site for site in sites}


def test_directory_does_not_promote_phone_only_row_and_exposes_source_coordinates():
    raw = _source()
    before = bytes(raw)
    book, sheet, mapping = _parsed(raw)
    sites = _by_site(directory.matrix_sites(book, sheet, *mapping))

    assert [c.name for c in sites["Synthetic North"].contacts] == [
        "Synthetic Shared Lead", "Synthetic Alternate Lead"]
    assert [c.phone for c in sites["Synthetic North"].contacts] == [
        "202-555-0101", "202-555-0103"]
    assert [(c.name, c.phone) for c in sites["Synthetic South"].contacts] == [
        ("Synthetic Shared Lead", "202-555-0102")]
    assert all(c.name for site in sites.values() for c in site.contacts)
    assert sheet.values()[(14, 3)] == "202-555-0199"
    assert any("C14" in notice and "Facility Director" in notice
               for notice in directory.sheet_findings(book, sheet))
    assert raw == before


def test_batch_preserves_other_contacts_and_sites_across_reimport_and_undo():
    raw = _source()
    before = bytes(raw)
    book, _, _ = _parsed(raw)
    plan = batch.prepare_workbook(book)
    assert len(plan.entries) == 1
    assert plan.entries[0].contract == "Synthetic Contract"
    assert any("Unreviewed Other Contract Sites" == ex.worksheet
               for ex in plan.exclusions)
    assert any(ex.worksheet == "Synthetic Contract Sites" and "C14" in ex.column
               for ex in plan.exclusions)
    entry = plan.entries[0]
    sites = _by_site(entry.sites)
    assert len(sites["Synthetic North"].contacts) == 2
    assert len(sites["Synthetic South"].contacts) == 1
    assert sites["Synthetic North"].contacts[0].name == sites["Synthetic South"].contacts[0].name
    assert sites["Synthetic North"].contacts[0].phone != sites["Synthetic South"].contacts[0].phone

    create = tuple(e.contract for e in plan.entries if e.new_contract)
    first = batch.save_workbook_plan(plan, raw, actor="Synthetic Editor",
                                     confirmed=True, create=create)
    assert first.saved == ("Synthetic Contract",)
    stored = directory.load_directory("Synthetic Contract")
    assert stored.revision == 1 and stored.sites == entry.sites
    assert raw == before

    again = batch.prepare_workbook(directory.inspect_workbook(raw))
    second = batch.save_workbook_plan(again, raw, actor="Synthetic Editor",
                                      confirmed=True, create=())
    assert second.unchanged == ("Synthetic Contract",) and not second.saved
    assert directory.load_directory("Synthetic Contract") == stored

    # Explicit replacement and undo must not shift the same-named person in
    # another site, remove the alternate row, or change contract-wide contacts.
    north = sites["Synthetic North"]
    changed = replace(north, contacts=(
        replace(north.contacts[0], phone="202-555-0177"), *north.contacts[1:]))
    directory.save_directory(
        stored.contract, tuple(changed if site.key == north.key else site
                               for site in stored.sites),
        expected_revision=1, actor="Synthetic Editor", confirmed=True)
    undone = directory.restore_directory(stored.contract, 1, expected_revision=2,
                                         actor="Synthetic Editor", confirmed=True)
    assert undone.sites == stored.sites
    assert undone.contract_contacts == stored.contract_contacts
    assert directory.load_directory(stored.contract) == undone
    assert raw == before


@pytest.mark.parametrize("bad", (b"", b"not-an-xlsx"))
def test_bad_workbook_never_creates_directory_records(bad):
    with pytest.raises((ValueError, OSError)):
        directory.inspect_workbook(bad)
    assert directory.load_directory("Synthetic Contract") is None


def test_physical_merged_vendor_bands_keep_unidentified_detail_for_manual_review(tmp_path):
    """The Word trade-band sibling uses the same fail-closed identity rule."""
    from docx import Document

    from app.monthly_report_import import ImportMapping, inspect_docx, map_items
    from app.monthly_report_vendor_groups import grouped_vendor_contacts

    rows = (
        ("Vendor", "Contact", "Phone"),
        ("HVAC", "", ""),
        ("Repeated Synthetic Vendor", "Synthetic First", "202-555-0101"),
        ("", "", "202-555-0199"),
        ("Vendor", "Contact", "Phone"),
        ("Electrical", "", ""),
        ("Repeated Synthetic Vendor", "Synthetic Second", "202-555-0102"),
    )
    document = Document()
    document.add_heading("6 Sub-Contractor Status", 1)
    table = document.add_table(rows=len(rows), cols=3)
    for index, cells in enumerate(rows):
        if index in (1, 5):
            table.rows[index].cells[0].merge(table.rows[index].cells[-1]).text = cells[0]
        else:
            for cell, value in zip(table.rows[index].cells, cells):
                cell.text = value
    path = tmp_path / "synthetic-merged-vendors.docx"
    document.save(path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    item = next(item for item in inspection.items if item.kind == "table"
                and any("Repeated Synthetic Vendor" in cell for row in item.rows for cell in row))
    assert item.merged_title_rows == (1, 5)
    assert grouped_vendor_contacts(item) is None
    mapped = map_items(path, inspection, (ImportMapping(item.id, "subcontractor_matrix"),))
    assert mapped.blocks[0].rows == item.rows[1:]
    assert ("", "", "202-555-0199") in mapped.blocks[0].rows
    assert path.read_bytes() == original


def test_stale_manual_contact_and_unrelated_site_survive_same_source_reimport():
    raw = _source()
    plan = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert batch.save_workbook_plan(
        plan, raw, actor="Synthetic Editor", confirmed=True,
        create=tuple(e.contract for e in plan.entries if e.new_contract)).saved
    original = directory.load_directory("Synthetic Contract")
    stale = directory.DirectoryContact("Former Supervisor", "Synthetic Historic Lead",
                                       "202-555-0188", source="synthetic:reviewed")
    north, south = original.sites
    west = directory.DirectorySite("manual-west", "Synthetic West", contacts=(
        directory.DirectoryContact("Site Lead", "Synthetic West Lead"),))
    revised = directory.save_directory(
        original.contract, (replace(north, contacts=(*north.contacts, stale)), south, west),
        expected_revision=1, actor="Synthetic Editor", confirmed=True)
    plan2 = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert len(plan2.entries) == 1 and not plan2.entries[0].changed
    assert plan2.entries[0].sites == revised.sites
    result = batch.save_workbook_plan(plan2, raw, actor="Synthetic Editor", confirmed=True)
    assert result.unchanged == ("Synthetic Contract",) and not result.saved
    reloaded = directory.load_directory(original.contract)
    assert reloaded == revised
    assert reloaded.sites[0].contacts[-1] == stale
    assert reloaded.sites[-1] == west
