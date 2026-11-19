"""A93: synthetic source-row parity, duplicate dates and grid/list exclusivity.

No real client documents or mutable production state are used.
"""
from dataclasses import asdict, replace
from datetime import date
from hashlib import sha256
import json

import pytest

from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportSource,
    ResolvedBlock, ReportTable, default_sections,
)
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_work_order_counts import count_reviewed_work_orders
from app.monthly_report_work_order_coverage import CoverageDecision, summarize_coverage
from app.monthly_report_work_order_normalized import (
    correct_row, exclude_row, normalize_table, restore_review, review_record,
)
from app.monthly_report_work_order_rolling import (
    CoveredMonth, rolling_labels, tally_reviewed_months,
)
from app import monthly_report_work_order_review_flow as flow
from app import monthly_report_rolling_workflow as grid

PROFILE = ReportProfile("Synthetic contract A93", "a93", "Synthetic only", (
    Facility("north", "North"), Facility("south", "South")), scope_type="multi_site")
SEPT = ReportPeriod(2026, 9)
OCT = ReportPeriod(2026, 10)
COLS = ("WO Number", "Site", "Work Date", "Status", "Type", "Trade", "Completion Date")


def source(rows):
    raw = json.dumps((COLS, rows)).encode()
    digest = sha256(raw).hexdigest()
    origin = ReportSource(digest, "synthetic-a93.csv", digest, ".csv")
    content = SourceContent(origin, (SourceTable("Orders", COLS, tuple(rows)),))
    return content, normalize_table(content, 1, PROFILE, SEPT)


def tally(review, *, period=SEPT, sites=("north", "south"), trades=True):
    return count_reviewed_work_orders(review, approved_revision=review.revision,
        period=period, selected_sites=sites, include_trades=trades)


def attestation(review, site, start="2026-09", end="2026-10"):
    return CoverageDecision(PROFILE.contract, PROFILE.key, site,
        review.source_sha256, review.source_fingerprint, review.table_number,
        start, end, "am_confirmed", "Synthetic full export approval")


def test_known_published_table_totals_partition_by_site_date_status_category_and_trade():
    rows = (
        ("A-1", "North", "2026-09-01", "Closed", "PM", "HVAC", ""),
        ("B-2", "North", "2026-09-02", "Open", "Repair", "Electrical", ""),
        ("A-1", "South", "2026-09-03", "Open", "PM", "HVAC", ""),
        ("a-1", "North", "2026-09-05", "Closed", "PM", "Plumbing", ""),
        ("Dup", "North", "2026-09-06", "Open", "PM", "HVAC", ""),
        ("dup", "North", "2026-09-06", "Open", "PM", "HVAC", ""),
        ("C-3", "South", "2026-09-06", "Closed", "Repair", "Plumbing", ""),
        ("OCT", "North", "2026-10-01", "Open", "PM", "HVAC", ""),
        ("BAD", "South", "2026-09-07", "Unknown", "PM", "HVAC", ""),
        ("U-4", "South", "2026-09-08", "Open", "", "", ""),
        ("MIX", "North", "2026-09-09", "Open", "PM and corrective", "HVAC", ""),
    )
    _, reviewed = source(rows)
    original = review_record(reviewed)
    result = tally(reviewed)
    assert (result.overall.total, result.overall.completed, result.overall.open) == (6, 3, 3)
    assert [(g.key, g.total, g.completed, g.open) for g in result.work_types] == [
        ("PM", 3, 2, 1), ("Non-PM", 2, 1, 1), ("unknown", 1, 0, 1)]
    assert [(g.key, g.total) for g in result.sites] == [("north", 3), ("south", 3)]
    assert {g.key: g.total for g in result.trades} == {
        "named:HVAC": 2, "named:Electrical": 1, "named:Plumbing": 2, "unknown": 1}
    for groups in (result.work_types, result.sites, result.trades):
        receipts = [key for g in groups for key in g.row_keys]
        assert len(receipts) == len(set(receipts)) == result.overall.total
        assert set(receipts) == set(result.overall.row_keys)
        assert sum(g.completed for g in groups) == result.overall.completed
        assert sum(g.open for g in groups) == result.overall.open
    assert [d.disposition for d in result.dispositions] == [
        "counted", "counted", "counted", "counted", "needs_review", "needs_review",
        "counted", "needs_review", "needs_review", "counted", "needs_review"]
    assert result.summary_table().rows[0] == ("All reviewed rows in scope", "6", "3", "3")
    assert len(result.overall.row_keys) == 6
    assert review_record(reviewed) == original
    assert tally(restore_review(json.loads(json.dumps(original)))) == result


