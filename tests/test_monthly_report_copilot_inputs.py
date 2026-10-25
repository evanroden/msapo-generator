"""Synthetic pasted notes and prompt inspection; no external reader calls."""

from dataclasses import asdict, replace
import json

import pytest

from app import monthly_report_ai as ai
from app.monthly_report_ai_ui import copilot_source
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, ReportPeriod, ReportTable, ResolvedBlock,
    SectionSpec, synthetic_draft, synthetic_profiles,
)
from app.monthly_report_prompts import DRAFT_PROMPT, copilot_prompt, parse_copilot


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)


@pytest.mark.parametrize("statement", [
    "Work completed included replacing the pump seal",
    "Vendor visits were rescheduled",
    "Issues remained open after inspection",
    "Quotes were requested for the pump",
    "Meetings confirmed the shutdown plan",
    "Training was delivered to the facilities team",
    "Safety improvements were reviewed",
    "Upcoming work includes checking the seal",
])
def test_heading_words_in_cited_content_do_not_drop_or_retarget_notes(statement):
    notes = ("2. VENDOR VISITS & SERVICE REPORTS\n"
             f"{statement} [email from service team, 09/03]\n"
             "09/04 Inspected the pump [service report, 09/04]")
    source, unmatched, excluded = copilot_source(notes, PROFILE, PERIOD)
    assert not unmatched and excluded == 0
    assert [fact.kind for fact in source.facts] == ["finding", "finding"]
    assert [fact.text for fact in source.facts] == [statement, "09/04 Inspected the pump"]
    assert [fact.page for fact in source.facts] == [1, 2]
    assert source.page_texts[0] == statement + " [email from service team, 09/03]"
    assert all("verify the cited original" in fact.flags[0] for fact in source.facts)


@pytest.mark.parametrize("heading", [
    "Work completed needs checking", "Training status is unclear", "Safety observations",
])
def test_uncited_heading_like_prose_remains_visible_without_changing_section(heading):
    raw = "* " + heading
    lines, unmatched = parse_copilot("1. WORK COMPLETED\n" + raw + "\n09/04 Inspected pump")
    assert unmatched == ((2, raw),)
    assert [(line.section, line.source, line.line) for line in lines] == [
        (1, "Source not supplied", 3),
    ]


@pytest.mark.parametrize("section,heading", [
    (1, "## 1. WORK COMPLETED"),
    (2, "**2) Vendor visits & service reports:**"),
    (3, "3. Issues & equipment problems"),
    (4, "4. Quotes & proposals:"),
    (5, "5. MEETINGS & CLIENT COMMUNICATION"),
    (6, "__6. Training__"),
    (7, "7. Safety & improvements"),
    (8, "8. Upcoming / follow-ups"),
    (2, "VENDOR VISITS"),
    (3, "ISSUES"),
    (4, "QUOTES"),
    (5, "MEETINGS"),
    (7, "SAFETY"),
    (8, "UPCOMING"),
])
def test_complete_structural_headings_still_route_dated_content(section, heading):
    lines, unmatched = parse_copilot(heading + "\n09/03 Checked pump [email, 09/03]")
    assert not unmatched
    assert len(lines) == 1 and lines[0].section == section
    assert lines[0].text == "09/03 Checked pump"


def test_cited_exact_heading_is_content_and_absent_section_stays_unmatched():
    notes = "Training was delivered [meeting, 09/03]"
    assert parse_copilot(notes) == ((), ((1, notes),))
    lines, unmatched = parse_copilot("1. WORK COMPLETED\nTraining [meeting, 09/03]")
    assert not unmatched
    assert [(line.section, line.text) for line in lines] == [(1, "Training")]


def vendor_draft(columns, rows, extra_tables=()):
    spec = BlockSpec("subcontractor_matrix", "table", columns=tuple(
        ColumnSpec(f"column-{i}", title) for i, title in enumerate(columns)
    ))
    return replace(
        synthetic_draft(PROFILE, PERIOD),
        sections=(SectionSpec("subcontractors", "6", "Sub-Contractor Status", (spec,)),),
        blocks=(ResolvedBlock("subcontractor_matrix", "This month", rows=rows,
                              extra_tables=extra_tables),),
    )


@pytest.mark.parametrize("heading", [
    "Vendor", "Vendor name", "Company", "Company Name", "Contractor",
    "Contractor Name", "Subcontractor", "Sub-contractor name", "Supplier",
    "  COMPANY\n NAME  ",
])
def test_explicit_vendor_name_columns_preserve_spelling_and_order(heading):
    draft = vendor_draft((heading,), (("Synthetic Service",), ("",), (),
                                     ("Synthetic Service",), ("Other Synthetic Co.",)))
    assert ai.vendor_names(draft) == ("Synthetic Service", "Other Synthetic Co.")


@pytest.mark.parametrize("heading", [
    "Vendor Contact", "Company Contact Name", "Contractor Representative",
    "Vendor Email", "Company E-mail", "Contractor Phone", "Vendor / Contact",
    "Vendor Address", "Vendor Status", "Vendor Notes", "Vendor Contact / Company",
    "Contact at Company", "", "Name",
])
def test_contact_and_unrelated_columns_never_establish_vendor_names(heading):
    draft = vendor_draft(("Vendor", heading), (("Synthetic Service", "OMIT-CANARY"),))
    assert ai.vendor_names(draft) == ("Synthetic Service",)


def test_both_prompt_paths_minimize_custom_and_extra_tables_without_mutating_them():
    draft = vendor_draft(
        ("Vendor Contact", "Vendor", "Company Email", "Vendor Phone"),
        (("PERSON-CANARY", "Synthetic Service", "omit@example.invalid", "+1 202-555-0199"),),
        (ReportTable(("Company", "Contractor Contact", "Vendor Status"),
                     (("Other Synthetic Co.", "EXTRA-PERSON-CANARY", "STATUS-CANARY"),)),),
    )
    before = asdict(draft)
    vendors = ai.vendor_names(draft)
    assert vendors == ("Synthetic Service", "Other Synthetic Co.")
    prompt = copilot_prompt(PROFILE, PERIOD, vendors)
    source, _, _ = copilot_source("1. WORK COMPLETED\n09/03 Inspected pump [email, 09/03]",
                                  PROFILE, PERIOD)
    _, content, _ = ai.drafting_request("activity_summary", (source,), PERIOD, vendors)
    payload = json.loads(content[0]["text"][len(DRAFT_PROMPT) + 1:])
    assert payload["vendors"] == list(vendors)
    for canary in ("PERSON-CANARY", "omit@example.invalid", "+1 202-555-0199",
                   "EXTRA-PERSON-CANARY", "STATUS-CANARY"):
        assert canary not in prompt and canary not in content[0]["text"]
    assert asdict(draft) == before
