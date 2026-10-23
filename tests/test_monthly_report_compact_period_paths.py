"""Windows path components are not reporting-period evidence.

Synthetic narrative/editor controls only; no genuine saved report is changed.
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
PATH_TEMPLATES = (
    r"C:\reports\{token}",
    r"{token}\notes",
    r"C:\reports\{token}\notes",
    r"\\server\share\{token}",
)
TOKENS = ("09/2026", "9/2026", "10/2026", "11/2026", "13/2026")


def _body_item(text, kind="text"):
    return SimpleNamespace(
        section="activity", kind=kind,
        text=text if kind == "text" else "",
        rows=((text,),) if kind == "table" else (),
        suggested_slot="activity_summary",
    )


@pytest.mark.parametrize("template", PATH_TEMPLATES)
@pytest.mark.parametrize("token", TOKENS)
def test_windows_path_does_not_warn_or_authorize_historical_work(template, token):
    text = "Current service notes saved to " + template.format(token=token)
    assert stale_period_mentions(text, OCTOBER.year, OCTOBER.month) == ()
    assert historical_allowed(text, OCTOBER) is False
    assert not any("Other-month/date" in finding
                   for finding in item_findings(_body_item(text), OCTOBER))

    block = ResolvedBlock("activity_summary", "This month", text=text)
    assert pending_items(block, OCTOBER) == ()
    section = SectionSpec("activity", "2", "Activity",
                          (BlockSpec("activity_summary", "rich_text"),))
    draft = ReportDraft(synthetic_profiles()[0], OCTOBER, "Synthetic Reviewer",
                        (section,), (block,))
    assert not [check for check in preflight(draft)
                if check.code == "period" and check.block_key == block.key]
    assert block.text == text


@pytest.mark.parametrize("template", PATH_TEMPLATES)
@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.parametrize("kind", ("text", "table"))
def test_windows_path_is_neither_current_nor_old_body_evidence(template, token, kind):
    text = "Current service notes saved to " + template.format(token=token)
    inspection = SimpleNamespace(items=(_body_item(text, kind),))
    assert report_period_findings(inspection, OCTOBER) == {
        "current": 0, "older": 0, "images": 0}


@pytest.mark.parametrize("text", (
    "09/2026", "9/2026", "(09/2026)", "09/2026.",
    "09/2026, service completed", "Service period: 09/2026; notes retained",
))
def test_standalone_old_month_still_warns_and_allows_historical_context(text):
    token = "9/2026" if text == "9/2026" else "09/2026"
    assert stale_period_mentions(text, 2026, 10) == (token,)
    assert historical_allowed(text, OCTOBER) is True


@pytest.mark.parametrize("text,mentions,historical,current,older", (
    (r"10/2026 work saved to C:\reports\09/2026", (), False, 1, 0),
    (r"09/2026 work saved to C:\reports\10/2026", ("09/2026",), True, 0, 1),
    (r"09/2026 work and planned 11/2026 follow-up; C:\reports\09/2026",
     ("09/2026",), False, 0, 1),
    (r"09/2026 work and 10/2026 work; C:\reports\09/2026",
     ("09/2026",), False, 1, 1),
    (r"Since 09/2026, work continues; C:\reports\09/2026", (), False, 0, 0),
    (r"Since 13/2026, work continues; C:\reports\09/2026",
     ("13/2026",), False, 0, 1),
))
def test_real_dates_keep_their_existing_meaning_beside_a_windows_path(
        text, mentions, historical, current, older):
    assert stale_period_mentions(text, 2026, 10) == mentions
    assert historical_allowed(text, OCTOBER) is historical
    inspection = SimpleNamespace(items=(_body_item(text),))
    assert report_period_findings(inspection, OCTOBER) == {
        "current": current, "older": older, "images": 0}
