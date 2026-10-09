from dataclasses import replace

import pytest

from app.monthly_report_followups import confirmation, problems
from app.monthly_report_model import (
    ReportDraft, ReportFollowUp, ReportPeriod, ReportSource, ResolvedBlock,
    default_sections, synthetic_profiles,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_sources import source_reference


def issue_report(text="", **kwargs):
    return ReportDraft(
        synthetic_profiles()[0], ReportPeriod(2026, 8), "Synthetic Operator",
        tuple(s for s in default_sections() if s.key == "issues"),
        (ResolvedBlock("equipment_issues", "This month", text=text),),
        **kwargs,
    )


@pytest.mark.parametrize("status", ["updated", "resolved"])
def test_rollover_keeps_followup_source_evidence_but_requires_current_review(status):
    source = ReportSource(
        "repair-evidence", "repair.pdf", "a" * 64, ".pdf",
        page_texts=("CH-2 bearing replaced and tested.",),
    )
    item = ReportFollowUp(
        "issue-ch2", "issue", "CH-2 vibration", "2026-07", status=status,
        references=(source_reference(source, 1),),
    )
    item = replace(item, reviewed_fingerprint=confirmation(item, ReportPeriod(2026, 8)))
    prior = issue_report(sources=(source,), follow_ups=(item,))

    for month in (9, 10):
        current = new_month_draft(prior, ReportPeriod(2026, month))
        carried, = current.follow_ups
        assert carried.references == item.references
        assert current.sources == (source,)
        assert carried.status == status
        assert carried.reviewed_fingerprint == ""
        assert problems(carried, current) == (
            "Confirm whether this carried item is ongoing, updated or resolved this month.",
        )
        confirmed = replace(carried, reviewed_fingerprint=confirmation(carried, current.period))
        assert not problems(confirmed, current)
        changed = replace(current, sources=(replace(source, findings="Corrected evidence"),))
        assert any("source changed" in message for message in problems(confirmed, changed))
        prior = replace(current, follow_ups=(confirmed,))


@pytest.mark.parametrize(("text", "expected"), [
    (
        "- CH-2 vibration\n  Bearing inspection planned.\n- AHU-1 belt noise\nVendor called.",
        ("CH-2 vibration\nBearing inspection planned.", "AHU-1 belt noise\nVendor called."),
    ),
    (
        "CH-2 vibration remains under review.\nBearing inspection planned.\n\nAHU-1 belt noise\nVendor called.",
        ("CH-2 vibration remains under review.\nBearing inspection planned.", "AHU-1 belt noise\nVendor called."),
    ),
    (
        "1. CH-2 vibration\n   Bearing inspection planned.\n2. AHU-1 belt noise",
        ("CH-2 vibration\nBearing inspection planned.", "AHU-1 belt noise"),
    ),
    (
        "• CH-2 vibration\n  - Bearing inspection planned.\n  - Oil sample pending.\n• AHU-1 belt noise",
        ("CH-2 vibration\n- Bearing inspection planned.\n- Oil sample pending.", "AHU-1 belt noise"),
    ),
])
def test_rollover_keeps_multiline_issue_details_together(text, expected):
    current = new_month_draft(issue_report(text), ReportPeriod(2026, 9))
    assert tuple(item.text for item in current.follow_ups) == expected
    assert all(item.status == "ongoing" for item in current.follow_ups)


@pytest.mark.parametrize("text", [
    "No current equipment issues.",
    "No equipment issues this month",
    "  NO CURRENT EQUIPMENT PERFORMANCE ISSUES.  ",
    "- No equipment performance issues.",
])
def test_explicit_no_issue_declaration_does_not_become_a_followup(text):
    assert not new_month_draft(issue_report(text), ReportPeriod(2026, 9)).follow_ups


@pytest.mark.parametrize("text", [
    "No new equipment issues; CH-2 vibration remains ongoing.",
    "No current equipment issues. CH-2 inspection is pending.",
    "No current equipment issues.\nCH-2 inspection is pending.",
    "No equipment issues at AHU-1; CH-2 remains under investigation.",
])
def test_no_issue_phrase_does_not_hide_actual_problem_prose(text):
    current = new_month_draft(issue_report(text), ReportPeriod(2026, 9))
    assert tuple(item.text for item in current.follow_ups) == (text,)


def test_no_issue_declaration_does_not_hide_a_separate_issue():
    current = new_month_draft(
        issue_report("- No current equipment issues.\n- CH-2 inspection is pending."),
        ReportPeriod(2026, 9),
    )
    assert tuple(item.text for item in current.follow_ups) == ("CH-2 inspection is pending.",)