def test_same_real_order_case_variants_require_review_but_other_dates_and_sites_do_not():
    _, reviewed = source((
        ("W-5", "North", "2026-09-01", "Open", "PM", "HVAC", ""),
        ("w-5", "North", "2026-09-01", "Closed", "PM", "HVAC", ""),
        ("w-5", "North", "2026-09-02", "Open", "PM", "HVAC", ""),
        ("W-5", "South", "2026-09-01", "Open", "PM", "HVAC", ""),
    ))
    result = tally(reviewed)
    assert result.overall.total == 2
    assert [d.disposition for d in result.dispositions] == [
        "needs_review", "needs_review", "counted", "counted"]
    ignored = exclude_row(reviewed, reviewed.rows[1].key,
                          expected_revision=reviewed.revision, excluded=True)
    assert tally(ignored).overall.total == 2  # Exclusion alone never picks a winning duplicate.
    fixed = correct_row(reviewed, reviewed.rows[1].key, {"work_order": "W-6"},
                        expected_revision=reviewed.revision)
    assert tally(fixed).overall.total == 4
    with pytest.raises(ValueError, match="changed"):
        count_reviewed_work_orders(fixed, approved_revision=reviewed.revision,
            period=SEPT, selected_sites=("north",))
    assert fixed.original_rows == reviewed.original_rows
    assert fixed.rows[1].origin == reviewed.rows[1].origin


def test_annual_coverage_reuses_exact_rows_without_recounting_other_periods_or_sites():
    _, reviewed = source((
        ("R-1", "North", "2026-09-01", "Closed", "PM", "HVAC", ""),
        ("r-1", "North", "2026-09-05", "Open", "Repair", "Electrical", ""),
        ("R-1", "South", "2026-09-01", "Open", "PM", "HVAC", ""),
        ("R-1", "North", "2026-10-07", "Open", "PM", "HVAC", ""),
    ))
    assert tally(reviewed).overall.total == 3
    north = summarize_coverage(reviewed, (attestation(reviewed, "north"),),
        contract=PROFILE.contract, profile_key=PROFILE.key, site="north",
        months=("2026-09", "2026-10"), as_of=date(2026, 11, 17))
    south = summarize_coverage(reviewed, (attestation(reviewed, "south"),),
        contract=PROFILE.contract, profile_key=PROFILE.key, site="south",
        months=("2026-09",), as_of=date(2026, 11, 17))
    assert [(m.total, m.completed, m.open, m.pm, m.non_pm) for m in north] == [
        (2, 1, 1, 1, 1), (1, 0, 1, 1, 0)]
    assert [(m.total, m.completed, m.open) for m in south] == [(1, 0, 1)]
    covered = tuple(CoveredMonth(site, metric, month, reviewed.source_reference)
        for site, metric, month in (
            ("north", "pm_received", "2026-09"),
            ("north", "non_pm_received", "2026-09"),
            ("north", "pm_received", "2026-10"),
            ("south", "pm_received", "2026-09")))
    counted = tally_reviewed_months((reviewed,), OCT, PROFILE.facilities,
        approved_revisions={reviewed.source_reference: reviewed.revision},
        pm_categories=("PM",), covered_months=covered,
        coverage_approvals={(c.site, c.metric, c.month): c.source_reference for c in covered})
    assert counted.cell("north", "pm_received", "2026-09").value == "1"
    assert counted.cell("north", "non_pm_received", "2026-09").value == "1"
    assert counted.cell("north", "pm_received", "2026-10").value == "1"
    assert counted.cell("south", "pm_received", "2026-09").value == "1"
    assert len(set(counted.cell("north", "pm_received", "2026-09").source_rows)) == 1


