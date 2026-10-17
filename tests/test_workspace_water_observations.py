"""Water QA receipts must be read-only, scoped, and distinct from expected input."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from scripts.workspace_water_observations import water_state, emit_water_snapshot


def test_absent_and_empty_water_do_not_claim_included_pages():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    absent = water_state(replace(draft, blocks=()))
    empty = water_state(replace(draft, blocks=(ResolvedBlock("water_reports", "This month"),)))
    assert absent == empty
    assert absent["pages"] == [] and absent["sources"] == [] and absent["pending"] == []


def test_water_receipt_preserves_order_and_does_not_expose_caption():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    sid = "a" * 64
    assets = ("b" * 64 + ".png", "c" * 64 + ".png")
    references = (sid + ":2:" + "d" * 64, sid + ":1:" + "e" * 64)
    block = ResolvedBlock("water_reports", "This month", asset_hashes=assets,
        asset_captions=("Synthetic second page", "Synthetic first page"), references=references,
        asset_provenance=tuple((asset, (ref,)) for asset, ref in zip(assets, references)))
    draft = replace(draft, blocks=(block,))
    before = draft.fingerprint
    result = water_state(draft)
    assert [p["source_pages"][0][1] for p in result["pages"]] == [2, 1]
    assert result["pending"] == [0, 1]
    assert result["pages"][0]["caption_sha256"] == sha256(b"Synthetic second page").hexdigest()
    assert "Synthetic second page" not in json.dumps(result)
    assert draft.fingerprint == before


def test_unmarked_and_nonisolated_water_observers_refuse_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EPC_MONTHLY_DOM_FIXTURE", raising=False)
    with pytest.raises(ValueError, match="marked disposable"):
        emit_water_snapshot(tmp_path, "0" * 32)
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    from app import monthly_report_testing
    monkeypatch.setattr(monthly_report_testing, "scope", lambda: None)
    with pytest.raises(ValueError, match="server-isolated"):
        emit_water_snapshot(tmp_path, "0" * 32)


def test_unrelated_block_correction_changes_receipt_without_changing_water():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    water = ResolvedBlock("water_reports", "This month")
    first = replace(draft, blocks=(water, ResolvedBlock("activity_summary", "This month", text="first")))
    second = replace(first, blocks=(water, replace(first.blocks[1], text="manual correction")))
    a, b = water_state(first), water_state(second)
    assert a["unrelated_sha256"] != b["unrelated_sha256"]
    assert a["pages"] == b["pages"] == []
