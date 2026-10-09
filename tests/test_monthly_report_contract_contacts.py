"""Contract-wide directory records use synthetic people and sites only."""

from dataclasses import asdict, replace

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.monthly_report_model import Facility


CONTRACT = "Synthetic Contract"
ACTOR = "Synthetic Editor"
LEAD = directory.DirectoryContact(
    "Asset Manager", "Synthetic Lead", "202-555-0100", "lead@example.invalid", "summary:A3"
)
SITE = directory.DirectorySite("north", "Synthetic North", contacts=(
    directory.DirectoryContact("Site Manager", "Synthetic Site Lead", source="detail:B9"),
))


@pytest.fixture(autouse=True)
def isolated_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def save(sites=(), *, revision=0, **kwargs):
    return directory.save_directory(CONTRACT, sites, expected_revision=revision,
                                    actor=ACTOR, confirmed=True, **kwargs)


def test_old_directory_without_contract_contacts_still_loads():
    old = directory.DirectoryState(CONTRACT, 1, (SITE,), ACTOR, "2026-10-09T00:00:00Z")
    payload = asdict(old)
    payload.pop("contract_contacts")
    migrated = directory._state(payload)
    assert migrated == old
    assert migrated.contract_contacts == ()


def test_contract_only_directory_persists_without_inventing_sites():
    first = save(contract_contacts=(LEAD,))
    assert first.sites == ()
    assert first.contract_contacts == (LEAD,)
    assert directory.load_directory(CONTRACT) == first
    assert directory.load_directory(CONTRACT, 1) == first
    assert directory.directory_contracts() == (CONTRACT,)
    catalog = (Facility("catalog-site", "Synthetic Catalog Site"),)
    assert directory.available_sites(catalog, first) == catalog
    assert directory.suggest_contact_bindings(first, catalog) == {"catalog-site": ""}


def test_existing_site_edits_preserve_contract_contacts_until_explicitly_changed():
    save((SITE,), contract_contacts=(LEAD,))
    updated_site = replace(SITE, title="Synthetic North Campus")
    second = save((updated_site,), revision=1)
    assert second.sites == (updated_site,)
    assert second.contract_contacts == (LEAD,)
    third = save((updated_site,), revision=2, contract_contacts=())
    assert third.contract_contacts == ()


def test_contract_only_save_can_preserve_contacts_and_cannot_clear_last_record():
    save(contract_contacts=(LEAD,))
    assert save(revision=1).contract_contacts == (LEAD,)
    with pytest.raises(ValueError, match="at least one"):
        save(revision=2, contract_contacts=())
    assert directory.load_directory(CONTRACT).revision == 2
    assert directory.load_directory(CONTRACT).contract_contacts == (LEAD,)


def test_empty_new_directory_and_unconfirmed_contacts_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        save()
    assert directory.load_directory(CONTRACT) is None
    with pytest.raises(library.LibraryError):
        directory.save_directory(CONTRACT, (), expected_revision=0, actor=ACTOR,
                                 confirmed=False, contract_contacts=(LEAD,))
    assert directory.load_directory(CONTRACT) is None


@pytest.mark.parametrize("contacts,message", [
    ((LEAD,) * (directory.MAX_CONTACTS + 1), "review budget"),
    ((replace(LEAD, name="x" * 2001),), "review budget"),
    ((replace(LEAD, source="x" * 2001),), "review budget"),
    ((replace(LEAD, role="  "),), "needs a role"),
])
def test_contract_contact_validation_preserves_existing_revision(contacts, message):
    first = save(contract_contacts=(LEAD,))
    with pytest.raises(ValueError, match=message):
        save(revision=1, contract_contacts=contacts)
    assert directory.load_directory(CONTRACT) == first


def test_stale_contract_contact_update_cannot_overwrite_newer_contacts():
    save(contract_contacts=(LEAD,))
    updated = replace(LEAD, email="updated@example.invalid")
    second = save(revision=1, contract_contacts=(updated,))
    with pytest.raises(library.RevisionConflict):
        save(revision=1, contract_contacts=(LEAD,))
    assert directory.load_directory(CONTRACT) == second


