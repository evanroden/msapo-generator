"""An old cover plus a planned target-month mention is not completed work.

All Word inputs are synthetic. The author still owns explicit period review,
source-page decisions, and final wording; no old originals are rewritten.
"""
from io import BytesIO
from pathlib import Path

from docx import Document
import pytest

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_start_import import (
    _target_month_evidence, analyze_starting_report, automatic_section_plans,
    mentioned_periods,
)
from test_monthly_report_start_import import report_file, start_app, save_start


OCTOBER = ReportPeriod(2026, 10)
PROFILE = synthetic_profiles()[0]


def inspect(tmp_path, paragraphs, *, cover="September 2026", table=False):
    path = report_file(tmp_path, month=cover, activity=paragraphs,
                       table=table, contact=True)
    return path, inspect_docx(path)


def work_item(inspection, phrase):
    return next(item for item in inspection.items
                if phrase in item.text and item.suggested_slot == "activity_summary")


@pytest.mark.parametrize("scheduled", (
    "October 2026: the inspection is planned, not completed.",
    "Scheduled for October 2026: a system performance visit.",
    "An upcoming October 2026 follow-up was proposed.",
    "10/2026: expected contractor service, date not confirmed.",
    "Will inspect the synthetic pump on 2026-10-12.",
    "Pending October 2026 work; no current completion evidence.",
))
def test_future_only_target_date_is_not_current_month_evidence(tmp_path, scheduled):
    path, inspection = inspect(tmp_path, (scheduled, "Undated partial work."))
    result = analyze_starting_report(inspection, PROFILE, OCTOBER)
    planned, partial = (work_item(inspection, text) for text in
                        (scheduled, "Undated partial work."))
    assert result.source_period == (2026, 9)
    assert not result.current_items
    assert {planned.id, partial.id}.issubset(result.uncertain_items)
    assert {planned.id, partial.id}.issubset(result.period_review_items)
    assert planned.id not in result.older_items
    activity = automatic_section_plans(inspection, result)["activity"]
    assert not activity["approved"]
    assert planned.id in activity["selected"]
    assert partial.id in activity["selected"]
    assert not any("pricing" in problem.lower() for problem in activity["questions"])
    assert path.exists()


def test_planned_sibling_still_needs_review_when_another_task_is_genuinely_current(tmp_path):
    statements = (
        "October 2026 repair of synthetic pump completed.",
        "October 2026 preventive-maintenance visit is scheduled.",
        "September 2026: previous inspection finished.",
        "Undated current draft update.",
    )
    path, inspection = inspect(tmp_path, statements)
    result = analyze_starting_report(inspection, PROFILE, OCTOBER)
    completed, planned, old, undated = (work_item(inspection, item) for item in statements)
    assert completed.id in result.current_items
    assert planned.id not in result.current_items and planned.id in result.uncertain_items
    assert planned.id in result.period_review_items
    assert old.id in result.older_items
    assert undated.id in result.uncertain_items
    assert undated.id not in result.period_review_items  # Genuine current evidence exists.
    activity = automatic_section_plans(inspection, result)["activity"]
    assert not activity["approved"]
    assert planned.id in activity["selected"]
    assert completed.id in activity["selected"]
    assert undated.id in activity["selected"]
    assert old.id not in activity["selected"]
    assert any("cover shows an earlier month" in notice for notice in activity["questions"])


@pytest.mark.parametrize("body,current,scheduled", (
    ("October 2026 site inspection completed.", True, False),
    ("Completed October 2, 2026 synthetic maintenance.", True, False),
    ("2026-10-16: repaired the demonstration pump.", True, False),
    ("October 2026: new maintenance order scheduled.", False, True),
    ("September 2026 repair completed. October 2026 follow-up planned.", False, True),
    ("September 2026 repair completed; October 2026 inspection performed.", True, False),
    ("October 2026 equipment tested. November 2026 upgrade planned.", True, False),
    ("October 2026 work completed; October 2026 inspection proposed.", True, True),
    ("September 2026 completed work; undated next visit.", False, False),
))
def test_month_evidence_is_clause_scoped_and_does_not_infer_completion(body, current, scheduled):
    assert _target_month_evidence(body, (2026, 10)) == (current, scheduled)


