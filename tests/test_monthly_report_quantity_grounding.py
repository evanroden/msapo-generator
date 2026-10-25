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
    ("One hundred thousand thousand tenants.", {"100000"}),
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


@pytest.mark.parametrize("text,expected", [
    ("Replaced 2,000 filters; 2000 filters; 1,250.50 feet.", {"2000", "1250.5"}),
    ("Capacity is two million BTU/hr, 2 million BTU/hr or 2.5 million.", {"2000000", "2500000"}),
    ("Pressure five point two psi and 5.20 psi.", {"5.2"}),
    ("Valve opened point five turns, or 0.50 turns.", {"0.5"}),
    ("Two dozen filters; two and a half hours.", {"two dozen", "two and a half"}),
])
def test_digits_and_words_share_one_canonical_form(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote", [
    ("Capacity is 2 BTU/hr.", "Capacity is two million BTU/hr."),
    ("Pressure measured 5psi.", "Pressure measured five point two psi."),
    ("Valve opened 5 turns.", "Valve opened point five turns."),
    ("Replaced 2 filters.", "Replaced two dozen filters."),
    ("Worked 2 hours.", "Worked two and a half hours."),
])
def test_part_of_a_number_phrase_supports_nothing(text, quote):
    page = replace(SOURCE, page_texts=(quote,))
    with pytest.raises(ValueError, match="unsupported numbers"):
        ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)


@pytest.mark.parametrize("text,quote", [
    ("Replaced two thousand filters.", "Replaced 2,000 filters."),
    ("Replaced 2,000 filters.", "Replaced two thousand filters."),
    ("Capacity is 2 million BTU/hr.", "Capacity is two million BTU/hr."),
    ("Pressure measured 5.2psi.", "Pressure measured five point two psi."),
    ("Replaced two dozen filters.", "Replaced two dozen filters."),
])
def test_equal_quantities_in_different_forms_are_accepted(text, quote):
    page = replace(SOURCE, page_texts=(quote,))
    facts = ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)
    assert [item.text for item in facts] == [text]


@pytest.mark.parametrize("dash", ["‐", "‑", "‒", "–", "−", "﹣", "－"])
def test_a_unicode_hyphen_joins_number_words_like_an_ascii_one(dash):
    assert ai.numbers(f"Replaced twenty{dash}five filters.") == {"25"}


@pytest.mark.parametrize("text", ["No one was injured.", "No-one was injured.", "They helped one another."])
def test_one_as_a_pronoun_is_not_a_quantity(text):
    assert ai.numbers(text) == set()
    assert ai.numbers("Replaced one pump.") == {"1"}


def test_a_fact_and_its_quote_are_read_separately_so_their_boundary_makes_no_number():
    quote = "Five pumps inspected; the filter count was twenty"
    page = replace(SOURCE, page_texts=(quote + ".",))
    facts = ai.normalize_facts(fact("The filter count was twenty", quote), page, (1,), PROFILE, PERIOD)
    assert ai.fact_numbers(facts) == {"20", "5"}
    source = replace(page, facts=facts)
    block = ai.normalize_draft({"paragraphs": [{"text": "The filter count was 25.", "fact_ids": [facts[0].id]}]},
                               "activity_summary", facts, (source,))
    assert any("Unsupported number" in flag for flag in block.ai_paragraphs[0].flags)


@pytest.mark.parametrize("text,expected", [
    ("Replaced two half-inch valves.", {"2"}),
    ("Made two quarter-turn adjustments.", {"2"}),
    ("Worked two and a half hours.", {"two and a half"}),
    ("Capacity is point five million BTU/hr.", {"500000"}),
    ("A hundred filters and an hundred valves; a thousand feet.", {"100", "1000"}),
])
def test_unit_adjectives_and_leading_decimals_keep_their_meaning(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote,accepted", [
    ("Replaced two half-inch valves.", "Replaced two valves (half-inch).", True),
    ("Capacity is 500000 BTU/hr.", "Capacity is point five million BTU/hr.", True),
    ("Capacity is 0.5 BTU/hr.", "Capacity is point five million BTU/hr.", False),
])
def test_unit_adjectives_and_scaled_leading_decimals_ground_correctly(text, quote, accepted):
    page = replace(SOURCE, page_texts=(quote,))
    if accepted:
        assert [f.text for f in ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)] == [text]
    else:
        with pytest.raises(ValueError, match="unsupported numbers"):
            ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)
