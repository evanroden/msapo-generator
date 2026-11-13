"""Independent synthetic reference counts and safe rolling-month rebinds."""
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.monthly_report_model import Facility, ReportPeriod, ReportTable
from app.monthly_report_work_order_rolling import (
    CoveredMonth, METRICS, bind_template_grids, explicit_grid_period,
    merge_carried_grid, rolling_labels, rolling_months, tally_reviewed_months,
)


@dataclass(frozen=True)
class Row:
    key: str
    site: str
    work_order: str
    work_date: str
    completed_date: str
    status: str
    work_type: str
    issues: tuple[str, ...] = ()
    excluded: bool = False


def review(reference, rows, *, completion_column=True, period="2026-12", questions=()):
    return SimpleNamespace(source_reference=reference, revision=reference + ":rev",
        kind="records", questions=questions, rows=rows, period_key=period,
        mapping=SimpleNamespace(completed_date=3 if completion_column else None))


NORTH = Facility("n", "North")
SOUTH = Facility("s", "South")
JANUARY = ReportPeriod(2027, 1)


def count(reviews, *, pm=("PM",), closed=("Closed", "Completed"), coverage=(),
          coverage_approvals=None, facilities=(NORTH, SOUTH)):
    return tally_reviewed_months(reviews, JANUARY, facilities,
        approved_revisions={r.source_reference: r.revision for r in reviews},
        pm_categories=pm, closed_statuses=closed, covered_months=coverage,
        coverage_approvals=coverage_approvals)


def approved_coverage(*items):
    """Make each test's explicit source/month/site/metric attestation visible."""
    coverage = tuple(CoveredMonth(site, metric, month, source)
                     for site, metric, month, source in items)
    approvals = {(site, metric, month): source for site, metric, month, source in items}
    return coverage, approvals


def test_twelve_months_cross_year_and_received_closed_event_dates_are_independent():
    assert rolling_months(JANUARY) == tuple(
        [f"2026-{m:02d}" for m in range(2, 13)] + ["2027-01"])
    rows = (
        Row("r1", "n", "A-1", "2026-12-31", "2027-01-02", "Closed", "PM"),
        Row("r2", "n", "A-2", "2027-01-01", "", "Open", "Non-PM"),
        Row("r3", "s", "A-1", "2026-12-31", "", "Completed", "Non-PM"),
    )
    with_date = review("csv:dates", rows[:2])
    no_date = review("pdf:no-date", rows[2:], completion_column=False)
    coverage, approvals = approved_coverage(
        ("n", "pm_received", "2026-12", "csv:dates"),
        ("n", "pm_closed", "2026-12", "csv:dates"),
        ("n", "pm_closed", "2027-01", "csv:dates"),
        ("s", "non_pm_received", "2026-12", "pdf:no-date"),
        ("s", "non_pm_closed", "2026-12", "pdf:no-date"))
    result = count((with_date, no_date), coverage=coverage, coverage_approvals=approvals)
    assert result.cell("n", "pm_received", "2026-12").value == "1"
    assert result.cell("n", "pm_closed", "2027-01").value == "1"
    assert result.cell("n", "pm_closed", "2026-12").value == "0"
    assert result.cell("n", "pm_closed", "2026-11").value is None
    assert result.cell("s", "non_pm_received", "2026-12").value == "1"
    assert result.cell("s", "non_pm_closed", "2026-12").value == "1"
    assert result.cell("n", "non_pm_received", "2027-01").source_rows == (
        "csv:dates#r2",)
    assert result.cell("s", "non_pm_received", "2026-12").source_rows == (
        "pdf:no-date#r3",)


