"""Specific old-period wording decisions never waive unrelated safety checks."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from app.monthly_report_checks import preflight
from app.monthly_report_docx import assemble_docx
from app.monthly_report_library import block_from_dict, save_snapshot, load_snapshot
from app.monthly_report_model import BlockSpec, ReportDraft, ReportPeriod, ReportSource, ResolvedBlock, SectionSpec, synthetic_profiles
from app.monthly_report_period_items import (
    HISTORICAL, apply_exclusions, historical_allowed, is_historical, item_sources,
    pending_items, resolve_item, restore_excluded,
)
from app.monthly_report_setup import merge_blocks
from app.monthly_report_sources import source_reference

OCTOBER = ReportPeriod(2026, 10)
OLD = "Inspected the synthetic pump on September 16, 2026."
SECOND = "Replaced a synthetic belt on September 20, 2026."
CURRENT = "October 2, 2026: current synthetic work."


def sample(text=OLD, key="activity_summary"):
    source = ReportSource("synthetic-source", "Synthetic vendor report.txt", "a" * 64, ".txt",
                          page_texts=(OLD, SECOND), selected_pages=(1, 2))
    block = ResolvedBlock(key, "This month", text=text, references=(source_reference(source, 1), source_reference(source, 2)))
    section = SectionSpec("activity", "2", "Activity", (BlockSpec(key, "rich_text"),))
    return ReportDraft(synthetic_profiles()[0], OCTOBER, "Synthetic reviewer", (section,), (block,), sources=(source,))


def resolve(draft, index=0, action="historical"):
    block = draft.blocks[0]
    return replace(draft, blocks=(resolve_item(block, draft.period, index, action,
                    expected_fingerprint=block.fingerprint, sources=draft.sources),))


def test_one_item_is_labeled_in_actual_docx_and_other_dates_remain_reviewable():
    draft = sample(OLD + "\n" + SECOND + "\n" + CURRENT)
    first, second = pending_items(draft.blocks[0], OCTOBER, draft.sources)
    assert item_sources(draft.blocks[0], first, draft.sources) == ("Synthetic vendor report.txt · page/item 1",)
    assert item_sources(draft.blocks[0], second, draft.sources) == ("Synthetic vendor report.txt · page/item 2",)
    updated = resolve(draft)
    assert updated.sources == draft.sources
    assert updated.blocks[0].fingerprint != draft.blocks[0].fingerprint
    assert updated.blocks[0].text == HISTORICAL + OLD + "\n" + SECOND + "\n" + CURRENT
    checks = [check for check in preflight(updated) if check.code == "period"]
    assert len(checks) == 1 and "September 20, 2026" in checks[0].message
    assert "September 16, 2026" not in checks[0].message
    document = Document(BytesIO(assemble_docx(updated, acknowledged_fingerprint=updated.fingerprint)))
    text = "\n".join(p.text for p in document.paragraphs)
    assert HISTORICAL + OLD in text
    assert SECOND in text and CURRENT in text
    assert text.count(OLD) == 1
    assert draft.blocks[0].text.startswith(OLD)  # Historical input remains unchanged.


def test_historical_receipt_is_exact_wording_target_and_current_source_bound():
    updated = resolve(sample())
    block = updated.blocks[0]
    assert not pending_items(block, OCTOBER, updated.sources)
    changed = replace(block, text=block.text.replace("pump", "generator"))
    assert pending_items(changed, OCTOBER, updated.sources)
    assert pending_items(block, ReportPeriod(2026, 11), updated.sources)
    altered_source = replace(updated.sources[0], service_date="2026-09-17")
    assert pending_items(block, OCTOBER, (altered_source,))
    assert not is_historical(replace(block, references=()), block.text, OCTOBER)
    assert pending_items(replace(block, references=("period-item:v1:invalid!",)), OCTOBER)
    with pytest.raises(ValueError, match="wording changed"):
        resolve_item(changed, OCTOBER, 0, "historical", expected_fingerprint=block.fingerprint, sources=updated.sources)


@pytest.mark.parametrize("text", [
    "Completed synthetic work on November 1, 2026.",
    "Completed synthetic work on 2026-02-31.",
    "September 16, 2026: synthetic replacement cost $240.",
    "September 16, 2026 work. Completed another task November 1, 2026.",
    "September 16, 2026 work. Planned follow-up November 1, 2026.",
    "September 16, 2026 work and October 2, 2026 work.",
    "Completed synthetic work September 99, 2026.",
])
def test_historical_action_cannot_relabel_future_invalid_or_priced_facts(text):
    draft = sample(text)
    assert not historical_allowed(text, OCTOBER)
    with pytest.raises(ValueError, match="invalid, future or priced"):
        resolve(draft)
    if "$" in text:
        assert any(c.code == "pricing" and c.blocking for c in preflight(draft))


def test_other_representations_and_hard_carried_gate_remain_independent():
    draft = resolve(sample())
    # An identical cell or caption is not the acknowledged narrative item.
    block = replace(draft.blocks[0], rows=((draft.blocks[0].text,),), asset_captions=(draft.blocks[0].text,))
    assert any(c.code == "period" for c in preflight(replace(draft, blocks=(block,))))
    ai_block = replace(block, ai_written=True)
    assert not pending_items(ai_block, OCTOBER, draft.sources)
    assert any(c.code == "period" for c in preflight(replace(draft, blocks=(ai_block,))))
    carried = sample(key="utility_analysis")
    carried = replace(carried, blocks=(replace(carried.blocks[0], references=(*carried.blocks[0].references, "report-period:2026-09")),))
    carried = resolve(carried)
    assert any(c.code == "carried_period" and c.blocking for c in preflight(carried))


def test_report_only_exclusion_survives_storage_merge_and_has_explicit_restore(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = sample(OLD + "\n" + CURRENT)
    snapshot = save_snapshot(original, expected_revision=0, entered_editor="Synthetic reviewer")
    updated = resolve(original, action="exclude")
    assert updated.sources == original.sources
    excluded = block_from_dict(asdict(updated.blocks[0]))
    assert excluded.text == CURRENT
    incoming = replace(original.blocks[0], text=OLD + "\nNew independent manual fact.")
    merged = merge_blocks(excluded, incoming)
    merged_draft = replace(updated, blocks=(merged,))
    assert any(c.code == "period_removed" and c.blocking for c in preflight(merged_draft))
    reconciled = apply_exclusions(merged, OCTOBER)
    assert OLD not in reconciled.text and CURRENT in reconciled.text and "New independent manual fact." in reconciled.text
    assert not any(c.code == "period_removed" for c in preflight(replace(updated, blocks=(reconciled,))))
    restored = restore_excluded(reconciled, OCTOBER, OLD, expected_fingerprint=reconciled.fingerprint)
    assert restored.text.count(OLD) == 1
    assert apply_exclusions(restored, OCTOBER) == restored
    assert any(c.code == "period" for c in preflight(replace(updated, blocks=(restored,))))
    # October-only suppression cannot silently omit November's imported item.
    assert OLD in apply_exclusions(merged, ReportPeriod(2026, 11)).text
    assert load_snapshot(original.profile.contract, original.profile.key, original.period) == snapshot


def test_duplicate_items_are_removed_one_at_a_time_and_pictures_keep_approval():
    from app.monthly_report_asset_review import approve_all_assets, pending_asset_indexes
    draft = sample(OLD + "\n" + OLD)
    block = replace(draft.blocks[0], asset_hashes=("synthetic-image",), asset_captions=("Synthetic caption",))
    block = approve_all_assets(block)
    draft = replace(draft, blocks=(block,))
    updated = resolve(draft, action="exclude")
    assert updated.blocks[0].text.count(OLD) == 1
    assert len(pending_items(updated.blocks[0], OCTOBER, updated.sources)) == 1
    assert pending_asset_indexes(updated.blocks[0]) == ()
    second = resolve(updated, action="exclude")
    assert not second.blocks[0].text.strip()
    merged = merge_blocks(second.blocks[0], draft.blocks[0])
    assert not apply_exclusions(merged, OCTOBER).text.strip()
    historical = resolve(replace(draft, blocks=(replace(block, text=OLD),)))
    assert pending_asset_indexes(historical.blocks[0]) == ()


APP = '''
import streamlit as st
from app.monthly_report_period_items_ui import render_period_items
from app.monthly_report_model import ReportPeriod
st.session_state["block"] = render_period_items(st.session_state["block"],ReportPeriod(2026,10),st.session_state["sources"],
    "fixture",section_title="Activity",editor_anchor="report-block-activity_summary")
'''


def test_inline_controls_name_item_source_and_apply_only_clicked_choice():
    draft = sample(OLD + "\n" + SECOND)
    app = AppTest.from_string(APP)
    app.session_state["block"] = draft.blocks[0]
    app.session_state["sources"] = draft.sources
    app.run()
    assert not app.exception and app.session_state["block"] == draft.blocks[0]
    assert any("Synthetic vendor report.txt · page/item 1" in c.value for c in app.caption)
    assert any("#report-block-activity_summary" in m.value for m in app.markdown)
    next(button for button in app.button if button.label == "Retain as historical context").click().run()
    app.run()
    assert not app.exception
    assert app.session_state["block"].text == HISTORICAL + OLD + "\n" + SECOND
    next(button for button in app.button if button.label == "Exclude this item from this report").click().run()
    app.run()
    assert app.session_state["block"].text.strip() == HISTORICAL + OLD
    next(button for button in app.button if button.label == "Restore this wording").click().run()
    app.run()
    assert SECOND in app.session_state["block"].text
