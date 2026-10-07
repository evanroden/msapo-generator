from dataclasses import replace

import pytest

from app.monthly_report_cmms import CMMSMapping, map_cmms, month_window, parse_date
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_sources import SourceTable


PROFILE = synthetic_profiles()[1]
PERIOD = ReportPeriod(2026, 9)
TABLE = SourceTable("Synthetic", ("ID", "Finished", "Facility", "Type", "Status", "Task"), (
    ("001", "2026-09-02", "Demo North", "Preventive", "Closed", "Inspected DEMO-01"),
    ("002", "2026-09-03", "Demo North", "Corrective", "Closed", "Repaired DEMO-02"),
    ("003", "2026-08-03", "Demo North", "Preventive", "Closed", "Inspected DEMO-03"),
    ("004", "2026-10-03", "Demo South", "Corrective", "Closed", "Repaired DEMO-04"),
    ("005", "2026-09-04", "Demo North", "Corrective", "Open", "Awaiting visit"),
))
MAPPING = CMMSMapping("Finished", "ID", facility="Facility", category="Type", status="Status", description="Task",
                      completed_statuses=("Closed",), pm_values=("Preventive",), cm_values=("Corrective",))


def test_monthly_service_calls_filter_month_and_status_but_keep_evidence():
    result = map_cmms(TABLE, MAPPING, PROFILE, PERIOD, "synthetic-source")
    service, grid = result.blocks
    assert [r[1] for r in service.rows] == ["001", "002"]
    assert all(r[0] == PROFILE.facilities[0].title for r in service.rows)
    assert len(grid.rows) == 24
    assert all(row[2:] == ("", "", "") for row in grid.rows)
    assert any("outside September" in n for n in result.notices)


def test_counts_require_explicit_month_and_facility_coverage():
    mapping = replace(MAPPING, complete_months=("2026-09",), complete_facilities=("north",))
    result = map_cmms(TABLE, mapping, PROFILE, PERIOD, "synthetic-source")
    rows = result.blocks[1].rows
    assert rows[-2][2:] == ("1", "1", "2")
    assert rows[-1][2:] == ("", "", "")  # South was not confirmed.
    assert rows[-4][2:] == ("", "", "")  # August has evidence, no completeness assertion.


def test_zero_only_for_confirmed_complete_history():
    mapping = replace(MAPPING, complete_months=("2026-07",), complete_facilities=("north",))
    result = map_cmms(TABLE, mapping, PROFILE, PERIOD, "synthetic-source")
    july = [r for r in result.blocks[1].rows if r[0] == "2026-07"]
    assert july[0][2:] == ("0", "0", "0")
    assert july[1][2:] == ("", "", "")


def test_duplicate_ids_count_once_and_conflicts_are_excluded():
    mapping = replace(MAPPING, complete_months=(PERIOD.key,), complete_facilities=("north",))
    duplicate = replace(TABLE, rows=TABLE.rows + (TABLE.rows[0],))
    result = map_cmms(duplicate, mapping, PROFILE, PERIOD, "synthetic-source")
    assert result.blocks[1].rows[-2][-1] == "2"
    assert any("counted once" in n for n in result.notices)
    conflict = replace(TABLE, rows=TABLE.rows + (("001", "2026-09-10", "Demo North", "Preventive", "Closed", "Different task"),))
    result = map_cmms(conflict, mapping, PROFILE, PERIOD, "synthetic-source")
    assert [r[1] for r in result.blocks[0].rows] == ["002"]
    assert result.blocks[1].rows[-2][2:] == ("", "", "")
    assert any("conflicting" in n for n in result.notices)


def test_unknown_facility_and_invalid_date_warn_without_creating_members():
    table = replace(TABLE, rows=TABLE.rows + (("006", "bad date", "Demo North", "Preventive", "Closed", "Text"),
                                             ("007", "2026-09-03", "Unknown Demo", "Preventive", "Closed", "Text")))
    result = map_cmms(table, MAPPING, PROFILE, PERIOD, "synthetic-source")
    assert len(result.blocks[0].rows) == 2
    assert any("invalid finish date" in n for n in result.notices)
    assert any("outside this profile" in n for n in result.notices)


def test_missing_facility_requires_explicit_assignment():
    mapping = replace(MAPPING, facility="")
    with pytest.raises(ValueError, match="explicitly assign"):
        map_cmms(TABLE, mapping, PROFILE, PERIOD, "synthetic-source")
    result = map_cmms(TABLE, replace(mapping, assigned_facility="south"), PROFILE, PERIOD, "synthetic-source")
    assert all(row[0] == PROFILE.facilities[1].title for row in result.blocks[0].rows)


def test_dates_are_explicit_and_twelve_months_cross_year():
    assert parse_date("03/09/2026", "DD/MM/YYYY").isoformat() == "2026-09-03"
    assert parse_date("03/09/2026", "MM/DD/YYYY").isoformat() == "2026-03-09"
    assert parse_date("03/09/2026", "ISO") is None
    assert month_window(PERIOD)[0] == "2025-10"
    assert month_window(ReportPeriod(2027, 1))[-1] == "2027-01"


def test_unmapped_category_never_invents_pm_cm_counts():
    mapping = replace(MAPPING, category="", complete_months=(PERIOD.key,), complete_facilities=("north",))
    result = map_cmms(TABLE, mapping, PROFILE, PERIOD, "synthetic-source")
    assert result.blocks[1].rows[-2][2:] == ("", "", "2")


def test_missing_required_columns_or_ambiguous_category_are_rejected():
    for mapping in (replace(MAPPING, finished="Missing"), replace(MAPPING, completed_statuses=()),
                    replace(MAPPING, cm_values=("Preventive",))):
        with pytest.raises(ValueError):
            map_cmms(TABLE, mapping, PROFILE, PERIOD, "synthetic-source")