def test_archive_and_restore_preserve_exact_historical_contract_contacts():
    first = save(contract_contacts=(LEAD,))
    second = save(revision=1, contract_contacts=(replace(LEAD, name="Synthetic Replacement"),))
    archived = directory.archive_directory(CONTRACT, expected_revision=2, actor=ACTOR, confirmed=True)
    assert archived.contract_contacts == second.contract_contacts
    assert directory.load_directory(CONTRACT) is None
    assert directory.load_directory(CONTRACT, include_archived=True) == archived
    restored = directory.restore_directory(CONTRACT, 1, expected_revision=3, actor=ACTOR, confirmed=True)
    assert restored.contract_contacts == first.contract_contacts
    assert not restored.archived
    assert restored.sites == ()
    assert restored.action == "restore:1"


def test_restoring_legacy_revision_does_not_copy_new_contract_contacts_backwards():
    first = save((SITE,))
    save((SITE,), revision=1, contract_contacts=(LEAD,))
    restored = directory.restore_directory(CONTRACT, 1, expected_revision=2, actor=ACTOR, confirmed=True)
    assert restored.contract_contacts == first.contract_contacts == ()


def test_contract_rows_are_once_per_report_and_do_not_create_site_bindings():
    state = save(contract_contacts=(LEAD,))
    facilities = (Facility("north", "Synthetic North"), Facility("south", "Synthetic South"))
    block, missing = directory.contact_block(state, facilities)
    assert not missing
    assert block.rows == ((CONTRACT + " (contract-wide)", LEAD.role, LEAD.name, LEAD.phone, LEAD.email),)
    assert len(block.references) == 1
    assert block.references[0].startswith("directory:")
    assert not any(ref.startswith("directory-site:") for ref in block.references)


def test_mixed_directory_keeps_explicit_site_match_requirement():
    state = save((SITE,), contract_contacts=(LEAD,))
    facilities = (SITE.facility, Facility("south", "Synthetic South"))
    block, missing = directory.contact_block(state, facilities)
    assert missing == ("Synthetic South",)
    assert len(block.rows) == 2
    assert block.rows[0][0] == CONTRACT + " (contract-wide)"
    assert block.rows[1][0] == SITE.title
    assert "directory-site:north:north" in block.references


def test_sustainability_sales_and_zero_fields_are_normalized_only_at_contact_mapping():
    values = {
        (2, 1): "Facility", (2, 2): "Synthetic North", (2, 3): "Synthetic South",
        (3, 1): "Address", (3, 2): "0",
        (5, 1): "Sustainability", (5, 2): "0", (5, 3): "Synthetic Sustainability Lead",
        (6, 1): "Phone", (6, 2): "0.0", (6, 3): "0",
        (7, 1): "Email", (7, 2): "0", (7, 3): "sustainability@example.invalid",
        (9, 1): "Sales", (9, 2): "Vacant", (9, 3): "TBD",
        (10, 1): "Phone", (10, 2): "0", (10, 3): "0.00",
    }
    sheet = directory.DirectorySheet("Synthetic Detail", tuple(
        directory.DirectoryCell(r, c, value) for (r, c), value in values.items()
    ))
    book = directory.DirectoryWorkbook("a" * 64, (sheet,), ())
    mapping = directory.suggest_matrix(sheet)
    assert [group["Role"] for group in mapping[3]] == ["Sustainability", "Sales"]
    north, south = directory.matrix_sites(book, sheet, *mapping)
    assert north.address == "0"
    assert sheet.values()[(5, 2)] == "0"
    assert [c.role for c in north.contacts] == ["Sales"]
    assert north.contacts[0].name == "Vacant"
    assert south.contacts[0].phone == ""
    assert south.contacts[0].email == "sustainability@example.invalid"
    assert south.contacts[1].name == "TBD"
    assert all(c.phone != "0" for site in (north, south) for c in site.contacts)


def test_zero_only_contact_matrix_is_reported_as_unpopulated():
    sheet = directory.DirectorySheet("Synthetic Detail", (
        directory.DirectoryCell(1, 1, "Facility"), directory.DirectoryCell(1, 2, "Synthetic North"),
        directory.DirectoryCell(2, 1, "Sales"), directory.DirectoryCell(2, 2, "0"),
    ))
    book = directory.DirectoryWorkbook("a" * 64, (sheet,), ())
    assert any("No populated" in finding for finding in directory.sheet_findings(book, sheet))
