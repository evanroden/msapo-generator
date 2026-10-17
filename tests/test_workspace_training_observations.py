"""Synthetic Training observations preserve distinctions without saving work."""
from dataclasses import replace
from datetime import date

import pytest

from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_training import add_event
from scripts.workspace_training_observations import emit_training_snapshot, training_state


def test_receipt_observes_actual_event_date_hours_and_independent_content():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    table = add_event(None, title="Synthetic session", when=date(2026, 9, 15),
                      mode="Virtual", participants=["Synthetic Person"], hours="", period=draft.period)
    block = ResolvedBlock("training_summary", "This month", text="Synthetic monthly note", extra_tables=(table,))
    draft = replace(draft, blocks=(block, ResolvedBlock("activity", "This month", text="Independent wording")))
    before = draft.fingerprint
    receipt = training_state(draft)
    assert receipt["events"] == [["Synthetic session", "2026-09-15", "Virtual", "Synthetic Person", ""]]
    without = training_state(replace(draft, blocks=(replace(block, extra_tables=()), draft.blocks[1])))
    assert without["events"] == []
    assert {key: value for key, value in receipt.items() if key != "events"} == {
        key: value for key, value in without.items() if key != "events"}
    assert draft.fingerprint == before


def test_unmarked_or_nonisolated_root_cannot_emit_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EPC_MONTHLY_DOM_FIXTURE", raising=False)
    with pytest.raises(ValueError, match="marked disposable"):
        emit_training_snapshot(tmp_path, "0" * 32)
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    from app import monthly_report_testing
    monkeypatch.setattr(monthly_report_testing, "scope", lambda: None)
    with pytest.raises(ValueError, match="server-isolated"):
        emit_training_snapshot(tmp_path, "0" * 32)
