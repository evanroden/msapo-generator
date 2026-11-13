"""Coverage receipts persist with the existing single-source work-order workspace."""
from dataclasses import replace
from datetime import date

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, default_sections,
)
from app.monthly_report_work_order_coverage import (
    restore_decision, summarize_coverage, month_window,
)


def make_profile(contract):
    return ReportProfile(contract, "regional-example", "Two example facilities", (
        Facility("alpha", "Example Alpha", ("Alpha",)),
        Facility("beta", "Example Beta", ("Beta",))), scope_type="multi_site")


def make_draft(profile, name="export.csv", raw=None):
    if raw is None:
        raw = (b"Work Order #,Facility,Received Date,Status,PM/Non-PM\n"
               b"Wo-8,Alpha,2026-09-07,Closed,PM\n"
               b"WO-8,Beta,2026-09-09,Complete,Repair\n")
    content, _ = sources.ingest(profile, name, raw)
    draft = ReportDraft(profile, ReportPeriod(2026, 9), "Synthetic AM", default_sections(), (
        ResolvedBlock("work_orders", "This month"),), synthetic=True,
        sources=(content.source,))
    return draft, content


def test_two_contracts_same_identifiers_are_scoped_and_saved(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    saved = []
    for contract in ("Example Contract A", "Example Contract B"):
        profile = make_profile(contract)
        draft, content = make_draft(profile)
        original = flow.prepare_bundle(draft, content)
        normalized = flow.restored_group(original, original["groups"][0])
        assert normalized.mapping.work_date == 2
        assert normalized.rows[0].work_order == "Wo-8"
        assert normalized.rows[1].work_order == "WO-8"
        assert normalized.rows[0].site == "alpha" and normalized.rows[1].site == "beta"
        assert not normalized.questions
        reviewed = flow.confirm_coverage(draft, original, table_number=1, site="alpha",
            start_month="2026-01", end_month="2026-09",
            evidence="AM compared export-period settings to the saved export", confirmed=True)
        decisions = tuple(restore_decision(d) for d in reviewed["coverage"])
        measures = summarize_coverage(normalized, decisions, contract=contract,
            profile_key=profile.key, site="alpha", months=month_window("2026-09"),
            as_of=date(2026, 11, 12))
        assert [m.total for m in measures[-3:]] == [0, 0, 1]
        assert measures[0].total is None  # October 2025 is not covered.
        stored = flow.store_bundle(draft, reviewed)
        library.save_profile(profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
        library.save_snapshot(stored, expected_revision=0)
        reopened = library.load_snapshot(profile.contract, profile.key, draft.period).draft
        assert flow.saved_bundle(reopened, content.source.id, "workorders") == reviewed
        saved.append((stored, reviewed))
    with pytest.raises(ValueError, match="different contract"):
        left, _ = saved[0]
        right = tuple(restore_decision(d) for d in saved[1][1]["coverage"])
        old = flow.restored_group(saved[0][1], saved[0][1]["groups"][0])
        summarize_coverage(old, right, contract=left.profile.contract,
            profile_key=left.profile.key, site="alpha", months=("2026-09",),
            as_of=date(2026, 11, 12))


def test_coverage_attestation_requires_explicit_am_and_single_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, content = make_draft(make_profile("Example-Three"))
    bundle = flow.prepare_bundle(draft, content)
    opts = dict(table_number=1, site="alpha", start_month="2026-09",
                end_month="2026-09", evidence="AM inspected export settings")
    with pytest.raises(ValueError, match="Confirm"):
        flow.confirm_coverage(draft, bundle, **opts, confirmed=False)
    with pytest.raises(ValueError, match="Confirm"):
        flow.confirm_coverage(draft, bundle, **{**opts, "table_number": 2}, confirmed=True)
    with pytest.raises(ValueError, match="Coverage"):
        flow.confirm_coverage(draft, bundle, **{**opts, "start_month": "2026-10"}, confirmed=True)
    accepted = flow.confirm_coverage(draft, bundle, **opts, confirmed=True)
    assert len(accepted["coverage"]) == 1
    assert flow.confirm_coverage(draft, accepted, **opts, confirmed=True) == accepted
    removed = flow.revoke_coverage(draft, accepted, site="alpha", table_number=1)
    assert removed["coverage"] == []
    assert removed["groups"] == bundle["groups"]


def test_corrected_review_and_scope_survive_coverage_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft, content = make_draft(make_profile("Example-Four"))
    original = flow.prepare_bundle(draft, content)
    row = flow.restored_group(original, original["groups"][0]).rows[0]
    corrected = flow.change_row(original, 0, row.key, {"status": "Open"})
    verified = flow.confirm_coverage(draft, corrected, table_number=1, site="alpha",
        start_month="2026-09", end_month="2026-09",
        evidence="AM checked saved export parameters", confirmed=True)
    retained = flow.store_bundle(draft, verified)
    saved = flow.saved_bundle(retained, content.source.id, "workorders")
    reopened_row = flow.restored_group(saved, saved["groups"][0]).rows[0]
    assert reopened_row.status == "Open"
    assert reopened_row.origin.cells[3] == "Closed"
    changed_month = replace(retained, period=ReportPeriod(2026, 10))
    with pytest.raises(ValueError, match="different site or reporting month"):
        flow.store_bundle(changed_month, verified)
    altered_source = replace(content.source, vendor="Updated synthetic source")
    with pytest.raises(ValueError, match="source changed"):
        flow.store_bundle(replace(draft, sources=(altered_source,)), verified)


def test_coverage_uses_operator_day_and_falls_back_when_browser_zone_missing(monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace

    from app import config, monthly_report_work_order_review_ui as ui

    class BoundaryClock:
        @classmethod
        def now(cls, timezone):
            if timezone.key == "America/Los_Angeles":
                return datetime(2026, 8, 24, 21, 30, tzinfo=timezone)
            return datetime(2026, 8, 25, 0, 30, tzinfo=timezone)

    monkeypatch.setattr(config, "datetime", BoundaryClock)
    monkeypatch.setattr(config, "EPC_TIMEZONE", "America/New_York")
    monkeypatch.setattr(ui, "st", SimpleNamespace(context=SimpleNamespace(timezone="America/Los_Angeles")))
    assert ui._coverage_as_of() == date(2026, 8, 24)
    monkeypatch.setattr(ui, "st", SimpleNamespace())
    assert ui._coverage_as_of() == date(2026, 8, 25)
