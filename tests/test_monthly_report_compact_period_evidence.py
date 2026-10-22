"""Short and compact reporting periods must not hide prior-month facts.

Synthetic-only parser and editor-check controls. This does not authorize
carry-forward, redate source pages, or certify a genuine Word/PDF export.
"""
from types import SimpleNamespace

import pytest

from app.monthly_report_checks import preflight, stale_period_mentions
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec,
    synthetic_profiles,
)
from app.monthly_report_period_items import historical_allowed, pending_items
from app.monthly_report_setup import item_findings, report_period_findings


OCTOBER = ReportPeriod(2026, 10)


@pytest.mark.parametrize("text,expected", (
    ("Sept 2026", ("Sept 2026",)),
    ("Sept. 2026", ("Sept. 2026",)),
    ("Sep. 2026", ("Sep. 2026",)),
    ("09/2026", ("09/2026",)),
    ("9/2026", ("9/2026",)),
    ("13/2026", ("13/2026",)),
    ("Since 13/2026", ("13/2026",)),
    ("00/2026", ("00/2026",)),
    ("99/2026", ("99/2026",)),
    ("October 2026", ()),
    ("10/2026", ()),
    ("Planned 11/2026 follow-up", ()),
    ("Completed 11/2026 follow-up", ("11/2026",)),
    ("Since 09/2026, work is continuing", ()),
    ("PO-09/2026", ()),
    ("09/2026/03", ()),
    ("109/2026", ()),
    ("09/20260", ()),
    ("09/2026.5", ()),
    ("September 2026", ("September 2026",)),
    ("September 15, 2026", ("September 15, 2026",)),
    ("09/15/2026", ("09/15/2026",)),
    ("2026-09-15", ("2026-09-15",)),
    ("Sept. 2026 work; planned November 2026 follow-up", ("Sept. 2026",)),
    ("May we inspect the pump?", ()),
    ("March on to the next section.", ()),
    ("May 2026", ("May 2026",)),
    ("Sept 2025", ("Sept 2025",)),
    ("09/2027", ("09/2027",)),
    ("Planned 09/2027 follow-up", ()),
    ("Q3/2026", ()),
    ("11/2026.5", ()),
))
def test_month_year_warning_has_complete_token_and_future_controls(text, expected):
    assert stale_period_mentions(text, OCTOBER.year, OCTOBER.month) == expected


@pytest.mark.parametrize("text,expected", (
    ("Sept. 2026", True),
    ("09/2026", True),
    ("09/2025", True),
    ("09/2026 and 10/2026", False),
    ("Sept 2026 and October 2026", False),
    ("09/2026 and planned 11/2026", False),
    ("09/2026 and 13/2026", False),
    ("09/2026 and 00/2026", False),
    ("09/2027", False),
    ("PO-09/2026", False),
    ("09/2026 and 09/2026", True),
    ("Planned 11/2026", False),
    ("May we inspect?", False),
    ("March on.", False),
))
def test_historical_action_requires_all_dates_to_be_prior(text, expected):
    assert historical_allowed(text, OCTOBER) is expected


@pytest.mark.parametrize("text,expected", (
    ("Sept. 2026: synthetic activity.", "Sept. 2026"),
    ("09/2026: synthetic activity.", "09/2026"),
    ("13/2026: incorrect date.", "13/2026"),
))
def test_unresolved_month_reference_is_visible_to_editor_preflight(text, expected):
    section = SectionSpec("activity", "2", "Activity",
                          (BlockSpec("activity_summary", "rich_text"),))
    block = ResolvedBlock("activity_summary", "This month", text=text)
    draft = ReportDraft(synthetic_profiles()[0], OCTOBER, "Synthetic Reviewer",
                        (section,), (block,))
    checks = [check for check in preflight(draft)
              if check.code == "period" and check.block_key == "activity_summary"]
    assert len(checks) == 1 and expected in checks[0].message
    items = pending_items(block, OCTOBER)
    assert len(items) == 1 and expected in items[0].mentions


def test_period_evidence_counts_current_compact_and_prior_abbreviation_without_cover_authority():
    item = lambda section, kind, text="": SimpleNamespace(
        section=section, kind=kind, text=text, rows=())
    inspection = SimpleNamespace(items=(
        item("activity", "text", "Sept. 2026 synthetic service"),
        item("activity", "text", "10/2026 current synthetic service"),
        item("water", "image"),
        item("cover", "text", "October 2026"),  # A cover never dates a body page.
        item("activity", "text", "PO-10/2026 is only an identifier"),
    ))
    assert report_period_findings(inspection, OCTOBER) == {
        "current": 1, "older": 1, "images": 1}


@pytest.mark.parametrize("label", ("Sept 2026", "Sept. 2026", "09/2026"))
def test_starting_item_warns_about_old_compact_month(label):
    item = SimpleNamespace(kind="text", text=label, rows=(),
                           suggested_slot="activity_summary")
    assert any(label in finding for finding in item_findings(item, OCTOBER))


@pytest.mark.parametrize("label", ("Sep 2026", "Sept 2026", "Sept. 2026", "09/2026"))
def test_same_month_variants_do_not_create_false_stale_warning(label):
    assert not stale_period_mentions(label, 2026, 9)
