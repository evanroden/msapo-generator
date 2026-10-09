"""Synthetic workbook regression cases; no uploaded owner contacts are fixtures."""

from dataclasses import replace
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app import monthly_report_library as library


def workbook(sheets):
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        entries = "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="r{i}"/>'
                          for i, (name, _) in enumerate(sheets, 1))
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{directory.S[1:-1]}" xmlns:r="{directory.R[1:-1]}"><sheets>{entries}</sheets></workbook>')
        rels = "".join(f'<Relationship Id="r{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                       for i in range(1, len(sheets) + 1))
        archive.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, (_, values) in enumerate(sheets, 1):
            cells = "".join(f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>' for coordinate, value in values.items())
            archive.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{directory.S[1:-1]}"><sheetData><row>{cells}</row></sheetData></worksheet>')
    return stream.getvalue()


def summary(**overrides):
    return {"A6": "Contract", "B6": "Synthetic Contract", "A7": "Address", "B7": "100 Example Way",
            "A9": "Executive Director", "B9": "Synthetic Executive", "A10": "Phone", "B10": "202-555-0100",
            "A11": "Email", "B11": "executive@example.invalid", **overrides}


def detail(**overrides):
    return {"A6": "Facility", "B6": "Synthetic North", "A7": "Address", "B7": "100 Example Way",
            "A9": "Facility Director", "B9": "Synthetic Site Lead", "A10": "Phone", "B10": "202-555-0101",
            "A11": "Email", "B11": "site@example.invalid", **overrides}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def prepared(*sheets):
    raw = workbook(sheets or (("Active Contracts", summary()), ("Synthetic Contract Sites", detail())))
    return raw, batch.prepare_workbook(directory.inspect_workbook(raw))


def save(plan, raw):
    return batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=True)


def test_summary_contacts_remain_contract_wide_and_site_membership_is_explicit(tmp_path):
    raw, plan = prepared()
    assert len(plan.entries) == 1 and plan.site_count == 1 and plan.contact_count == 2
    entry = plan.entries[0]
    assert entry.contract == "Synthetic Contract"
    assert [s.title for s in entry.sites] == ["Synthetic North"]
    assert entry.contract_contacts[0].name == "Synthetic Executive"
    assert entry.sites[0].contacts[0].name == "Synthetic Site Lead"
    assert not (tmp_path / "monthly_reports" / "directory").exists()
    assert save(plan, raw).saved == ("Synthetic Contract",)
    state = directory.load_directory("Synthetic Contract")
    assert len(state.sites) == 1 and len(state.contract_contacts) == 1
    assert state.contract_contacts[0].source.endswith("Active Contracts!B9,B10,B11")
    assert state.sites[0].contacts[0].source.endswith("Synthetic Contract Sites!B9,B10,B11")


def test_summary_only_contract_never_gets_a_bogus_site():
    raw, plan = prepared(("Active Contracts", summary(B6="Synthetic New Account")))
    entry = plan.entries[0]
    assert not entry.sites and entry.contract_contacts
    assert save(plan, raw).saved == ("Synthetic New Account",)
    assert directory.load_directory("Synthetic New Account").sites == ()


def test_inactive_empty_ambiguous_and_index_columns_are_excluded():
    raw, plan = prepared(("Index", {"A1": "Contents"}),
        ("Active Contracts", summary(C6="INACTIVE WATER CAMPUS CLOSED", C9="Synthetic Old Lead", D6="Synthetic Empty", E6="Hartford Health", E9="Synthetic Held Lead")),
        ("Hartford Health Sites", detail()))
    assert len(plan.entries) == 1
    assert {(e.worksheet, e.column) for e in plan.exclusions} == {
        ("Index", ""), ("Active Contracts", "C6"), ("Active Contracts", "D6"),
        ("Active Contracts", "E6"), ("Hartford Health Sites", "")}
    assert save(plan, raw).saved == ("Synthetic Contract",)


def test_review_mapping_exposes_cells_roles_and_scope():
    _, plan = prepared()
    assert [(m.scope, m.header_row, m.label_column, m.address_row) for m in plan.mappings] == [
        ("contract", 6, 1, 7), ("site", 6, 1, 7)]
    assert plan.mappings[0].targets == (("B6", "Synthetic Contract"),)
    assert plan.mappings[1].groups == (batch.ContactRows("Facility Director", 9, 10, 11),)


def test_exact_reimport_is_a_noop_without_new_history():
    raw, first = prepared()
    assert save(first, raw).saved
    again = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert not again.entries[0].changed
    result = save(again, raw)
    assert result.unchanged == ("Synthetic Contract",) and not result.saved
    assert directory.load_directory("Synthetic Contract").revision == 1


def test_existing_sites_roles_and_identity_survive_a_partial_import():
    old = directory.DirectorySite("stable-north", "Synthetic North Campus", ("Synthetic North",),
        contacts=(directory.DirectoryContact("Night Supervisor", "Synthetic Night Lead"),))
    untouched = directory.DirectorySite("stable-west", "Synthetic West")
    directory.save_directory("Synthetic Contract", (old, untouched), expected_revision=0, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Administrator"),))
    raw, plan = prepared()
    assert not plan.entries[0].conflicts
    assert [s.key for s in plan.entries[0].sites] == ["stable-north", "stable-west"]
    assert plan.entries[0].sites[0].title == old.title
    assert len(plan.entries[0].sites[0].contacts) == 2
    assert len(plan.entries[0].contract_contacts) == 2
    assert save(plan, raw).saved


def test_conflicting_populated_person_or_contact_fields_block_that_contract():
    raw, first = prepared()
    save(first, raw)
    changed_raw, plan = prepared(("Active Contracts", summary(B9="Synthetic Replacement")),
                                ("Synthetic Contract Sites", detail(B10="202-555-0199")))
    entry = plan.entries[0]
    assert len(entry.conflicts) == 2 and not entry.can_save
    assert entry.contract_contacts[0].name == "Synthetic Executive"
    assert entry.sites[0].contacts[0].phone == "202-555-0101"
    result = save(plan, changed_raw)
    assert result.blocked and not result.saved
    assert directory.load_directory("Synthetic Contract").revision == 1


def test_same_person_missing_field_can_be_filled_without_erasing_saved_data():
    raw, first = prepared(("Active Contracts", summary(B11="")))
    save(first, raw)
    raw, plan = prepared(("Active Contracts", summary(B10="")))
    assert not plan.entries[0].conflicts
    assert plan.entries[0].contract_contacts[0].phone == "202-555-0100"
    assert plan.entries[0].contract_contacts[0].email == "executive@example.invalid"
    assert save(plan, raw).saved


def test_named_person_never_inherits_an_unidentified_phone_record():
    directory.save_directory("Synthetic Contract", (), expected_revision=0, actor="Synthetic Editor", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Executive Director", phone="202-555-0199"),))
    _, plan = prepared(("Active Contracts", summary(B10="")))
    assert any("contact identity" in c for c in plan.entries[0].conflicts)


def test_only_exact_or_explicit_aliases_link_a_contract_and_site(monkeypatch):
    monkeypatch.setattr(batch.contract_catalog, "contract_names", lambda: ["Synthetic Contract"])
    monkeypatch.setattr(batch.contract_catalog, "sites_for_contract", lambda contract: ["Synthetic North Campus"])
    raw = workbook((("Active Contracts", summary(B6="Synthetic Alternate")), ("Synthetic Alternate Sites", detail())))
    plan = batch.prepare_workbook(directory.inspect_workbook(raw),
        contract_aliases={"Synthetic Alternate": "Synthetic Contract"},
        site_aliases={"Synthetic Contract": {"Synthetic North": "Synthetic North Campus"}})
    assert len(plan.entries) == 1
    site = plan.entries[0].sites[0]
    assert site.key == "synthetic-north-campus" and site.title == "Synthetic North Campus"
    assert "Synthetic North" in site.aliases
    raw, unmatched = prepared(("Active Contracts", summary()), ("Synthetic Contra Sites", detail()))
    assert unmatched.site_count == 0
    assert "does not exactly match" in unmatched.exclusions[0].reason


def test_copied_headings_and_two_columns_for_one_site_are_never_silently_merged():
    _, plan = prepared(("Active Contracts", summary(C6="Synthetic Other", C9="Synthetic Other Lead")),
                       ("Synthetic Contract Sites", detail()), ("Synthetic Other Sites", detail()))
    assert plan.site_count == 0 and len(plan.exclusions) == 2
    raw = workbook((("Active Contracts", summary()), ("Synthetic Contract Sites", detail(C6="Synthetic North", C9="Synthetic Second Lead"))))
    plan = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert any("two workbook columns" in c for c in plan.entries[0].conflicts)


def test_stale_preview_and_archived_records_require_fresh_review():
    raw, plan = prepared()
    save(plan, raw)
    stale = save(plan, raw)
    assert not stale.saved and "changed after the preview" in stale.blocked[0][1]
    directory.archive_directory("Synthetic Contract", expected_revision=1, actor="Synthetic Editor", confirmed=True)
    archived = batch.prepare_workbook(directory.inspect_workbook(raw))
    assert "archived" in archived.entries[0].conflicts[0]
    assert save(archived, raw).blocked


def test_batch_reports_partial_success_and_keeps_other_contracts(monkeypatch):
    raw, plan = prepared(("Active Contracts", summary(C6="Synthetic Other", C9="Synthetic Other Lead")))
    original = directory.save_directory
    def fail_one(contract, *args, **kwargs):
        if contract == "Synthetic Other":
            raise OSError("Synthetic unavailable disk")
        return original(contract, *args, **kwargs)
    monkeypatch.setattr(directory, "save_directory", fail_one)
    result = save(plan, raw)
    assert result.saved == ("Synthetic Contract",)
    assert result.failed == (("Synthetic Other", "Synthetic unavailable disk"),)
    assert directory.load_directory("Synthetic Contract").revision == 1
    assert directory.load_directory("Synthetic Other") is None


def test_confirmation_workbook_hash_and_selection_are_bound_to_review():
    raw, plan = prepared()
    with pytest.raises(library.LibraryError):
        batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=False)
    with pytest.raises(ValueError, match="workbook changed"):
        save(plan, raw + b"changed")
    with pytest.raises(ValueError, match="unreviewed contract"):
        batch.save_workbook_plan(plan, raw, actor="Synthetic Editor", confirmed=True, contracts=("Unreviewed",))
    assert not directory.directory_contracts()


def test_noop_plan_also_checks_revision_before_claiming_unchanged():
    raw, plan = prepared()
    save(plan, raw)
    noop = batch.prepare_workbook(directory.inspect_workbook(raw))
    state = directory.load_directory("Synthetic Contract")
    directory.save_directory(state.contract, state.sites, expected_revision=1, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(replace(state.contract_contacts[0], email="updated@example.invalid"),))
    result = save(noop, raw)
    assert not result.unchanged and result.blocked
