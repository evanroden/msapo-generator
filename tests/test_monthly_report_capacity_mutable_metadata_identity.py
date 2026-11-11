"""Stable capacity identity excludes mutable notes, dates, status and title.

Saved synthetic CSVs exercise real shared manifest and original-byte paths.
"""
import pytest

from app import monthly_report_capacity as capacity
from app import monthly_report_directory as directory
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportProfile


HEADER = (b"Facility,System,Service,Required capacity,Available capacity,"
          b"Units,Notes,Status,Inspection date,Title\n")
BASE = (HEADER
        + b"North Facility,Plant A,Steam,100,200,lb/hr,First note,Open,2026-10-01,Old title\n"
        + b"North Facility,Plant B,Steam,50,60,lb/hr,Plant B note,Open,2026-10-01,Plant B\n"
        + b"South Facility,Plant A,Steam,70,80,lb/hr,South note,Open,2026-10-01,South title\n")
CORRECTION = (HEADER
              + b"North Facility,Plant A,Steam,110,210,lb/hr,Corrected note,Closed,2026-11-01,New title\n")


@pytest.fixture
def profile(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "scope"))
    contract = "Synthetic Metadata Stable Capacity"
    directory.save_directory(
        contract, (
            directory.DirectorySite("north", "North Facility"),
            directory.DirectorySite("south", "South Facility"),
        ), expected_revision=0, actor="Synthetic Reviewer", confirmed=True,
    )
    return ReportProfile(contract, "north-report", "North report",
                         (Facility("north", "North Facility"),))


def inspect(profile, raw, name):
    result = capacity.inspect_capacity(profile, name, raw)
    assert len(result.tables) == 1
    assert sources.source_bytes(profile, result.content.source) == raw
    return result


def save(profile, result, revision):
    return capacity.save_capacity(
        profile, result.tables, expected_revision=revision,
        actor="Synthetic Reviewer",
        reviewed_fingerprint=capacity.review_fingerprint(result.tables),
    )


def _site_rows(state, site):
    return tuple(row for table in state.tables
                 for row, key in zip(table.rows, table.site_keys) if key == site)


def test_notes_status_date_title_correction_replaces_only_same_physical_row(profile):
    old = inspect(profile, BASE, "baseline.csv")
    first = save(profile, old, 0)
    corrected = inspect(profile, CORRECTION, "corrected.csv")
    original_row = old.tables[0].rows[0]
    updated_row = corrected.tables[0].rows[0]

    # Optional descriptions can change without creating another plant.
    assert capacity._row_key(old.tables[0], original_row, "north") == (
        capacity._row_key(corrected.tables[0], updated_row, "north"))
    assert capacity.first_fill_tables(first, corrected.tables) == ()

    latest = save(profile, corrected, 1)
    assert latest.revision == 2
    assert sorted(_site_rows(latest, "north")) == sorted((updated_row, old.tables[0].rows[1]))
    assert _site_rows(latest, "south") == (old.tables[0].rows[2],)
    assert sum(len(table.rows) for table in latest.tables) == 3
    assert capacity.load_capacity(profile.contract) == latest
    assert capacity.load_capacity(profile.contract, 1) == first
    with pytest.raises(library.RevisionConflict):
        save(profile, corrected, 1)
    assert sources.source_bytes(profile, old.content.source) == BASE
    assert sources.source_bytes(profile, corrected.content.source) == CORRECTION


def test_metadata_differences_do_not_disguise_duplicate_measurements(profile):
    raw = (HEADER
           + b"North Facility,Plant A,Steam,100,200,lb/hr,First,Open,2026-10-01,Title one\n"
           + b"North Facility,Plant A,Steam,100,200,lb/hr,Second,Closed,2026-11-01,Title two\n")
    candidate = inspect(profile, raw, "duplicates.csv")
    assert capacity.duplicate_capacity_rows(candidate.tables) == (
        ((1, 1), (1, 2), "north"),)
    with pytest.raises(ValueError, match="same site and labels"):
        save(profile, candidate, 0)
    assert capacity.load_capacity(profile.contract) is None


def test_physical_system_and_unit_still_distinguish_valid_measurements(profile):
    raw = (HEADER
           + b"North Facility,Plant A,Steam,100,200,lb/hr,First,Open,2026-10-01,Title one\n"
           + b"North Facility,Plant B,Steam,100,200,lb/hr,First,Open,2026-10-01,Title one\n"
           + b"North Facility,Plant A,Steam,100,200,kg/hr,First,Open,2026-10-01,Title one\n")
    candidate = inspect(profile, raw, "distinct.csv")
    assert capacity.duplicate_capacity_rows(candidate.tables) == ()
    result = save(profile, candidate, 0)
    assert len(_site_rows(result, "north")) == 3


def test_title_only_without_a_system_identity_remains_distinct(profile):
    """Do not collapse two facilities' units based only on equal readings."""
    raw = (b"Facility,Required capacity,Available capacity,Units,Title\n"
           b"North Facility,100,200,lb/hr,Boiler 1\n"
           b"North Facility,100,200,lb/hr,Boiler 2\n")
    candidate = inspect(profile, raw, "title-only.csv")
    assert capacity.duplicate_capacity_rows(candidate.tables) == ()
    saved = save(profile, candidate, 0)
    assert len(_site_rows(saved, "north")) == 2
    assert {row[-1] for row in _site_rows(saved, "north")} == {
        "Boiler 1", "Boiler 2"}


def test_blank_service_does_not_erase_the_only_equipment_title(profile):
    """A physical header without data cannot establish distinct identity."""
    raw = (b"Facility,Service,Required capacity,Available capacity,Units,Title\n"
           b"North Facility,,100,200,lb/hr,Boiler 1\n"
           b"North Facility,,100,200,lb/hr,Boiler 2\n")
    candidate = inspect(profile, raw, "blank-service.csv")
    assert capacity.duplicate_capacity_rows(candidate.tables) == ()
    saved = save(profile, candidate, 0)
    assert len(_site_rows(saved, "north")) == 2
    assert {row[-1] for row in _site_rows(saved, "north")} == {
        "Boiler 1", "Boiler 2"}
