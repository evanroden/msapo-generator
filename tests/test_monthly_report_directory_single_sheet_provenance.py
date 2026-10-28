"""Single-sheet contact corrections must not exhaust their provenance budget.

Refs #288. All workbooks and contacts are synthetic. The ordinary inspected
worksheet/proposal/save pipeline is exercised against isolated durable storage.
"""

from dataclasses import replace

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_retention as retention
from test_monthly_report_directory_batch import detail, workbook


CONTRACT = "Synthetic Provenance"
SHEET = CONTRACT + " Sites"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def _workbook(correction, sheet_name=SHEET):
    return workbook(((sheet_name, detail(B10=f"202-555-{correction:04d}")),))


def _proposal(raw):
    inspected = directory.inspect_workbook(raw)
    sheet, = inspected.sheets
    incoming, = directory.matrix_sites(inspected, sheet, *directory.suggest_matrix(sheet))
    previous = directory.load_directory(CONTRACT)
    if previous:
        old, = previous.sites
        incoming = replace(incoming, key=old.key,
                           contacts=directory.proposed_contacts(old.contacts, incoming.contacts))
    return inspected, incoming, previous


def _save(raw):
    inspected, site, previous = _proposal(raw)
    state = directory.save_directory(
        CONTRACT, (site,), expected_revision=previous.revision if previous else 0,
        actor="Synthetic Reviewer", confirmed=True, raw=raw,
        source_sha256=inspected.sha256, source_sheet=inspected.sheets[0].name)
    reloaded = directory.load_directory(CONTRACT)
    assert reloaded == state
    return state


@pytest.mark.parametrize("sheet_name", [SHEET, "Synthetic;Provenance Sites"])
def test_repeated_single_sheet_corrections_save_without_rewriting_originals_or_history(sheet_name):
    original_bytes, history_bytes, references = {}, {}, []
    for correction in range(30):
        raw = _workbook(correction, sheet_name)
        state = _save(raw)
        contact, = state.sites[0].contacts
        assert contact.phone == f"202-555-{correction:04d}"
        assert contact.name == "Synthetic Site Lead"
        assert contact.email == "site@example.invalid"
        reference = f"{state.source_sha256}:{sheet_name}!B9,B10,B11"
        references.append(reference)
        original_bytes[retention._sources() / (state.source_sha256 + ".xlsx")] = raw
        history = directory._path(CONTRACT) / "history" / f"{state.revision:08d}.json"
        history_bytes[history] = history.read_bytes()

    latest = directory.load_directory(CONTRACT)
    assert latest.revision == 30
    contact, = latest.sites[0].contacts
    kept = [reference for reference in references if reference in contact.source]
    assert contact.source == ";".join(kept)  # no partial worksheet/cell references
    assert len(contact.source) <= 1000
    assert kept[0] == references[0]
    assert kept[-1] == references[-1]
    assert kept[1:] == references[-(len(kept) - 1):]
    assert references[1] not in kept  # its original and revision still exist below
    for path, raw in original_bytes.items():
        assert path.read_bytes() == raw
    for path, raw in history_bytes.items():
        assert path.read_bytes() == raw
    assert directory.load_directory(CONTRACT, 1).sites[0].contacts[0].phone == "202-555-0000"


def test_single_sheet_replay_and_missing_fields_do_not_change_saved_provenance():
    state = _save(_workbook(0))
    state = _save(_workbook(1))
    before = state.sites[0].contacts
    _, same, _ = _proposal(_workbook(1))
    assert same.contacts == before
    omitted = workbook(((SHEET, detail(B10="", B11="")),))
    _, partial, _ = _proposal(omitted)
    assert partial.contacts == before


def test_single_sheet_new_person_does_not_inherit_the_previous_person_or_provenance():
    _save(_workbook(0))
    replacement = workbook(((SHEET, detail(B9="Synthetic Replacement", B10="", B11="")),))
    state = _save(replacement)
    contact, = state.sites[0].contacts
    assert (contact.name, contact.phone, contact.email) == ("Synthetic Replacement", "", "")
    assert contact.source == f"{state.source_sha256}:{SHEET}!B9,B10,B11"


def test_single_sheet_update_compacts_an_existing_long_reference_chain_without_splitting_it():
    references = [f"{number:064x}:Synthetic Sheet!B9,B10,B11" for number in range(22)]
    contact = directory.DirectoryContact(
        "Manager", "Synthetic Lead", "202-555-0100", "", ";".join(references[:-1]))
    previous = directory.save_directory(
        CONTRACT, (directory.DirectorySite("north", "Synthetic North", contacts=(contact,)),),
        expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    history = directory._path(CONTRACT) / "history" / "00000001.json"
    history_bytes = history.read_bytes()
    incoming = replace(contact, phone="202-555-0101", source=references[-1])
    proposed, = directory.proposed_contacts((contact,), (incoming,))
    state = directory.save_directory(
        CONTRACT, (replace(previous.sites[0], contacts=(proposed,)),),
        expected_revision=1, actor="Synthetic Reviewer", confirmed=True)
    assert directory.load_directory(CONTRACT) == state
    kept = state.sites[0].contacts[0].source.split(";")
    assert len(proposed.source) <= 1000
    assert kept[0] == references[0] and kept[-1] == references[-1]
    assert all(reference in references for reference in kept)
    assert history.read_bytes() == history_bytes
    assert directory.load_directory(CONTRACT, 1) == previous


def test_correcting_from_a_previously_used_source_keeps_that_source_among_newest_references():
    references = [f"{number:064x}:Synthetic Sheet!B9,B10,B11" for number in range(20)]
    saved = directory.DirectoryContact(
        "Manager", "Synthetic Lead", "202-555-0100", "", ";".join(references))
    incoming = replace(saved, phone="202-555-0101", source=references[1])
    contact, = directory.proposed_contacts((saved,), (incoming,))
    kept = contact.source.split(";")
    assert kept[0] == references[0]
    assert kept[-1] == incoming.source
    assert len(contact.source) <= 1000
    assert len(kept) == len(set(kept))


def test_oversized_legacy_reference_cannot_hide_the_new_workbook_reference():
    legacy = "Legacy note; retained as one reference. " * 40
    contact = directory.DirectoryContact(
        "Facility Director", "Synthetic Site Lead", "202-555-0199", "", legacy)
    previous = directory.save_directory(
        CONTRACT, (directory.DirectorySite("north", "Synthetic North", contacts=(contact,)),),
        expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    history = directory._path(CONTRACT) / "history" / "00000001.json"
    history_bytes = history.read_bytes()

    state = _save(_workbook(0, "Synthetic;Provenance Sites"))

    assert state.sites[0].contacts[0].source == (
        f"{state.source_sha256}:Synthetic;Provenance Sites!B9,B10,B11")
    assert history.read_bytes() == history_bytes
    assert directory.load_directory(CONTRACT, 1) == previous
