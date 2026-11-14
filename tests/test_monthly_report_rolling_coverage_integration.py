"""Synthetic cross-module checks for a reviewed twelve-month work-order grid."""
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ReportSource
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_work_order_coverage import CoverageDecision, summarize_coverage
from app.monthly_report_work_order_normalized import normalize_table
from app.monthly_report_work_order_rolling import CoveredMonth, tally_reviewed_months


def test_prior_month_review_and_rolling_metrics_require_separate_coverage():
    period = ReportPeriod(2027, 1)
    profile = ReportProfile("Synthetic contract", "coverage-grid", "Two synthetic sites",
        (Facility("north", "Synthetic North", ("North",)),
         Facility("south", "Synthetic South", ("South",))), scope_type="multi_site")
    sample = json.loads((Path(__file__).parent / "fixtures" /
                         "monthly_rolling_cross_month.json").read_text())
    columns = tuple(sample["columns"])

    def reviewed(closed_date):
        rows = ((sample["work_order"], sample["site"], sample["received_date"],
                 closed_date, sample["status"], sample["type"]),)
        digest = sha256(json.dumps((columns, rows)).encode()).hexdigest()
        source = ReportSource(digest, "synthetic.csv", digest, ".csv")
        content = SourceContent(source, (SourceTable("Work orders", columns, rows),))
        return normalize_table(content, 1, profile, period)

    review = reviewed(sample["closed_date"])
    assert review.rows[0].issues == ("source date is outside this report period",)
    decision = CoverageDecision(profile.contract, profile.key, "north", review.source_sha256,
        review.source_fingerprint, review.table_number, "2026-12", "2027-01",
        "am_confirmed", "Synthetic complete export")
    preview = summarize_coverage(review, (decision,), contract=profile.contract,
        profile_key=profile.key, site="north", months=("2026-12",), as_of=date(2027, 1, 31))
    assert preview[0].covered and preview[0].total == 1

    # Site/month review evidence must not implicitly approve each grid metric.
    kwargs = dict(approved_revisions={review.source_reference: review.revision}, pm_categories=("PM",))
    unknown = tally_reviewed_months((review,), period, profile.facilities, **kwargs)
    assert unknown.cell("north", "pm_received", "2026-12").value is None
    assert unknown.cell("north", "pm_closed", "2027-01").value is None
    approved = (CoveredMonth("north", "pm_received", "2026-12", review.source_reference),
                CoveredMonth("north", "pm_closed", "2027-01", review.source_reference))
    receipts = {(v.site, v.metric, v.month): review.source_reference for v in approved}
    result = tally_reviewed_months((review,), period, profile.facilities,
        covered_months=approved, coverage_approvals=receipts, **kwargs)
    assert result.cell("north", "pm_received", "2026-12").value == "1"
    assert result.cell("north", "pm_closed", "2027-01").value == "1"
    assert not result.review_notices

    invalid = reviewed(sample["invalid_closed_date"])
    assert "completed_date needs review" in invalid.rows[0].issues
    rejected = tally_reviewed_months((invalid,), period, profile.facilities,
        approved_revisions={invalid.source_reference: invalid.revision}, pm_categories=("PM",))
    assert rejected.review_notices


def test_selected_closed_statuses_match_original_source_values():
    period = ReportPeriod(2027, 1)
    profile = ReportProfile("Synthetic contract", "status-choice", "North",
                            (Facility("north", "Synthetic North", ("North",)),))
    columns = ("Work Order #", "Site", "Received Date", "Status", "PM/Non-PM")
    rows = (("WO-1", "North", "2027-01-02", "Closed", "Non-PM"),
            ("WO-2", "North", "2027-01-03", "Complete", "Non-PM"),
            ("WO-3", "North", "2027-01-04", "Finished", "Non-PM"))
    digest = sha256(json.dumps((columns, rows)).encode()).hexdigest()
    source = ReportSource(digest, "synthetic.csv", digest, ".csv")
    review = normalize_table(SourceContent(source, (SourceTable("Export", columns, rows),)),
                             1, profile, period)
    assert {row.status for row in review.rows} == {"Completed"}
    covered = (CoveredMonth("north", "non_pm_closed", "2027-01", review.source_reference),)
    options = dict(approved_revisions={review.source_reference: review.revision}, covered_months=covered,
        coverage_approvals={("north", "non_pm_closed", "2027-01"): review.source_reference})
    def result(**kwargs):
        return tally_reviewed_months((review,), period, profile.facilities, **options, **kwargs).cell(
            "north", "non_pm_closed", "2027-01").value
    assert result() == "2"
    assert result(closed_statuses=("Closed",)) == "1"
    assert result(closed_statuses=("Finished",)) == "1"
    assert result(closed_statuses=()) == "0"
