"""Known synthetic counts, row membership, review changes and source boundaries."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ReportSource
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_normalized import (
    correct_row, exclude_row, normalize_table, review_record, restore_review,
)

PROFILE = ReportProfile("Invented contract", "counts", "Synthetic only", (
    Facility("north", "North"), Facility("south", "South")), scope_type="multi_site")
PERIOD = ReportPeriod(2026, 9)
COLUMNS = ("WO Number", "Site", "Work Date", "Status", "Type", "Trade", "Completion Date")


def review(rows, columns=COLUMNS):
    data = json.dumps((columns, rows)).encode()
    digest = sha256(data).hexdigest()
    source = ReportSource(digest, "invented-orders.csv", digest, ".csv")
    content = SourceContent(source, (SourceTable("Orders", columns, tuple(rows)),))
    return normalize_table(content, 1, PROFILE, PERIOD)


def counts(value, sites=("north", "south"), trades=True, **kwargs):
    return count_reviewed_work_orders(value, approved_revision=value.revision,
        period=PERIOD, selected_sites=sites, include_trades=trades, **kwargs)


def fixture_review():
    return review((
        ("001", "North", "2026-09-01", "Closed", "PM", "HVAC", "2026-10-01"),
        ("002", "North", "2026-09-02", "Open", "Repair", "Electrical", ""),
        ("003", "South", "2026-09-03", "Closed", "PM", "Plumbing", ""),
        ("004", "South", "2026-09-04", "Open", "", "", ""),
        ("005", "North", "2026-09-05", "Open", "Non-PM", "HVAC / Electrical", ""),
        ("006", "South", "2026-10-01", "Closed", "PM", "HVAC", ""),
        ("007", "South", "", "Open", "PM", "HVAC", ""),
        ("008", "South", "2026-09-08", "Unknown", "PM", "HVAC", ""),
        ("009", "North", "2026-09-09", "Open", "PM", "HVAC", ""),
        ("009", "North", "2026-09-09", "Closed", "PM", "HVAC", ""),
        ("010", "South", "2026-09-10", "Open", "PM and corrective", "HVAC", ""),
    ))


def test_known_cohort_counts_and_each_partition_reconcile_to_exact_row_membership():
    source = fixture_review()
    result = counts(source)
    assert (result.overall.total, result.overall.completed, result.overall.open) == (5, 2, 3)
    assert result.overall.row_keys == tuple(row.key for row in source.rows[:5])
    assert [(g.key, g.total, g.completed, g.open) for g in result.work_types] == [
        ("PM", 2, 2, 0), ("Non-PM", 2, 0, 2), ("unknown", 1, 0, 1)]
    assert [(g.key, g.total) for g in result.sites] == [("north", 3), ("south", 2)]
    assert {g.key: g.total for g in result.trades} == {
        "named:HVAC": 1, "named:Electrical": 1, "named:Plumbing": 1,
        "unknown": 1, "multiple": 1}
    for groups in (result.work_types, result.sites, result.trades):
        memberships = [key for group in groups for key in group.row_keys]
        assert len(memberships) == len(set(memberships)) == 5
        assert set(memberships) == set(result.overall.row_keys)
        assert sum(g.completed for g in groups) == 2
        assert sum(g.open for g in groups) == 3
    assert [d.disposition for d in result.dispositions] == ["counted"] * 5 + ["needs_review"] * 6
    assert any("6 source rows" in notice for notice in result.notices)
    assert any("completion-event" in notice for notice in result.notices)
    assert result.source_reference == source.source_reference


def test_scope_and_optional_trade_changes_never_mutate_source_or_manual_totals():
    source = fixture_review()
    before = review_record(source)
    north, south = counts(source, ("north",)), counts(source, ("south",))
    assert (north.overall.total, south.overall.total) == (3, 2)
    assert north.fingerprint != south.fingerprint
    assert counts(source, ("south", "north")).fingerprint == counts(source).fingerprint
    no_trade = counts(source, trades=False)
    assert not no_trade.trades and no_trade.overall == counts(source).overall
    assert no_trade.fingerprint != counts(source).fingerprint
    assert counts(source, ()).overall.total == 0
    assert counts(source, (), trades=False).fingerprint != counts(source, (), trades=True).fingerprint
    assert review_record(source) == before
    assert any("aggregate totals" in notice for notice in north.notices)


def test_corrections_recompute_counts_require_new_approval_and_survive_serialization():
    source = fixture_review()
    fixed = correct_row(source, source.rows[7].key, {"status": "Open"},
                        expected_revision=source.revision)
    assert counts(fixed).overall.total == 6
    assert counts(fixed).fingerprint != counts(source).fingerprint
    with pytest.raises(ValueError, match="approved.*changed"):
        count_reviewed_work_orders(fixed, approved_revision=source.revision,
            period=PERIOD, selected_sites=("north",))
    roundtrip = restore_review(json.loads(json.dumps(review_record(fixed))))
    assert counts(roundtrip) == counts(fixed)
    assert fixed.original_rows == source.original_rows
    assert fixed.rows[7].origin == source.rows[7].origin


def test_duplicate_ids_are_site_scoped_and_exclusion_does_not_approve_sibling():
    source = review((
        ("A", "North", "2026-09-01", "Open", "PM", "HVAC", ""),
        ("a", "North", "2026-09-01", "Open", "PM", "HVAC", ""),
        ("A", "South", "2026-09-01", "Open", "PM", "HVAC", ""),
    ))
    assert counts(source).overall.total == 1
    omitted = exclude_row(source, source.rows[1].key, expected_revision=source.revision, excluded=True)
    assert counts(omitted).overall.total == 1
    assert [d.disposition for d in counts(omitted).dispositions] == ["needs_review", "excluded", "counted"]
    corrected = correct_row(source, source.rows[1].key, {"work_order": "B"},
                            expected_revision=source.revision)
    assert counts(corrected).overall.total == 3


def test_aggregate_tables_wrong_period_unknown_scope_and_stale_approval_are_rejected():
    aggregate = review((("PM", "100", "110"),), ("Category", "September", "October"))
    with pytest.raises(ValueError, match="Aggregate"):
        counts(aggregate)
    source = fixture_review()
    for sites in (("foreign",), ("north", "north"), "north"):
        with pytest.raises(ValueError, match="unique sites"):
            counts(source, sites)
    with pytest.raises(ValueError, match="period"):
        count_reviewed_work_orders(source, approved_revision=source.revision,
            period=ReportPeriod(2026, 10), selected_sites=("north",))
    with pytest.raises(ValueError, match="trade"):
        counts(source, trades="yes")


def test_unresolved_mapping_blocks_counts_even_after_row_fields_are_corrected():
    source = review((("A", "North", "2026-09-01", "Closed"),),
                    ("WO Number", "Site", "Work Date", "Unmapped state"))
    fixed = correct_row(source, source.rows[0].key, {"status": "Completed"},
                        expected_revision=source.revision)
    assert not fixed.rows[0].issues and fixed.questions
    assert counts(fixed).overall.total == 0
    assert counts(fixed).dispositions[0].disposition == "needs_review"


def test_source_integrity_checked_and_unknown_named_trade_does_not_collide_with_bucket():
    source = review((
        ("A", "North", "2026-09-01", "Open", "", "Unclassified trade", ""),
        ("B", "North", "2026-09-01", "Open", "", "", ""),
    ))
    assert {g.key for g in counts(source).trades} == {"named:Unclassified trade", "unknown"}
    corrupt = replace(source, rows=(replace(source.rows[0], origin=replace(source.rows[0].origin,
        cells=("changed",) + source.rows[0].origin.cells[1:])), source.rows[1]))
    with pytest.raises(ValueError, match="identity"):
        counts(corrupt)
    table = counts(source).summary_table()
    assert table.reference == source.source_reference
    assert table.columns[0] == "Uploaded row sample"
    assert table.rows[0] == ("All reviewed rows in scope", "2", "0", "2")