def test_selected_closure_and_pm_aliases_use_reviewed_normalized_values():
    # Normalized rows express these as Completed and PM; dropdown values may
    # still carry the source's human status/category variant labels.
    source = review("aliases", (Row("r", "n", "WO-9", "2026-12-15", "",
                                  "Completed", "PM"),), completion_column=False)
    coverage, approvals = approved_coverage(
        ("n", "pm_received", "2026-12", "aliases"),
        ("n", "pm_closed", "2026-12", "aliases"))
    counts = count((source,), pm=("Preventive Maintenance",), closed=("Finished",),
                   coverage=coverage, coverage_approvals=approvals)
    assert counts.cell("n", "pm_received", "2026-12").value == "1"
    assert counts.cell("n", "pm_closed", "2026-12").value == "1"


def test_present_but_blank_completion_date_never_falls_back_to_closed_status():
    source = review("has-date", (
        Row("r", "n", "W-1", "2026-12-01", "", "Closed", "PM"),))
    coverage, approvals = approved_coverage(("n", "pm_received", "2026-12", "has-date"))
    result = count((source,), coverage=coverage, coverage_approvals=approvals)
    assert result.cell("n", "pm_received", "2026-12").value == "1"
    assert result.cell("n", "pm_closed", "2026-12").value is None
    complete, approvals = approved_coverage(
        ("n", "pm_received", "2026-12", "has-date"),
        ("n", "pm_closed", "2026-12", "has-date"))
    assert count((source,), coverage=complete, coverage_approvals=approvals).cell(
        "n", "pm_closed", "2026-12").value == "0"


def test_missing_pm_selection_leaves_pm_unknown_including_explicit_coverage():
    source = review("source", (
        Row("r", "n", "W-1", "2026-12-01", "2026-12-02", "Closed", "PM"),))
    attest = CoveredMonth("n", "pm_received", "2026-12", "source")
    result = count((source,), pm=(), coverage=(attest,),
                   coverage_approvals={("n", "pm_received", "2026-12"): "source"})
    assert result.cell("n", "pm_received", "2026-12").value is None
    assert not result.cell("n", "pm_received", "2026-12").covered
    assert any("unselected or unknown" in n for n in result.review_notices)


def test_unknown_month_is_blank_and_covered_zero_is_literal_zero():
    coverage = (CoveredMonth("s", "non_pm_received", "2026-12", "verified:full-export"),)
    result = count((review("verified:full-export", ()),), coverage=coverage,
                   coverage_approvals={("s", "non_pm_received", "2026-12"): "verified:full-export"})
    assert result.cell("s", "non_pm_received", "2026-12").value == "0"
    assert result.cell("s", "non_pm_received", "2026-12").covered
    assert result.cell("s", "non_pm_received", "2026-11").value is None


def test_nonempty_partial_export_does_not_become_a_complete_month_count():
    row = Row("r1", "n", "WO-1", "2026-12-09", "", "Open", "Non-PM")
    source = review("partial", (row,))
    unknown = count((source,)).cell("n", "non_pm_received", "2026-12")
    assert unknown.value is None and not unknown.covered
    assert unknown.source_rows == ("partial#r1",)
    coverage, approvals = approved_coverage(("n", "non_pm_received", "2026-12", "partial"))
    confirmed = count((source,), coverage=coverage, coverage_approvals=approvals).cell(
        "n", "non_pm_received", "2026-12")
    assert confirmed.value == "1" and confirmed.covered
    assert confirmed.source_rows == unknown.source_rows


def test_overlapping_identical_rows_count_once_but_retain_both_sources():
    first = Row("r1", "n", "WO-1", "2026-12-09", "", "Open", "Non-PM")
    second = Row("r2", "n", "wo-1", "2026-12-09", "", "Open", "Non-PM")
    coverage, approvals = approved_coverage(("n", "non_pm_received", "2026-12", "one"))
    result = count((review("one", (first,)), review("two", (second,))),
                   coverage=coverage, coverage_approvals=approvals)
    cell = result.cell("n", "non_pm_received", "2026-12")
    assert cell.value == "1"
    assert cell.source_rows == ("one#r1", "two#r2")


