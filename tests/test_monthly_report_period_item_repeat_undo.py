"""Synthetic report-only period exclusions restore one occurrence per choice."""
from dataclasses import asdict, replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_period_items import (
    PREFIX, apply_exclusions, decisions, exclusions, pending_items,
    resolve_item, restore_excluded,
)
from app.monthly_report_library import block_from_dict, load_snapshot, save_snapshot


PERIOD = ReportPeriod(2026, 10)
NEXT = ReportPeriod(2026, 11)
OLD = "Inspected synthetic pump on September 16, 2026."
OTHER = "Replaced synthetic belt on September 20, 2026."
CURRENT = "Current October work completed."


def block_with(text):
    return ResolvedBlock("activity_summary", "This month", text=text)


def leave_out(block, *, index=0):
    return resolve_item(block, PERIOD, index, "exclude",
                        expected_fingerprint=block.fingerprint)


def restore(block, *, text=OLD):
    return restore_excluded(block, PERIOD, text, expected_fingerprint=block.fingerprint)


def receipts(block):
    return tuple(ref for ref in block.references if ref.startswith(PREFIX))


def repeatedly_excluded(count=2):
    block = block_with("\n".join((OLD,) * count))
    for _ in range(count):
        block = leave_out(block)
    assert block.text == ""
    assert len(receipts(block)) == count
    assert tuple(v["remaining"] for v in decisions(block, PERIOD)) == tuple(range(count - 1, -1, -1))
    return block


@pytest.mark.parametrize("count", [2, 3, 4])
def test_restore_each_omitted_duplicate_without_discarding_earlier_receipts(count):
    original = repeatedly_excluded(count)
    current = original
    for expected in range(1, count + 1):
        current = restore(current)
        assert current.text.splitlines() == [OLD] * expected
        assert len(receipts(current)) == count - expected
        if expected < count:
            assert exclusions(current, PERIOD)[0]["remaining"] == expected
        assert apply_exclusions(current, PERIOD) == current
    assert exclusions(current, PERIOD) == ()
    assert original.text == "" and len(receipts(original)) == count
    assert len(pending_items(current, PERIOD)) == count


def test_partial_restore_keeps_other_removed_occurrence_out_after_reimport():
    original = repeatedly_excluded()
    once = restore(original)
    # The same source block returns two literal lines after import/merge.
    replayed = replace(once, text=OLD + "\n" + OLD)
    reconciled = apply_exclusions(replayed, PERIOD)
    # Removing the second occurrence must preserve the first line's original newline.
    assert reconciled.text == OLD + "\n"
    assert len(receipts(reconciled)) == 1
    assert exclusions(reconciled, PERIOD)[0]["remaining"] == 1
    assert restore(reconciled).text == OLD + "\n" + OLD
    assert apply_exclusions(replayed, NEXT).text == OLD + "\n" + OLD


def test_unrelated_dated_exclusion_and_regular_source_references_are_preserved():
    start = block_with(OLD + "\n" + OTHER + "\n" + OLD + "\n" + CURRENT)
    start = replace(start, references=("original-source:1:fingerprint",))
    first = leave_out(start, index=0)
    second = leave_out(first, index=1)
    third = leave_out(second, index=0)
    assert third.text == CURRENT
    assert len(receipts(third)) == 3
    partial = restore(third)
    assert partial.text == CURRENT + "\n" + OLD
    assert exclusions(partial, PERIOD)[0]["text"] == OLD
    assert exclusions(partial, PERIOD)[0]["remaining"] == 1
    assert any(v["text"] == OTHER for v in exclusions(partial, PERIOD))
    assert "original-source:1:fingerprint" in partial.references
    remaining = restore(partial)
    assert OLD in remaining.text and len(receipts(remaining)) == 1
    assert restore(remaining, text=OTHER).text.endswith(OTHER)
    assert not receipts(restore(remaining, text=OTHER))


def test_current_block_hash_is_required_before_undo():
    twice = repeatedly_excluded()
    changed = replace(twice, text=CURRENT)
    with pytest.raises(ValueError, match="wording changed"):
        restore_excluded(changed, PERIOD, OLD, expected_fingerprint=twice.fingerprint)
    assert len(receipts(twice)) == 2
    with pytest.raises(ValueError, match="not excluded"):
        restore_excluded(twice, PERIOD, "unrelated old item", expected_fingerprint=twice.fingerprint)


def test_saved_and_reopened_pending_removals_keep_individual_undo(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    pending = repeatedly_excluded()
    section = SectionSpec("activity", "2", "Activity",
                          (BlockSpec("activity_summary", "rich_text"),))
    draft = ReportDraft(synthetic_profiles()[0], PERIOD, "Synthetic reviewer",
                        (section,), (pending,))
    first = save_snapshot(draft, expected_revision=0,
                          entered_editor="Synthetic reviewer")
    loaded = load_snapshot(draft.profile.contract, draft.profile.key, PERIOD)
    assert first == loaded
    original = block_from_dict(asdict(loaded.draft.blocks[0]))
    assert original == pending
    once = restore(original)
    assert len(receipts(once)) == 1
    assert once.text == OLD
    assert restore(block_from_dict(asdict(once))).text == OLD + "\n" + OLD
    assert load_snapshot(draft.profile.contract, draft.profile.key, PERIOD) == first


UI = """
import streamlit as st
from app.monthly_report_period_items_ui import render_period_items
from app.monthly_report_model import ReportPeriod
st.session_state["block"] = render_period_items(
    st.session_state["block"], ReportPeriod(2026, 10), (),
    "repeat-undo", section_title="Activity", editor_anchor="report-block-activity_summary")
"""


def test_actual_period_cards_offer_two_separate_restore_actions():
    app = AppTest.from_string(UI, default_timeout=30)
    app.session_state["block"] = block_with(OLD + "\n" + OLD)
    app.run()
    assert not app.exception
    for n in (1, 2):
        next(button for button in app.button if button.label == "Leave out").click().run()
        app.run()
        assert not app.exception
        assert app.session_state["block"].text.count(OLD) == 2 - n
    assert len(receipts(app.session_state["block"])) == 2
    for n in (1, 2):
        next(button for button in app.button if button.label == "Restore this wording").click().run()
        app.run()
        assert not app.exception
        assert app.session_state["block"].text.count(OLD) == n
        assert len(receipts(app.session_state["block"])) == 2 - n
