"""Synthetic receipt helpers must not invent saved values or touch live data."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from app.monthly_report_model import (
    ReportFollowUp, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles,
)
from scripts.workspace_text_observations import emit_text_snapshot, text_hashes


def test_missing_and_intentionally_empty_text_have_different_receipts():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    missing = text_hashes(replace(draft, blocks=(), follow_ups=()))
    empty = text_hashes(replace(draft,
        blocks=(ResolvedBlock('training_summary', 'This month', text=''),),
        follow_ups=(ReportFollowUp('synthetic', 'issue', '', '2026-09'),)))
    assert missing == {'training': None, 'issues': []}
    assert empty == {'training': sha256(b'').hexdigest(), 'issues': [sha256(b'').hexdigest()]}


def test_receipts_are_hashes_and_do_not_expose_invented_source_text():
    value = 'Synthetic-only receipt test wording'
    draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
        blocks=(ResolvedBlock('training_summary', 'This month', text=value),),
        follow_ups=(ReportFollowUp('synthetic', 'issue', value, '2026-09'),))
    before = draft.fingerprint
    receipt = text_hashes(draft)
    assert receipt == {'training': sha256(value.encode()).hexdigest(), 'issues': [sha256(value.encode()).hexdigest()]}
    assert value not in json.dumps(receipt)
    assert draft.fingerprint == before


def test_unmarked_or_nonisolated_roots_reject_receipt_reads(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('EPC_MONTHLY_DOM_FIXTURE', raising=False)
    with pytest.raises(ValueError, match='marked disposable'):
        emit_text_snapshot(tmp_path, '0' * 32)
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    (tmp_path / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    from app import monthly_report_testing
    monkeypatch.setattr(monthly_report_testing, 'scope', lambda: None)
    with pytest.raises(ValueError, match='server-isolated'):
        emit_text_snapshot(tmp_path, '0' * 32)
