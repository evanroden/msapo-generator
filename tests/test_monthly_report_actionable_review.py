"""Period and review messages distinguish source facts, future work and site labels."""
from dataclasses import replace

from app.monthly_report_checks import ReportCheck, preflight, stale_period_mentions
from app.monthly_report_model import Facility, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles, default_sections


def test_explicit_future_follow_up_is_not_mistaken_for_prior_activity():
    assert stale_period_mentions("Completed pump cleaning September 3; follow-up scheduled for October 5.", 2026, 9) == ()
    assert stale_period_mentions("October 5 belt check is scheduled for the future.", 2026, 9) == ()
    assert stale_period_mentions("Follow-up due 2026-10-05.", 2026, 9) == ()
    assert stale_period_mentions("Repair completed October 5.", 2026, 9)
    assert stale_period_mentions("2026-08-15 repair completed.", 2026, 9)


def test_a_date_in_a_facility_name_is_not_a_monthly_activity_claim():
    profile = synthetic_profiles()[0]
    facilities = (replace(profile.facilities[0], title="Synthetic Campus UX Review 2026-10-09"),)
    draft = synthetic_draft(replace(profile, title="Testing built 2026-10-09",
                                   facilities=facilities), ReportPeriod(2026, 9))
    assert not any(check.code == "period" and check.block_key == "cover"
                   for check in preflight(draft))


def test_true_duplicate_warnings_collapse_but_distinct_fields_remain():
    profile = synthetic_profiles()[0]
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    activity = ResolvedBlock("activity_summary", "This month", text="Finished work August 2026.")
    scorecard = ResolvedBlock("utility_analysis", "This month", text="Reviewed June 2026.")
    draft = replace(draft, sections=default_sections(),
                    blocks=(activity, scorecard))
    warnings = [check for check in preflight(draft) if check.code == "period"]
    assert len(warnings) == 2
    assert {w.block_key for w in warnings} == {"activity_summary", "utility_analysis"}
    assert len(warnings) == len(set(warnings))