def test_planned_month_in_word_table_needs_review_without_losing_rows(tmp_path):
    path, _ = inspect(tmp_path, ("October 2026 repair completed.",),
                      table=True)
    doc = Document(path)
    table = doc.tables[-1]
    original_header = tuple(cell.text for cell in table.rows[0].cells)
    table.cell(1, 0).text = "October 2026 planned"
    table.cell(1, 1).text = "2"
    table.cell(2, 0).text = "September 2026 completed"
    table.cell(2, 1).text = "4"
    doc.save(path)
    inspection = inspect_docx(path)
    result = analyze_starting_report(inspection, PROFILE, OCTOBER)
    table_item = next(item for item in inspection.items
                      if item.kind == "table"
                      and any("October 2026 planned" in cell for row in item.rows for cell in row))
    assert table_item.id in result.period_review_items
    assert table_item.id in result.uncertain_items
    assert table_item.id not in result.current_items
    plans = automatic_section_plans(inspection, result)
    owner = next(plan for plan in plans.values()
                 if table_item.id in plan["tables"])
    assert not owner["approved"]
    source_table = owner["tables"][table_item.id]
    assert source_table.columns == original_header
    assert source_table.rows[0] == ("October 2026 planned", "2")
    assert source_table.rows[1] == ("September 2026 completed", "4")
    assert Path(path).exists()


def test_native_start_requires_confirmation_and_durable_accepted_text_unchanged(
        monkeypatch, tmp_path):
    # The old source has only a *planned* October visit, plus undated work.
    # It must not become a completed October entry by merely uploading it.
    path = report_file(tmp_path, month="July 2026",
                       activity=("September 2026: a pump service is scheduled.",
                                 "Undated unfinished synthetic current notes."))
    original = path.read_bytes()
    # The existing production AppTest fixture targets September 2026.
    app = start_app(monkeypatch, tmp_path, path)
    proceed = lambda: next(b for b in app.button
                           if b.label == "Continue to this month’s updates")
    assert not app.exception and proceed().disabled
    reviewer = next(c for c in app.checkbox
                    if c.label == "This work belongs in September 2026")
    assert not reviewer.value
    reviewer.check().run()
    assert not app.exception and not proceed().disabled
    draft = save_start(app)
    work = next(b for b in draft.blocks if b.key == "activity_summary")
    assert "September 2026: a pump service is scheduled." in work.text
    assert "Undated unfinished synthetic current notes." in work.text
    assert original == path.read_bytes()

    saved = library.save_snapshot(draft, expected_revision=0,
                                  entered_editor="Synthetic reviewer")
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key,
                                     draft.period)
    assert reopened.draft == saved.draft
    assert original == path.read_bytes()

    # Layout-only assembly checks preservation. The required fully populated
    # client preflight/Generate journey remains a separate acceptance gate.
    from app.monthly_report_docx import _build_docx
    rendered = Document(BytesIO(_build_docx(reopened.draft)))
    text = "\n".join(p.text for p in rendered.paragraphs)
    assert "pump service is scheduled" in text
    assert "Undated unfinished" in text
    assert text.count("pump service is scheduled") == 1


@pytest.mark.parametrize("label,expected", (
    ("Sept 2026", {(2026, 9)}),
    ("Sept. 2026", {(2026, 9)}),
    ("09/2026", {(2026, 9)}),
    ("9/2026", {(2026, 9)}),
    ("10/2026", {(2026, 10)}),
    ("2026-10-12", {(2026, 10)}),
    ("September 3, 2026", {(2026, 9)}),
    ("C:\\reports\\10/2026", set()),
    ("PO-10/2026", set()),
    ("10/2026.5", set()),
    ("10/20/2026", {(2026, 10)}),
    ("September inspection", set()),
))
def test_compact_source_period_evidence_is_bounded(label, expected):
    assert mentioned_periods(label) == expected


def test_compact_stale_cover_and_compact_future_task_still_require_review(tmp_path):
    path, inspection = inspect(
        tmp_path, ("10/2026: the generator inspection is planned.", "Undated pump notes."),
        cover="09/2026")
    result = analyze_starting_report(inspection, PROFILE, OCTOBER)
    assert result.source_period == (2026, 9)
    assert not result.current_items
    task = work_item(inspection, "the generator inspection is planned")
    assert task.id in result.period_review_items
    assert not automatic_section_plans(inspection, result)["activity"]["approved"]
    assert path.exists()