def test_coverage_unknown_for_same_day_duplicates_even_without_cached_normalizer_warning():
    _, reviewed = source((
        ("ABC", "North", "2026-09-01", "Open", "PM", "", ""),
        ("abc", "North", "2026-09-01", "Open", "PM", "", ""),
    ))
    without_issues = replace(reviewed, rows=tuple(replace(row, issues=()) for row in reviewed.rows))
    result, = summarize_coverage(without_issues, (attestation(reviewed, "north"),),
        contract=PROFILE.contract, profile_key=PROFILE.key, site="north",
        months=("2026-09",), as_of=date(2026, 11, 17))
    assert result.covered and result.total is None
    assert len(result.issues) == 2 and all("duplicate" in notice for notice in result.issues)


def test_unknown_and_wrong_month_inputs_remain_outside_published_totals():
    _, reviewed = source((
        ("A", "North", "", "Open", "PM", "", ""),
        ("B", "South", "2026-09-02", "unclear", "PM", "", ""),
        ("C", "North", "2026-10-01", "Open", "PM", "", ""),
    ))
    result = tally(reviewed)
    assert result.overall.total == 0
    assert all(d.disposition == "needs_review" for d in result.dispositions)
    with pytest.raises(ValueError, match="period"):
        tally(reviewed, period=OCT)
    with pytest.raises(ValueError, match="unique sites"):
        tally(reviewed, sites=("north", "north"))


def test_a_list_and_annual_grid_cannot_both_publish_totals_for_same_source():
    content, _ = source((("A", "North", "2026-09-01", "Open", "PM", "HVAC", ""),))
    draft = ReportDraft(PROFILE, SEPT, "Synthetic preparer", default_sections(),
        (ResolvedBlock("work_orders", "This month"),), synthetic=True,
        sources=(content.source,))
    bundle = flow.prepare_bundle(draft, content)
    tables = flow.reviewed_tables(draft, bundle)
    assert len(tables) == 2
    published = flow.decoded(flow.encoded({**bundle,
        "published": [asdict(table) for table in tables]}))
    with pytest.raises(ValueError, match="published work-order list"):
        grid.publish(draft, published, expected_revision=flow.revision(published),
            expected_block=draft.blocks[0].fingerprint, group_index=0,
            metrics=("pm_received",), confirmed=True, as_of=date(2026, 11, 17))
    labels = rolling_labels(SEPT)
    frames = [ReportTable(("PM Received", *labels), (), "master-table:" + str(i)) for i in range(4)]
    receipt = {"schema": 1, "group_index": 0, "review_revision": "review",
        "coverage_revision": "coverage", "metrics": ["pm_received"],
        "closed_statuses": ["Closed"], "base_tables": [asdict(f) for f in frames],
        "published_tables": [asdict(f) for f in frames]}
    grid_bound = flow.decoded(flow.encoded({**bundle, "grid_receipt": receipt}))
    with pytest.raises(ValueError, match="annual work-order grid"):
        flow.reviewed_tables(draft, grid_bound)


