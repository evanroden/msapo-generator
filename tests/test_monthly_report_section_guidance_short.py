"""Short section guidance keeps the real content and pricing gates intact."""

from dataclasses import replace

from app.monthly_report_checks import preflight
from app.monthly_report_model import (
    ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_section_help import section_help


def test_actionable_section_intros_do_not_invent_monthly_work():
    assert section_help("activity").guidance.startswith(
        "Add this month’s work files or write a summary below.")
    scorecards = section_help("scorecards").guidance
    assert "Leave unknown capacity values blank or NR" in scorecards
    assert "only when confirmed" in scorecards

    issues = section_help("issues").guidance
    assert "Update open equipment issues" in issues
    assert "carried-forward" not in issues
    assert "only when deliberately chosen" in issues

    capital = section_help("capital").guidance
    assert "replacement priorities and expected timing" in capital
    assert "Leave unknown dates blank" in capital

    rfi = section_help("rfi").guidance
    assert "RFI means Request for Information" in rfi
    assert "site and status" in rfi
    assert "only when confirmed" in rfi


def test_shorter_capital_guidance_does_not_downgrade_client_pricing_gate():
    profile = synthetic_profiles()[0]
    draft = synthetic_draft(profile, ReportPeriod(2026, 9))
    priced = ResolvedBlock(
        "capital_renewal", "This month",
        rows=(("Demo North", "Priority 1", "Pump replacement $1,200.00"),),
    )
    revised = replace(
        draft,
        blocks=tuple(b for b in draft.blocks if b.key != priced.key) + (priced,),
    )
    assert any(
        check.code == "pricing" and check.blocking
        and check.block_key == "capital_renewal"
        for check in preflight(revised)
    )
