from dataclasses import asdict, replace
from io import BytesIO
import json

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_followups import confirmation, problems
from app.monthly_report_model import (
    ReportPeriod,
    ReportSource,
    ResolvedBlock,
    synthetic_draft,
    synthetic_profiles,
    default_sections,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_sources import source_reference
from test_monthly_report_ui import monthly, step


def prior_report():
    base = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 8))
    return replace(
        base,
        sections=tuple(
            s for s in default_sections() if s.key in ("issues", "proposals")
        ),
        blocks=(
            ResolvedBlock(
                "equipment_issues",
                "This month",
                text="- Synthetic pump vibration remained under investigation.",
            ),
            ResolvedBlock(
                "proposals",
                "This month",
                rows=(
                    (
                        "Example facility",
                        "Synthetic Vendor",
                        "Controls upgrade",
                        "$1200",
                        "Pending",
                    ),
                ),
            ),
        ),
    )


def test_new_month_carries_issues_and_proposals_without_costs_or_silent_resolution():
    prior = prior_report()
    current = new_month_draft(prior, ReportPeriod(2026, 9))
    assert len(current.follow_ups) == 2
    assert all(i.status == "ongoing" and i.included for i in current.follow_ups)
    assert not any("1200" in i.text for i in current.follow_ups)
    assert "Pending" in current.follow_ups[1].text
    assert not any(b.text or b.rows for b in current.blocks)
    assert any(c.code == "follow_up" for c in preflight(current))
    assert new_month_draft(prior, prior.period) == prior
    assert library.draft_from_dict(json.loads(json.dumps(asdict(current)))) == current


def test_resolution_requires_evidence_and_explicit_removal_and_is_restorable():
    current = new_month_draft(prior_report(), ReportPeriod(2026, 9))
    item = replace(current.follow_ups[0], status="resolved", included=False)
    assert any("evidence" in p for p in problems(item, current))
    item = replace(
        item, evidence_note="Synthetic inspection confirmed corrective work."
    )
    item = replace(item, reviewed_fingerprint=confirmation(item, current.period))
    assert not problems(item, current)
    approved = tuple(
        replace(i, reviewed_fingerprint=confirmation(i, current.period))
        for i in current.follow_ups
    )
    ready = replace(current, follow_ups=approved)
    data = assemble_docx(ready, acknowledged_fingerprint=ready.fingerprint)
    text = "\n".join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert "Ongoing" in text and "pump vibration" in text and "$" not in text
    removed = replace(
        current,
        follow_ups=(item, *approved[1:]),
        blocks=(
            replace(current.blocks[0], text="No current equipment issues."),
            current.blocks[1],
        ),
    )
    next_month = new_month_draft(removed, ReportPeriod(2026, 10))
    assert item not in next_month.follow_ups
    assert prior_report().blocks[0].text  # The source snapshot remains immutable.
    with pytest.raises(ValueError):
        assemble_docx(
            replace(
                ready, follow_ups=(replace(approved[0], included=False), *approved[1:])
            )
        )


def test_changed_source_or_text_invalidates_followup_confirmation():
    current = new_month_draft(prior_report(), ReportPeriod(2026, 9))
    source = ReportSource(
        "synthetic-source",
        "synthetic.pdf",
        "a" * 64,
        ".pdf",
        page_texts=("Synthetic repair verified.",),
    )
    item = replace(
        current.follow_ups[0],
        status="updated",
        references=(source_reference(source, 1),),
    )
    item = replace(item, reviewed_fingerprint=confirmation(item, current.period))
    current = replace(current, sources=(source,))
    assert not problems(item, current)
    assert problems(replace(item, update="Different update"), current)
    assert any(
        "source changed" in p
        for p in problems(
            item, replace(current, sources=(replace(source, findings="Corrected"),))
        )
    )


def test_returning_user_reviews_carried_status_and_can_save_unfinished_work(
    monkeypatch, tmp_path
):
    app = monthly(monkeypatch, tmp_path)
    from app.contracts import RRH_CONTRACT

    profile = library.list_profiles(RRH_CONTRACT)[0]
    prior = replace(prior_report(), profile=profile)
    library.save_snapshot(prior, expected_revision=0, entered_editor="Synthetic Editor")
    # Recreate the session so the latest saved prior report is the starting point.
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_ui import ROOT, choose_report

    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, profile.facilities[0].title)
    step(app, 2)
    assert len([w for w in app.radio if w.label == "Current status"]) == 2
    next(w for w in app.radio if w.label == "Current status").set_value(
        "resolved"
    ).run()
    next(
        w for w in app.text_area if w.label == "Evidence or explanation for the status"
    ).set_value("Synthetic maintenance inspection verified resolution.").run()
    next(
        w
        for w in app.checkbox
        if w.label == "Leave this resolved item out of the report"
    ).check().run()
    next(
        w
        for w in app.checkbox
        if w.label == "I confirmed this item’s status and supporting information"
    ).check().run()
    assert not app.exception
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.radio if w.label == "Current status").value == "resolved"
    assert next(
        w
        for w in app.checkbox
        if w.label == "Leave this resolved item out of the report"
    ).value