def test_conflicting_sources_exclude_ambiguous_identity_and_keep_other_site():
    coverage, approvals = approved_coverage(("s", "non_pm_received", "2026-12", "second"))
    result = count((
        review("first", (Row("a", "n", "WO-1", "2026-12-09", "", "Open", "Non-PM"),)),
        review("second", (
            Row("b", "n", "wo-1", "2026-12-10", "", "Closed", "Non-PM"),
            Row("c", "s", "WO-1", "2026-12-09", "", "Open", "Non-PM"),
        )),
    ), coverage=coverage, coverage_approvals=approvals)
    assert result.cell("n", "non_pm_received", "2026-12").value is None
    assert result.cell("s", "non_pm_received", "2026-12").value == "1"
    assert any("conflicting updates" in n for n in result.review_notices)
    # A partial known subtotal is not permission to publish misleading grids.
    frames = tuple(SimpleNamespace(reference=f"native-{site}-{metric}",
        columns=(("PM" if metric.startswith("pm_") else "Non-PM") +
                 (" Received" if metric.endswith("received") else " Closed"),
                 *rolling_labels(JANUARY)), slot="work_orders")
        for site in ("n", "s") for metric in METRICS)
    bindings = {frame.reference: tuple(frame.reference.split("-", 2)[1:])
                for frame in frames}
    with pytest.raises(ValueError, match="Resolve unclassified"):
        bind_template_grids(result, JANUARY, frames, bindings, (NORTH, SOUTH))


def test_unapproved_review_or_coverage_without_source_is_rejected():
    source = review("source", ())
    with pytest.raises(ValueError, match="Approve"):
        tally_reviewed_months((source,), JANUARY, (NORTH,),
            approved_revisions={"source": "stale"}, pm_categories=("PM",))
    with pytest.raises(ValueError, match="Coverage"):
        count((), coverage=(CoveredMonth("n", "pm_received", "2026-12", ""),))
    with pytest.raises(ValueError, match="independently approved"):
        count((source,), coverage=(CoveredMonth("n", "pm_received", "2026-12", "source"),))
    with pytest.raises(ValueError, match="independently approved"):
        count((), coverage=(CoveredMonth("n", "pm_received", "2026-12", "other"),),
              coverage_approvals={("n", "pm_received", "2026-12"): "other"})
    # An approval receipt alone is not a reviewed work-order export.  Even an
    # exact revision string must not manufacture a covered zero when the
    # corresponding source review was not included.
    with pytest.raises(ValueError, match="independently approved"):
        tally_reviewed_months(iter(()), JANUARY, (NORTH,),
            approved_revisions={"missing": "missing:rev"}, pm_categories=("PM",),
            covered_months=(CoveredMonth("n", "pm_received", "2026-12", "missing"),),
            coverage_approvals={("n", "pm_received", "2026-12"): "missing"})


def test_coverage_accepts_reviewed_sources_from_a_single_use_iterable():
    source = review("complete", ())
    result = tally_reviewed_months(iter((source,)), JANUARY, (NORTH,),
        approved_revisions={"complete": "complete:rev"}, pm_categories=("PM",),
        covered_months=(CoveredMonth("n", "pm_received", "2026-12", "complete"),),
        coverage_approvals={("n", "pm_received", "2026-12"): "complete"})
    assert result.cell("n", "pm_received", "2026-12").value == "0"


