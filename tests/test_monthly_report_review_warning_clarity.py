"""Content review should distinguish dates in client identity and future work."""
from dataclasses import replace

from app.monthly_report_checks import preflight, stale_period_mentions
from app.monthly_report_model import ResolvedBlock, ReportPeriod, default_sections, synthetic_draft, synthetic_profiles


def test_explicit_next_month_follow_up_is_not_completed_previous_month_work():
    text = ("Replaced pump seals September 20, 2026. "
            "October 5 belt check is scheduled as a future follow-up.")
    assert not stale_period_mentions(text, 2026, 9)
    assert not stale_period_mentions("2026-10-05 future belt check planned", 2026, 9)
    assert not stale_period_mentions("10/05/2026 follow-up scheduled for site inspection", 2026, 9)


def test_wrong_month_completed_activity_still_gets_review_warning():
    assert stale_period_mentions("October 5, 2026 replacement was completed.", 2026, 9)
    assert stale_period_mentions("2026-10-05 motor replacement performed.", 2026, 9)
    assert stale_period_mentions("June 2026 follow-up was previously recorded.", 2026, 9)
    assert stale_period_mentions("September 2025 pump inspection completed.", 2026, 9)


def test_test_site_dates_are_identifiers_not_accepted_work_period():
    profile = replace(synthetic_profiles()[0], title="Synthetic October 9 QA Facility",
                      facilities=(replace(synthetic_profiles()[0].facilities[0],
                                          title="October 9 Review Campus"),),
                      contract="Synthetic October 9 Group")
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    draft = replace(draft, sections=default_sections(),
                    blocks=(ResolvedBlock("activity_summary", "This month",
                                           text="Inspected pump on September 3, 2026."),))
    checks = preflight(draft)
    assert not any(c.code == "period" and c.block_key == "report_identity" for c in checks)
    assert not any(c.code == "period" and "October 9" in c.message for c in checks)


def test_duplicate_review_items_are_only_shown_once():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    draft = replace(draft, sections=default_sections(),
                    blocks=(ResolvedBlock("activity_summary", "This month",
                                           text="August 2026 maintenance completed."),))
    checks = preflight(draft)
    assert len(checks) == len(set(checks))
    assert any(c.code == "period" and "August" in c.message for c in checks)
