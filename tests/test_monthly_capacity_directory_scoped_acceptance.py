"""Independent synthetic persistence and output acceptance for #287/#288/#487.

Not a native served/browser assertion. Never touches customer or shared storage.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document
import pytest

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app.monthly_report_capacity_inclusion import capacity_inclusion
from app.monthly_report_docx import assemble_docx, _convert_report_pdf
from app.monthly_report_checks import preflight
from app.monthly_report_model import (
    Facility, OrgChartNode, ReportDraft, ReportPeriod, ReportProfile,
    ResolvedBlock, default_sections,
)
from conftest import requires_libreoffice


@pytest.fixture(autouse=True)
def private_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "synthetic-scoped-acceptance"))


def _site(key, title, person):
    return directory.DirectorySite(key, title, contacts=(
        directory.DirectoryContact("Director", person, "202-555-0100"),
    ))


def _directory(contract, sites):
    return directory.save_directory(
        contract, sites, expected_revision=0,
        actor="Synthetic Reviewer", confirmed=True,
    )


def test_two_editors_reconcile_site_updates_without_cross_contract_name_leak():
    """Real manifest revisions, not in-memory provider mocks."""
    contract = "Synthetic Scope North"
    other_contract = "Synthetic Scope Elsewhere"
    north = _site("north", "Shared Facility", "North Director")
    south = _site("south", "South Campus", "South Director")
    saved = _directory(contract, (north, south))
    other = _directory(other_contract, (_site("east", "Shared Facility", "Elsewhere Director"),))
    first_editor = directory.load_directory(contract)
    second_editor = directory.load_directory(contract)
    assert first_editor == second_editor == saved

    new_north = replace(north, contacts=(
        directory.DirectoryContact("Director", "North Updated", "202-555-0199"),
    ))
    winner = directory.save_directory(contract, (new_north, south),
        expected_revision=first_editor.revision, actor="Synthetic Reviewer", confirmed=True)
    with pytest.raises(library.RevisionConflict):
        directory.save_directory(contract, (north, _site("south", "South Campus", "Stale South")),
            expected_revision=second_editor.revision, actor="Synthetic Reviewer", confirmed=True)

    latest = directory.load_directory(contract)
    assert latest == winner
    recovered_south = _site("south", "South Campus", "South Updated")
    reconciled = directory.save_directory(contract, (latest.sites[0], recovered_south),
        expected_revision=latest.revision, actor="Synthetic Reviewer", confirmed=True)
    assert tuple(site.contacts[0].name for site in reconciled.sites) == (
        "North Updated", "South Updated")
    assert directory.load_directory(contract, 1) == saved
    assert directory.load_directory(other_contract) == other
    assert directory.load_directory(other_contract).sites[0].contacts[0].name == "Elsewhere Director"

    # One malformed sibling must not remove healthy choices or rewrite history.
    damaged_contract = "Synthetic Scope Damaged"
    _directory(damaged_contract, (_site("bad", "Other Facility", "Damaged Director"),))
    path = (library._root() / "directory" /
            library._contract_directory(damaged_contract) / "manifest.json")
    path.write_bytes(b"{")
    unavailable = []
    choices = directory.directory_contracts(unavailable=unavailable)
    assert contract in choices and other_contract in choices
    assert any(problem.storage_key == path.parent.name for problem in unavailable)
    assert directory.load_directory(contract) == reconciled
    assert directory.load_directory(other_contract) == other
    assert path.read_bytes() == b"{"


def _saved_report():
    left_contract = "Synthetic Capacity Contact Left"
    right_contract = "Synthetic Capacity Contact Right"
    left = _directory(left_contract, (_site("left", "Shared Facility", "Left Director"),))
    right = _directory(right_contract, (_site("right", "Shared Facility", "Right Director"),))
    profile = ReportProfile(left_contract, "left-report", "Synthetic Left Report",
                            (Facility("left", "Shared Facility"),))
    other_profile = ReportProfile(right_contract, "right-report", "Synthetic Right Report",
                                  (Facility("right", "Shared Facility"),))
    original = (b"Facility,Service,Required capacity,Available capacity,Units,Notes\n"
                b"Shared Facility,UniqueCapacityMarker,0,NR,lb/hr,Keep measured note\n")
    inspected = capacity.inspect_capacity(profile, "synthetic-capacity.csv", original)
    assert len(inspected.tables) == 1
    assert inspected.tables[0].site_keys == ("left",)
    capacity.save_capacity(profile, inspected.tables, expected_revision=0,
        actor="Synthetic Reviewer", reviewed_fingerprint=capacity.review_fingerprint(inspected.tables))
    assert capacity.capacity_block(other_profile) is None
    source = capacity.capacity_block(profile)
    assert source is not None and source.extra_tables
    assert source.extra_tables[0].rows[0][2:5] == ("0", "NR", "lb/hr")
    omitted = capacity_inclusion(source, False)
    # Construct valid synthetic required blocks: never bypass the export gate.
    required = (
        ResolvedBlock("org_chart", "This month", org_nodes=(
            OrgChartNode("synthetic-lead", "Synthetic Lead", "Asset Manager"),
        )),
        ResolvedBlock("activity_summary", "This month", text="Synthetic monthly activity reviewed."),
        ResolvedBlock("equipment_issues", "This month", text="Synthetic equipment issue review completed."),
        ResolvedBlock("training_summary", "This month", text="Synthetic training summary reviewed."),
    )
    draft = ReportDraft(profile, ReportPeriod(2026, 11), "Synthetic Reviewer",
                        default_sections(), (omitted, *required))
    contacts, missing = directory.contact_block(left, profile.facilities, {"left": "left"})
    assert not missing
    draft = directory.apply_contacts(draft, contacts)
    assert not [check.message for check in preflight(draft) if check.blocking]
    snapshot = library.save_snapshot(draft, expected_revision=0,
                                     entered_editor="Synthetic Reviewer")
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert reopened == snapshot
    assert directory.load_directory(right_contract) == right
    assert capacity.load_capacity(right_contract) is None
    return reopened.draft, source


def _word_text(draft):
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    document = Document(BytesIO(raw))
    return raw, " ".join(document.element.itertext())


def test_omit_then_restore_retains_capacity_formatting_and_contact_scope_in_word():
    saved, source = _saved_report()
    omitted = next(block for block in saved.blocks if block.key == "thermal_capacity")
    assert omitted.source == "Omit"
    assert omitted.references == source.references
    absent_word, absent_text = _word_text(saved)
    assert absent_word and "UniqueCapacityMarker" not in absent_text
    assert "Left Director" in absent_text and "Right Director" not in absent_text

    restored = capacity_inclusion(omitted, True)
    assert restored.extra_tables == source.extra_tables
    assert restored.references == source.references
    reopened = replace(saved, blocks=tuple(restored if b.key == "thermal_capacity" else b
                                          for b in saved.blocks))
    present_word, present_text = _word_text(reopened)
    assert present_word and "UniqueCapacityMarker" in present_text
    assert "Keep measured note" in present_text
    assert "Left Director" in present_text and "Right Director" not in present_text
    assert capacity.load_capacity(saved.profile.contract).revision == 1


@requires_libreoffice
def test_omit_then_restore_is_consistent_in_actual_pdf():
    import pymupdf as fitz

    saved, _ = _saved_report()
    omitted = next(b for b in saved.blocks if b.key == "thermal_capacity")
    for included in (False, True):
        block = capacity_inclusion(omitted, included)
        current = replace(saved, blocks=tuple(block if b.key == "thermal_capacity" else b
                                              for b in saved.blocks))
        word, _ = _word_text(current)
        pdf, error = _convert_report_pdf(current, word)
        assert pdf, error
        with fitz.open(stream=pdf, filetype="pdf") as document:
            printed = " ".join(page.get_text() for page in document)
        assert ("UniqueCapacityMarker" in printed) is included
        assert "Left Director" in printed and "Right Director" not in printed


def test_non_rrh_collision_rejected_without_mutating_saved_directory(monkeypatch):
    """A real saved synthetic directory cannot authorize two colliding slugs."""
    from app import monthly_report_site_catalog as catalog

    contract = "Synthetic Non RRH Site Identity"
    original = _directory(contract, (_site("north", "North Plant/A", "North Director"),))
    monkeypatch.setattr(catalog.contracts, "sites_for_contract",
                        lambda value: ("North Plant/A", "North Plant-A"))
    with pytest.raises(ValueError, match="same report site key"):
        catalog.site_options(contract)
    assert directory.load_directory(contract) == original
    assert directory.load_directory(contract, 1) == original

    # Once the synthetic catalog identities are unambiguous, the saved
    # directory's explicit site key is preserved; nothing has been rewritten.
    monkeypatch.setattr(catalog.contracts, "sites_for_contract",
                        lambda value: ("North Plant/A", "South Plant B"))
    choices = catalog.site_options(contract)
    assert choices[0].key == "north"
    assert choices[-1].key == "south-plant-b"
    assert directory.load_directory(contract) == original
