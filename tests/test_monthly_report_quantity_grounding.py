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
    ("One hundred thousand thousand tenants.", {"one hundred thousand thousand"}),  # Unreadable: as written.
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
    ("Capacity is two million BTU/hr, 2 Million BTU/hr, 2million or 2.5 million.", {"2000000", "2500000"}),
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


@pytest.mark.parametrize("text,expected", [
    ("Capacity is 1.2e6 BTU/hr; 3E-2 m.", {"1200000", "0.03"}),
    ("Capacity is half a million BTU/hr or a quarter of a million.", set()),
    ("Rated 500k BTU; panel 2B; room 5A.", {"500k", "2b", "5a"}),
    ("Measured 40psi, 3.5kW, 120gpm and 2nd floor.", {"40", "3.5", "120", "2"}),
    ("Value 1e999999 stays text.", {"1e999999"}),
])
def test_a_quantity_never_leaks_a_partial_value(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote,accepted", [
    ("Capacity is 1.2 BTU/hr.", "Capacity is 1.2e6 BTU/hr.", False),
    ("Capacity is 1,200,000 BTU/hr.", "Capacity is 1.2e6 BTU/hr.", True),
    ("Capacity is 1000000 BTU/hr.", "Capacity is half a million BTU/hr.", False),
    ("Rated 500 BTU.", "Rated 500k BTU.", False),
    ("Inspected room 5.", "Inspected room 5A.", False),
    ("Inspected room 5A.", "Inspected room 5A.", True),
])
def test_scientific_suffixed_and_fractional_scale_quantities_ground_safely(text, quote, accepted):
    page = replace(SOURCE, page_texts=(quote,))
    if accepted:
        assert [f.text for f in ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)] == [text]
    else:
        with pytest.raises(ValueError, match="unsupported numbers"):
            ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)


@pytest.mark.parametrize("text,expected", [
    ("Inspected the twenty-first and forty-fourth floors.", {"21", "44"}),
    ("Inspected the twenty-second floor.", {"twenty second"}),  # 22nd, or a 20-second span.
    ("Two first-floor pumps.", {"2"}),
    ("Voltage measured 120V, 500W, 250kVA and 15kVAR at 480VAC.", {"120", "500", "250", "15", "480"}),
    ("Breaker in room 5A.", {"5a"}),
])
def test_ordinals_and_electrical_units_read_without_leaking(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote,accepted", [
    ("Inspected floor 20.", "Inspected the twenty-second floor.", False),
    ("Inspected the 21st floor.", "Inspected the twenty-first floor.", True),
    ("Voltage measured 120V.", "Voltage measured 120 V.", True),
    ("Rated 250kVA.", "Rated 250 kVA.", True),
    ("Rated 240V.", "Rated 120 V.", False),
])
def test_ordinals_and_electrical_units_ground_correctly(text, quote, accepted):
    page = replace(SOURCE, page_texts=(quote,))
    if accepted:
        assert [f.text for f in ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)] == [text]
    else:
        with pytest.raises(ValueError, match="unsupported numbers"):
            ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)


@pytest.mark.parametrize("text,expected", [
    ("Capacity is .5 million BTU/hr or .25 kW.", {"500000", "0.25"}),
    ("Pressure measured 5 point two psi.", {"5 point two"}),
    ("Delay was one second, then 1 second, then two seconds.", {"1", "2"}),
    ("Pumps 5 6 and 7 ran; two and three were idle.", {"5", "6", "7", "2", "3"}),
    ("Pumps two three and four; twenty twenty.", {"2", "3", "4", "20"}),
])
def test_one_written_quantity_yields_exactly_one_token(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote,accepted", [
    ("Capacity is 5000000 BTU/hr.", "Capacity is .5 million BTU/hr.", False),
    ("Capacity is 500000 BTU/hr.", "Capacity is .5 million BTU/hr.", True),
    ("Pressure measured 0.2 psi.", "Pressure measured 5 point two psi.", False),
    ("Pressure measured 5 psi.", "Pressure measured 5 point two psi.", False),
    ("Delay was one second.", "Delay was 1 second.", True),
])
def test_mixed_and_leading_decimal_quantities_ground_safely(text, quote, accepted):
    page = replace(SOURCE, page_texts=(quote,))
    if accepted:
        assert [f.text for f in ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)] == [text]
    else:
        with pytest.raises(ValueError, match="unsupported numbers"):
            ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)


@pytest.mark.parametrize("text,expected", [
    ("Pressure measured five point two five psi.", {"5.25"}),
    ("Capacity is two point five five million BTU/hr.", {"2550000"}),
    ("Two point five dozen filters.", {"two point five dozen"}),
    ("Temperature measured minus five degrees, then negative 3.5 and -10 F.", {"-5", "-3.5", "-10"}),
    ("Tolerance is plus or minus five percent; 10 minus 2 remain.", {"5", "10", "2"}),
    ("Rooms 101-105 on 2026-09-15; R-22 and 1.2e-5.", {"101", "105", "2026", "9", "15", "22", "0.000012"}),
    ("① Pump inspection completed.¹ ② Valve exercised.", set()),
])
def test_signs_fractions_and_unicode_markers_read_whole(text, expected):
    assert ai.numbers(text) == expected


@pytest.mark.parametrize("text,quote,accepted", [
    ("Pressure measured 5.2 psi.", "Pressure measured five point two five psi.", False),
    ("Pressure measured 5.25 psi.", "Pressure measured five point two five psi.", True),
    ("Temperature measured 5 degrees.", "Temperature measured minus five degrees.", False),
    ("Freezer held 10 F.", "Freezer held -10 F.", False),
    ("Temperature measured -5 degrees.", "Temperature measured minus five degrees.", True),
    ("Tolerance is plus or minus 5 percent.", "Tolerance is plus or minus five percent.", True),
    ("Pump inspection completed.", "① Pump inspection completed.¹", True),
])
def test_signed_and_multi_digit_fractions_ground_safely(text, quote, accepted):
    page = replace(SOURCE, page_texts=(quote,))
    if accepted:
        assert [f.text for f in ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)] == [text]
    else:
        with pytest.raises(ValueError, match="unsupported numbers"):
            ai.normalize_facts(fact(text, quote), page, (1,), PROFILE, PERIOD)