def test_two_site_eight_frame_binding_is_order_explicit_and_overflow_fails_closed():
    result = count((review("complete:n", ()),), coverage=(
        CoveredMonth("n", "pm_received", "2026-12", "complete:n"),),
        coverage_approvals={("n", "pm_received", "2026-12"): "complete:n"})
    frames = tuple(SimpleNamespace(reference=f"native-{site}-{metric}",
        columns=(("PM" if metric.startswith("pm_") else "Non-PM") + (" Received" if metric.endswith("received") else " Closed"), *rolling_labels(JANUARY)), slot="work_orders")
        for site in ("n", "s") for metric in METRICS)
    pairs = {f.reference: tuple(f.reference.split("-", 2)[1:]) for f in frames}
    tables = bind_template_grids(result, JANUARY, frames, pairs, (NORTH, SOUTH))
    assert len(tables) == 8
    assert tables[0].rows[0][0] == "North"
    assert tables[0].rows[0][-2] == "0"
    assert tables[0].rows[0][-1] == ""
    assert tables[4].rows[0][0] == "South"
    with pytest.raises(ValueError, match="exactly once"):
        bind_template_grids(result, JANUARY, frames, {**pairs,
            frames[4].reference: ("n", "pm_received")},
            (NORTH, SOUTH))
    three = (NORTH, SOUTH, Facility("e", "East"))
    third_counts = count((), facilities=three)
    assert len(third_counts.cells) == 3 * 4 * 12
    with pytest.raises(ValueError, match="overflow"):
        bind_template_grids(third_counts, JANUARY, frames, pairs, three)


def test_history_merges_by_real_month_and_preserves_edited_previous_report():
    december = ReportPeriod(2026, 12)
    old = ReportTable(("WO Received", *rolling_labels(december)),
        (("North", *(str(m) if m == 11 else "" for m in range(1, 13))),),
        "master-table:synthetic")
    current = ReportTable(("WO Received", *rolling_labels(JANUARY)), (),
                          old.reference)
    before = old
    assert explicit_grid_period(old.columns) == december
    merged = merge_carried_grid(old, current, december, JANUARY,
                                site_title="North")
    assert old == before
    assert merged.rows[0][0] == "North"
    assert merged.rows[0][10] == "11"  # November 2026, now tenth month in view
    assert merged.rows[0][-1] == ""    # January 2027 remains unknown
    conflicting = ReportTable(current.columns,
        (("North", *("" if i != 9 else "12" for i in range(12))),),
        current.reference)
    with pytest.raises(ValueError, match="conflicting"):
        merge_carried_grid(old, conflicting, december, JANUARY,
                           site_title="North")
    assert merge_carried_grid(old, current, december, JANUARY,
                              site_title="North") == merged


def test_rollover_rejects_a_different_work_order_metric():
    december = ReportPeriod(2026, 12)
    previous = ReportTable(("PM Closed", *rolling_labels(december)),
        (("North", *("7" for _ in range(12))),), "master-table:stable")
    other = ReportTable(("Non-PM Closed", *rolling_labels(JANUARY)), (), previous.reference)
    with pytest.raises(ValueError, match="metric"):
        merge_carried_grid(previous, other, december, JANUARY, site_title="North")
    equivalent = ReportTable(("pm   closed", *rolling_labels(JANUARY)), (), previous.reference)
    assert merge_carried_grid(previous, equivalent, december, JANUARY,
                              site_title="North").rows[0][1] == "7"


def test_undated_or_other_site_carry_is_rejected_not_backfilled():
    december = ReportPeriod(2026, 12)
    correct = ReportTable(("PM Closed", *rolling_labels(december)),
        (("North", *("0" for _ in range(12))),), "master-table:old")
    blank = ReportTable(("PM Closed", *rolling_labels(JANUARY)), (), correct.reference)
    assert explicit_grid_period(("PM Closed", *tuple(
        m.split()[0] for m in rolling_labels(december)))) is None
    with pytest.raises(ValueError, match="different site"):
        merge_carried_grid(correct, blank, december, JANUARY, site_title="South")
    assert merge_carried_grid(correct, blank, december, JANUARY,
                              site_title="North").rows[0][1] == "0"
    with pytest.raises(ValueError, match="later month"):
        merge_carried_grid(correct, blank, december, december, site_title="North")
    undated_edits = ReportTable(correct.columns, (correct.rows[0],), correct.reference)
    with pytest.raises(ValueError, match="current year-month"):
        merge_carried_grid(correct, undated_edits, december, JANUARY,
                           site_title="North")
