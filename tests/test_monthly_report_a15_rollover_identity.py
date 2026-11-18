"""Synthetic scope and persistence regression for monthly standing-data rollover.

Do not promote report-only corrections or substitute a different site's
contacts, chart, capacity, or other standing records while opening a month.
"""
from dataclasses import replace

import pytest

from app import monthly_report_library as library
from app.monthly_report_model import (
    Facility, OrgChartNode, ReportDraft, ReportFollowUp, ReportPeriod,
    ReportProfile, ResolvedBlock, default_sections,
)
from app.monthly_report_setup import WorkOrderRolloverError, new_month_draft


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)


def previous_report():
    north = Facility("north", "Synthetic North", ("North Campus",))
    profile = ReportProfile("Synthetic A15 Contract", "site-north", "North", (north,))
    return ReportDraft(
        profile, SEPTEMBER, "Synthetic Editor", default_sections(),
        (
            ResolvedBlock("org_chart", "This month", org_nodes=(
                OrgChartNode("manager-1", "Synthetic Manager", "Manager"),)),
            ResolvedBlock("contact_matrix", "This month", rows=(
                ("Synthetic North", "Lead", "Identical Name", "555-0101", "north@example.invalid"),)),
            ResolvedBlock("thermal_capacity", "This month", rows=(
                ("North plant", "17 MW", "NR"),)),
            ResolvedBlock("activity_summary", "This month",
                          text="September synthetic technician inspection completed."),
            ResolvedBlock("vendor_reports", "This month", text="September evidence only."),
            ResolvedBlock("equipment_issues", "This month",
                          text="Synthetic pump vibration remains open."),
        ),
        follow_ups=(ReportFollowUp(
            "issue-synthetic-1", "issue", "Synthetic pump vibration remains open.",
            SEPTEMBER.key, status="ongoing"),),
    )


@pytest.mark.parametrize("period", [SEPTEMBER, OCTOBER])
@pytest.mark.parametrize("change", ["site", "contract", "profile_key", "membership"])
def test_rollover_refuses_foreign_report_identity_even_without_work_order_grids(period, change):
    old = previous_report()
    if change == "site":
        target = replace(old.profile, facilities=(Facility("south", "Synthetic South"),))
    elif change == "contract":
        target = replace(old.profile, contract="Other Synthetic Contract")
    elif change == "profile_key":
        target = replace(old.profile, key="different-report")
    else:
        target = replace(old.profile, facilities=(
            *old.profile.facilities, Facility("south", "Synthetic South")),
            scope_type="multi_site")
    baseline = old.fingerprint
    with pytest.raises(WorkOrderRolloverError, match="(site|profile|contract|membership|identity|different)"):
        new_month_draft(old, period, profile=target)
    assert old.fingerprint == baseline


def test_same_site_renames_and_design_pin_are_allowed_without_reclassifying_monthly_work():
    old = previous_report()
    renamed = replace(old.profile, title="Renamed North",
                      facilities=(Facility("north", "Renamed North", ("Original North",)),),
                      template="enfra_master:" + "b" * 64)
    current = new_month_draft(old, OCTOBER, profile=renamed)
    assert current.profile == renamed
    assert current.period == OCTOBER
    assert current.prepared_by == old.prepared_by
    for key in ("org_chart", "contact_matrix", "thermal_capacity"):
        assert next(b for b in current.blocks if b.key == key) == next(
            b for b in old.blocks if b.key == key)
    assert not next(b for b in current.blocks if b.key == "activity_summary").text
    assert not next(b for b in current.blocks if b.key == "vendor_reports").text
    assert current.follow_ups[0].status == "ongoing"
    assert current.follow_ups[0].reviewed_fingerprint == ""


def test_rollover_rejects_backdated_month_instead_of_reasserting_old_work():
    old = previous_report()
    with pytest.raises(WorkOrderRolloverError, match="(earlier|previous|older|backward|chronological)"):
        new_month_draft(old, ReportPeriod(2026, 8))


def test_two_saved_editors_and_storage_failure_keep_history(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "a15"))
    old = previous_report()
    first = library.save_snapshot(old, expected_revision=0, entered_editor=old.prepared_by)
    assert library.load_snapshot(old.profile.contract, old.profile.key, SEPTEMBER).draft == old
    updated = replace(old, blocks=tuple(
        replace(b, text="Report-only correction") if b.key == "activity_summary" else b
        for b in old.blocks))
    second = library.save_snapshot(updated, expected_revision=first.revision,
                                   entered_editor=old.prepared_by)
    with pytest.raises(library.RevisionConflict):
        library.save_snapshot(old, expected_revision=first.revision,
                              entered_editor=old.prepared_by)
    assert library.load_snapshot(old.profile.contract, old.profile.key, SEPTEMBER).draft == updated
    assert library.load_snapshot_version(
        old.profile.contract, old.profile.key, SEPTEMBER, first.revision).draft == old
    manifest = library._profile_path(old.profile.contract, old.profile.key, snapshots=True) / (SEPTEMBER.key + ".json")
    prior_bytes = manifest.read_bytes()
    real_write = library._atomic_write

    def unavailable(path, data):
        if path == manifest:
            raise OSError("Synthetic storage outage")
        return real_write(path, data)

    monkeypatch.setattr(library, "_atomic_write", unavailable)
    with pytest.raises(OSError, match="Synthetic storage outage"):
        library.save_snapshot(old, expected_revision=second.revision,
                              entered_editor=old.prepared_by)
    assert manifest.read_bytes() == prior_bytes
    assert library.load_snapshot(old.profile.contract, old.profile.key, SEPTEMBER).draft == updated
