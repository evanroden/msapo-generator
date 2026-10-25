"""A suggested quantity must match its evidence however either one writes it.

Synthetic pages and reader values only; no network call (#285, G4-ai-9).
"""

from dataclasses import replace

import pytest

from app import monthly_report_ai as ai
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_profiles


PROFILE = synthetic_profiles()[0]
PERIOD = ReportPeriod(2026, 9)
PAGE = "Replaced two filters. Pressure measured 40psi. Chiller CH-2 uses R410A."
SOURCE = ReportSource("source-qty", "synthetic.pdf", "b" * 64, ".pdf",
                      page_texts=(PAGE,), selected_pages=(1,))


def fact(text, quote):
    return {"facts": [{"page": 1, "kind": "action", "text": text, "quote": quote}]}


@pytest.mark.parametrize("text,expected", [
    ("Replaced two filters.", {"2"}),
    ("Replaced thirty filters.", {"30"}),
    ("Twenty-five valves and twenty five dampers.", {"25"}),
    ("One hundred twenty feet; one hundred and five feet.", {"120", "105"}),
    ("Two thousand gallons.", {"2000"}),
    ("Two, three or four pumps.", {"2", "3", "4"}),
    ("Pressure measured 40psi at 3.5kW and 2nd floor.", {"40", "3.5", "2"}),
    ("Pressure measured 40 psi.", {"40"}),
    ("Chiller R410A and AHU1 are unchanged.", set()),
    ("Chiller CH-2 was inspected.", {"2"}),
    ("Someone inspected the pump; it was done.", set()),
    ("A hundred tenants; one hundred thousand thousand; a thousand.", {"100000"}),
])
def test_numbers_read_spelled_quantities_and_digits_attached_to_units(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote", [
    ("Replaced thirty filters.", "Replaced two filters."),
    ("Replaced 3 filters.", "Replaced two filters."),
    ("Pressure measured 90psi.", "Pressure measured 40psi."),
    ("Pressure measured 90 psi.", "Pressure measured 40psi."),
])
def test_a_changed_quantity_is_not_accepted_as_a_fact(text, quote):
    with pytest.raises(ValueError, match="unsupported numbers"):
        ai.normalize_facts(fact(text, quote), SOURCE, (1,), PROFILE, PERIOD)


@pytest.mark.parametrize("text,quote", [
    ("Replaced 2 filters.", "Replaced two filters."),
    ("Replaced two filters.", "Replaced two filters."),
    ("Pressure measured 40 psi.", "Pressure measured 40psi."),
    ("Inspected chiller CH-2 using R410A.", "Chiller CH-2 uses R410A."),
])
def test_the_same_quantity_written_differently_is_still_accepted(text, quote):
    facts = ai.normalize_facts(fact(text, quote), SOURCE, (1,), PROFILE, PERIOD)
    assert [item.text for item in facts] == [text]


def test_a_drafted_paragraph_with_a_changed_quantity_is_flagged_and_cannot_be_reviewed():
    facts = ai.normalize_facts(fact("Replaced two filters.", "Replaced two filters."),
                               SOURCE, (1,), PROFILE, PERIOD)
    source = replace(SOURCE, facts=facts)
    block = ai.normalize_draft({"paragraphs": [{"text": "Replaced thirty filters.", "fact_ids": [facts[0].id]}]},
                               "activity_summary", facts, (source,))
    assert any("Unsupported number" in flag for flag in block.ai_paragraphs[0].flags)
    with pytest.raises(ValueError, match="numerical"):
        ai.reviewed_block(block, (source,))
    same = ai.normalize_draft({"paragraphs": [{"text": "Replaced 2 filters.", "fact_ids": [facts[0].id]}]},
                              "activity_summary", facts, (source,))
    assert not any("Unsupported number" in flag for flag in same.ai_paragraphs[0].flags)
