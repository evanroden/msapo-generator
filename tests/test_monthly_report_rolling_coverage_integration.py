"""Synthetic cross-module checks for a reviewed twelve-month work-order grid."""
from datetime import date
from hashlib import sha256
import json

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
    columns = ("Work Order", "Site", "Received Date", "Closed Date", "Status", "Type")

    def reviewed(closed_date):
        rows = (("WO-120", "North", "2026-12-20", closed_date, "Closed", "PM"),)
        digest = sha256(json.dumps((columns, rows)).encode()).hexdigest()
        source = ReportSource(digest, "synthetic.csv", digest, ".csv")
        content = SourceContent(source, (SourceTable("Work orders", columns, rows),))
        return normalize_table(content, 1, profile, period)

    review = reviewed("2027-01-06")
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

    invalid = reviewed("not a date")
    assert "completed_date needs review" in invalid.rows[0].issues
    rejected = tally_reviewed_months((invalid,), period, profile.facilities,
        approved_revisions={invalid.source_reference: invalid.revision}, pm_categories=("PM",))
    assert rejected.review_notices
