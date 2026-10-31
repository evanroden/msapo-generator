"""Legacy normalized proposal occurrences survive literal-cell migration."""
from dataclasses import replace
import pytest
from app.monthly_report_followups import _proposal_details, seed_followups
from app.monthly_report_model import ReportPeriod
from app.monthly_report_setup import new_month_draft
from test_monthly_report_proposal_table_carryover import table_draft


def legacy_rows(prior):
    return tuple(replace(item, text=_proposal_details(item.text + "; Status: " + item.status.replace("_", " "))[0], key="legacy-shared")
                 for item in seed_followups(prior))


@pytest.mark.parametrize("identical", [False, True])
def test_legacy_multiline_collision_reimport_two_rollovers(identical):
    first = ("Replace actuator\nRetain wiring", "Pending")
    second = first if identical else ("Inspect damper\nRetain bracket", "Declined")
    prior = table_draft(("Scope", "Status"), (first, second))
    saved = legacy_rows(prior)
    current = new_month_draft(replace(prior, follow_ups=saved), ReportPeriod(2026, 10))
    assert len(current.follow_ups) == 2
    assert len({item.key for item in current.follow_ups}) == 2
    assert [(x.text, x.status) for x in current.follow_ups] == [(x.text, x.status) for x in saved]
    for period in (ReportPeriod(2026, 11), ReportPeriod(2026, 12)):
        following = new_month_draft(replace(current, blocks=prior.blocks), period)
        assert [(x.key, x.text, x.status) for x in following.follow_ups] == [
            (x.key, x.text, x.status) for x in current.follow_ups]
        current = following


@pytest.mark.parametrize("saved_index", [0, 1])
def test_exact_saved_key_reserves_its_own_multiline_occurrence(saved_index):
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),) * 2)
    rows = seed_followups(prior)
    saved = replace(rows[saved_index], text="Manually corrected scope", status="on_hold")
    current = seed_followups(replace(prior, follow_ups=(saved,)))
    assert len(current) == 2
    assert current[0].text == saved.text and current[0].status == "on_hold"
    assert current[1].key == rows[1 - saved_index].key
    assert "\n" in current[1].text


def test_legacy_occurrence_cannot_consume_two_literal_candidates():
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),) * 2)
    saved = legacy_rows(prior)[0]
    current = seed_followups(replace(prior, follow_ups=(saved,)))
    assert len(current) == 2
    assert current[0].text == saved.text
    assert current[1].text == "Scope: Replace actuator\nRetain wiring"


def test_distinct_decisions_and_saved_manual_decision_remain_distinct():
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),
                                             ("Replace actuator\nRetain wiring", "Declined")))
    saved = legacy_rows(prior)
    saved = (replace(saved[0], status="on_hold"), saved[1])
    current = seed_followups(replace(prior, follow_ups=saved))
    assert len(current) == 2
    assert [x.status for x in current] == ["on_hold", "declined"]


def test_literal_match_has_priority_over_earlier_legacy_alias():
    # The first row's old spelling happens to equal the second's literal text.
    # A saved second row must not hide the first distinct physical source row.
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),
                                             ("Replace actuator; Retain wiring", "Declined")))
    rows = seed_followups(prior)
    saved = replace(rows[1], key="legacy-second")
    current = seed_followups(replace(prior, follow_ups=(saved,)))
    assert len(current) == 2
    assert current[0].status == "declined"
    assert current[1].key == rows[0].key and current[1].status == "pending"
    assert "\n" in current[1].text


def test_exact_source_identity_wins_over_legacy_alias_even_after_manual_edit():
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),
                                             ("Other scope", "Declined")))
    rows = seed_followups(prior)
    # The identified second row was edited to equal the first's legacy text.
    saved = replace(rows[1], text="Scope: Replace actuator; Retain wiring", status="on_hold")
    current = seed_followups(replace(prior, follow_ups=(saved,)))
    assert len(current) == 2
    assert current[0].key == saved.key and current[0].status == "on_hold"
    assert current[1].key == rows[0].key and "\n" in current[1].text


def test_legacy_reimport_plain_word_keeps_saved_decisions_without_duplicate(tmp_path):
    from io import BytesIO
    from docx import Document
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_followups import confirmation, report_text
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),
                                             ("Inspect damper\nRetain bracket", "Declined")))
    saved = legacy_rows(prior)
    saved = (replace(saved[0], status="on_hold"), saved[1])
    current = new_month_draft(replace(prior, follow_ups=saved), ReportPeriod(2026, 10))
    current = replace(current, follow_ups=tuple(replace(item,
        reviewed_fingerprint=confirmation(item, current.period)) for item in current.follow_ups))
    raw = assemble_docx(current, acknowledged_fingerprint=current.fingerprint)
    text = "\n".join(p.text for p in Document(BytesIO(raw)).paragraphs)
    for item in current.follow_ups:
        assert text.count(report_text(item)) == 1
    assert len(current.follow_ups) == 2
    (tmp_path / "legacy-proposals.docx").write_bytes(raw)


@pytest.mark.parametrize("saved_index", [0, 1])
def test_one_legacy_row_with_equal_wording_prefers_its_existing_decision(saved_index):
    prior = table_draft(("Scope", "Status"), (("Replace actuator\nRetain wiring", "Pending"),
                                             ("Replace actuator\nRetain wiring", "Declined")))
    original = seed_followups(prior)
    saved = legacy_rows(prior)[saved_index]
    current = seed_followups(replace(prior, follow_ups=(saved,)))
    assert len(current) == 2
    assert current[0].status == saved.status
    assert current[1].key == original[1 - saved_index].key
    assert {x.status for x in current} == {"pending", "declined"}