def test_another_exports_grid_cannot_be_recounted_in_list_and_distinct_dates_remain_valid():
    original_content, _ = source((("REF-1", "North", "2026-09-01", "Open", "PM", "", ""),))
    same_content, _ = source((
        ("ref-1", "North", "2026-09-01", "Open", "PM", "", ""),
        ("OTHER", "South", "2026-09-02", "Open", "Repair", "", ""),
    ))
    different_content, _ = source((("ref-1", "North", "2026-09-02", "Open", "PM", "", ""),))
    labels = rolling_labels(SEPT)
    frames = tuple(ReportTable(("PM Received", *labels), (), "master-table:" + str(i)) for i in range(4))
    draft = ReportDraft(PROFILE, SEPT, "Synthetic preparer", default_sections(),
        (ResolvedBlock("work_orders", "This month", extra_tables=frames),),
        synthetic=True, sources=(original_content.source, same_content.source,
                                 different_content.source))
    original = flow.prepare_bundle(draft, original_content)
    receipt = {"schema": 1, "group_index": 0, "review_revision": "approved",
        "coverage_revision": "approved", "metrics": ["pm_received"],
        "closed_statuses": ["Closed"], "base_tables": [asdict(t) for t in frames],
        "published_tables": [asdict(t) for t in frames]}
    grid_bound = flow.decoded(flow.encoded({**original, "grid_receipt": receipt}))
    draft = flow.store_bundle(draft, grid_bound)
    other = flow.prepare_bundle(draft, same_content)
    draft = flow.store_bundle(draft, other)
    with pytest.raises(ValueError, match="annual grids"):
        flow.publish_bundle(draft, other, expected_revision=flow.revision(other),
            expected_block=draft.blocks[0].fingerprint)
    clean = flow.prepare_bundle(draft, different_content)
    draft = flow.store_bundle(draft, clean)
    published = flow.publish_bundle(draft, clean, expected_revision=flow.revision(clean),
        expected_block=draft.blocks[0].fingerprint)
    assert published.blocks[0].extra_tables[:4] == frames
    assert published.blocks[0].extra_tables[-1].rows[0][1] == "1"


def test_other_exports_published_list_cannot_be_recounted_in_annual_grid(monkeypatch):
    first_content, _ = source((("REF-9", "North", "2026-09-01", "Open", "PM", "", ""),))
    second_content, _ = source((
        ("ref-9", "North", "2026-09-01", "Open", "PM", "", ""),
        ("SECOND", "South", "2026-09-02", "Open", "Repair", "", ""),
    ))
    draft = ReportDraft(PROFILE, SEPT, "Synthetic preparer", default_sections(),
        (ResolvedBlock("work_orders", "This month"),), synthetic=True,
        sources=(first_content.source, second_content.source))
    first = flow.prepare_bundle(draft, first_content)
    draft = flow.store_bundle(draft, first)
    draft = flow.publish_bundle(draft, first, expected_revision=flow.revision(first),
        expected_block=draft.blocks[0].fingerprint)
    frames = tuple(ReportTable(("PM Received", *rolling_labels(SEPT)), (),
        "master-table:" + str(i)) for i in range(4))
    block = replace(draft.blocks[0],
        extra_tables=(*draft.blocks[0].extra_tables, *frames))
    draft = replace(draft, blocks=(block,))
    other = flow.prepare_bundle(draft, second_content)
    draft = flow.store_bundle(draft, other)
    monkeypatch.setattr(grid, "_frames", lambda _: (frames, {}))
    with pytest.raises(ValueError, match="detailed list"):
        grid.publish(draft, other, expected_revision=flow.revision(other),
            expected_block=block.fingerprint, group_index=0,
            metrics=("pm_received",), confirmed=True, as_of=date(2026, 11, 17))


def test_trade_case_variants_reconcile_without_changing_source_values():
    _, reviewed = source((
        ("T-1", "North", "2026-09-01", "Open", "PM", "HVAC", ""),
        ("T-2", "North", "2026-09-02", "Closed", "PM", "hvac", ""),
        ("T-3", "South", "2026-09-03", "Open", "Repair", "HVAC  ", ""),
    ))
    original = review_record(reviewed)
    result = tally(reviewed)
    assert len(result.trades) == 1
    trade, = result.trades
    assert (trade.key, trade.label, trade.total, trade.completed, trade.open) == (
        "named:HVAC", "HVAC", 3, 1, 2)
    assert review_record(reviewed) == original
