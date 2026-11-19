"""A75: reviewed contract vendor tables retain identities and never leak sites.

All source names, contacts and dates below are invented test fixtures.
"""
from dataclasses import replace

import pytest

from app import monthly_report_library as library
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ReportTable, ResolvedBlock, default_sections,
)
from app.monthly_report_subcontractor_roster import (
    apply_roster, eligible_rosters, load_rosters, save_roster,
)
from test_monthly_report_subcontractor_roster import NATIVE_SPEC, profile, row, rows


def _publish(p, block, revision=0):
    return save_roster(
        p, block, NATIVE_SPEC,
        site_keys=tuple(f.key for f in p.facilities),
        expected_revision=revision, actor="Synthetic reviewer", confirmed=True,
    )


def test_reimport_is_noop_but_changed_source_or_status_creates_version(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = profile("Synthetic Contract A")
    first = ResolvedBlock("subcontractor_matrix", "This month",
                          rows=(row(north.facilities[0].title, "Vendor A", "On call"),),
                          references=("synthetic:report:page-3",))
    initial = _publish(north, first)
    manifest = (library._root() / "subcontractor_rosters" /
                library._contract_directory(north.contract) / "manifest.json")
    original_bytes = manifest.read_bytes()
    original_history = tuple(sorted(p.name for p in (manifest.parent / "history").iterdir()))

    # Baseline/current-main: a second identical promotion created revision 2.
    same = _publish(north, first, revision=1)
    assert same == initial
    assert manifest.read_bytes() == original_bytes
    assert tuple(sorted(p.name for p in (manifest.parent / "history").iterdir())) == original_history

    # Same visible values from another original must retain new source identity.
    new_source = replace(first, references=("synthetic:corrected:page-3",))
    corrected = _publish(north, new_source, revision=1)
    assert corrected.revision == 2
    assert corrected.entries[0].origin_references == ("synthetic:corrected:page-3",)
    assert corrected.entries[0].id != initial.entries[0].id
    assert load_rosters(north.contract) == corrected
    assert manifest.read_bytes() != original_bytes
    assert (manifest.parent / "history" / "00000001.json").exists()

    # A stale no-op is not allowed to evade optimistic-concurrency protection.
    with pytest.raises(library.RevisionConflict):
        _publish(north, first, revision=1)

    changed_status = replace(first, rows=(row(north.facilities[0].title,
                                               "Vendor A", "Awaiting confirmation"),))
    newer = _publish(north, changed_status, revision=2)
    assert newer.revision == 3
    assert newer.entries[0].tables[0].rows[0][-1] == "Awaiting confirmation"
    assert initial.entries[0].tables[0].rows[0][-1] == "On call"


def test_site_only_heading_is_not_a_global_category_band(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    both = profile("Synthetic Contract A", "both", ("north", "south"))
    north = profile("Synthetic Contract A")
    south = profile("Synthetic Contract A", "south", ("south",))
    foreign = profile("Synthetic Contract B")

    unknown = rows(("Unknown location", "", "", "", "", ""))
    # Baseline/current-main: the single populated site cell bypassed validation.
    with pytest.raises(ValueError, match="unconfirmed site"):
        _publish(north, unknown)
    assert load_rosters(north.contract).revision == 0

    table = rows(
        (both.facilities[0].title, "", "", "", "", ""),
        row(both.facilities[0].title, "Synthetic North Vendor"),
        (both.facilities[1].title, "", "", "", "", ""),
        row(both.facilities[1].title, "Synthetic South Vendor"),
    )
    state = _publish(both, table)
    a = apply_roster(state, state.entries[0], north,
                     ResolvedBlock("subcontractor_matrix", "Omit"), NATIVE_SPEC)
    b = apply_roster(state, state.entries[0], south,
                     ResolvedBlock("subcontractor_matrix", "Omit"), NATIVE_SPEC)
    assert [x[2] for x in a.rows if x[2]] == ["Synthetic North Vendor"]
    assert [x[2] for x in b.rows if x[2]] == ["Synthetic South Vendor"]
    assert all("South" not in str(x) for x in a.rows)
    assert all("North" not in str(x) for x in b.rows)
    assert not eligible_rosters(state, foreign)


def test_nested_people_dates_roles_and_category_bands_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    both = profile("Synthetic Contract A", "both", ("north", "south"))
    north = profile("Synthetic Contract A")
    columns = ("Category", "Facility", "Vendor", "Person", "Role",
               "Status / when to contact", "Status date")
    original = ReportTable(columns, (
        ("Mechanical", "", "", "", "", "", ""),
        ("", both.facilities[0].title, "Synthetic HVAC", "North Technician",
         "Service technician", "Awaiting approval", "2026-09-02"),
        ("", both.facilities[0].title, "Synthetic HVAC", "North Dispatcher",
         "Dispatch", "Call during business hours", ""),
        ("", both.facilities[1].title, "Synthetic HVAC", "South Technician",
         "Service technician", "Not confirmed", "2026-08-27"),
        ("Water", "", "", "", "", "", ""),
    ), "synthetic:source-table:12")
    block = ResolvedBlock("subcontractor_matrix", "This month",
                          extra_tables=(original,),
                          references=("synthetic:original:page-12",))
    state = _publish(both, block)
    assert state.entries[0].origin_references == (
        "synthetic:original:page-12", "synthetic:source-table:12")
    assert state.entries[0].tables[0].rows == original.rows
    first = apply_roster(state, state.entries[0], north,
                         ResolvedBlock("subcontractor_matrix", "Omit"), NATIVE_SPEC)
    assert first.rows == ()
    assert len(first.extra_tables) == 1
    assert [r[3] for r in first.extra_tables[0].rows if r[3]] == [
        "North Technician", "North Dispatcher"]
    assert all("South Technician" not in str(r) for r in first.extra_tables[0].rows)
    assert first.extra_tables[0].rows[1][-1] == "2026-09-02"
    assert first.extra_tables[0].rows[2][-1] == ""  # no invented confirmation date
    assert first.extra_tables[0].rows[2][4] == "Dispatch"

    second = apply_roster(state, state.entries[0], north, first,
                          NATIVE_SPEC, replace_existing=True)
    assert second == first  # retry/reimport creates no duplicate output rows

    draft = ReportDraft(north, ReportPeriod(2026, 9), "Synthetic Reviewer",
                        default_sections(), (first,))
    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor="Synthetic Reviewer")
    assert saved.draft.blocks[0] == first
    reopened = library.load_snapshot(north.contract, north.key, ReportPeriod(2026, 9))
    assert reopened.draft.blocks[0] == first
    report_only = replace(first, extra_tables=(
        replace(first.extra_tables[0],
                rows=tuple((*r[:-2], "Report-only override", r[-1])
                           if r[3] == "North Technician" else r
                           for r in first.extra_tables[0].rows)),))
    assert report_only != first
    edited_draft = replace(draft, blocks=(report_only,))
    revised = library.save_snapshot(edited_draft, expected_revision=saved.revision,
                                    entered_editor="Synthetic Reviewer")
    assert revised.draft.blocks[0] == report_only
    assert library.load_snapshot(north.contract, north.key,
                                 ReportPeriod(2026, 9)).draft.blocks[0] == report_only
    assert library.load_snapshot_version(north.contract, north.key,
                                         ReportPeriod(2026, 9), saved.revision).draft.blocks[0] == first
    assert load_rosters(north.contract) == state  # report correction never writes master
    assert reopened.draft.blocks[0] == first


def test_identical_person_rows_require_review_without_dropping_category_bands(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = profile("Synthetic Contract A")
    contact = row(north.facilities[0].title, "Synthetic Vendor")
    double = rows(contact, contact)
    with pytest.raises(ValueError, match="Duplicate subcontractor contact"):
        _publish(north, double)
    assert load_rosters(north.contract).revision == 0

    # Repeating a source's literal category heading is not a second person.
    band = ReportTable(("Trade", "Facility", "Vendor"),
                       (("Electrical", "", ""), ("Electrical", "", ""),
                        ("", north.facilities[0].title, "Synthetic Vendor")))
    state = _publish(north, ResolvedBlock(
        "subcontractor_matrix", "This month", extra_tables=(band,)))
    assert len(state.entries[0].tables[0].rows) == 3


def test_native_save_button_reports_noop_without_a_second_revision(monkeypatch, tmp_path):
    from test_monthly_report_subcontractor_roster_ui import launch, check, button

    north = profile("Synthetic Contract A")
    block = rows(row(north.facilities[0].title, "Synthetic Vendor"))
    app = launch(monkeypatch, tmp_path, north, block)
    check(app, "I reviewed these vendor contacts").check().run()
    button(app, "Save shared subcontractors").click().run()
    assert not app.exception
    assert load_rosters(north.contract).revision == 1

    app.run()
    check(app, "I reviewed these vendor contacts").check().run()
    button(app, "Save shared subcontractors").click().run()
    assert not app.exception
    assert load_rosters(north.contract).revision == 1
    assert any("already matches the saved contract version" in info.value
               for info in app.info)
