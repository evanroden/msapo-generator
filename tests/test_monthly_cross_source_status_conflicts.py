"""A56 deterministic cross-document work-order reconciliation (synthetic only).

No real documents or paid AI. Published rows are a report-only projection;
original source bytes, rejected claims and historic reviews remain immutable.
Refs #270 #277 #280 #287.
"""
from dataclasses import asdict, replace
import json

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_cross_source_conflicts import claim, compare
from app.monthly_report_model import ReportPeriod
from tests.test_monthly_report_work_order_review_flow import (
    PROFILE, PERIOD, CSV, draft_source, stored, publish, storage,
)


def joined(draft, raw, name):
    content, _ = sources.ingest(PROFILE, name, raw)
    result = replace(draft, sources=(*draft.sources, content.source))
    return (*stored(result, content), content)


def work_block(draft):
    return next(b for b in draft.blocks if b.key == "work_orders")


def row_statuses(draft):
    return [(row[0], row[1], row[4])
            for table in work_block(draft).extra_tables
            if table.columns[:2] == ("Work order", "Site")
            for row in table.rows]


def test_valid_two_source_duplicate_is_not_a_second_completed_work_order(storage):
    draft, first_source = draft_source()
    draft, first = stored(draft, first_source)
    accepted = publish(draft, first)
    combined, newer, second = joined(accepted, CSV + b"\n", "vendor-repeated.csv")
    candidates = flow.cross_source_candidates(combined, newer)
    assert len(candidates) == 2
    assert {c.kind for c in candidates} == {"duplicate"}
    assert all(c.existing.source_sha256 != c.incoming.source_sha256 for c in candidates)
    result = publish(combined, newer)
    assert work_block(result) is work_block(combined)  # no approval/content reset
    assert row_statuses(result) == [("0001", "north", "Open"), ("0002", "south", "Completed")]
    assert len(row_statuses(result)) == 2
    saved = flow.saved_bundle(result, second.source.id, "workorders")
    assert not saved["published"]
    assert len(saved["cross_source_receipts"]) == 2
    assert {r["winner"] for r in saved["cross_source_receipts"]} == {"existing"}
    assert sources.source_bytes(PROFILE, first_source.source) == CSV
    assert sources.source_bytes(PROFILE, second.source) == CSV + b"\n"
    again = publish(result, saved)
    assert again == result


def test_conflicting_open_and_closed_status_needs_one_recorded_choice(storage):
    draft, first_source = draft_source()
    draft, initial = stored(draft, first_source)
    accepted = publish(draft, initial)
    newer_csv = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                            b"0001,North,2026-09-03,Closed,PM")
    combined, review, second = joined(accepted, newer_csv, "vendor-updated.csv")
    candidates = flow.cross_source_candidates(combined, review)
    assert len(candidates) == 2
    conflict = next(c for c in candidates if c.kind == "conflict")
    duplicate = next(c for c in candidates if c.kind == "duplicate")
    assert (conflict.existing.status, conflict.incoming.status) == ("Open", "Completed")
    assert conflict.existing.source_id == first_source.source.id
    assert conflict.incoming.source_id == second.source.id
    assert conflict.existing.original_cells[3] == "Open"
    assert conflict.incoming.original_cells[3] == "Closed"
    assert duplicate.existing.site == "south"
    with pytest.raises(ValueError, match="Two sources disagree"):
        publish(combined, review)
    # One choice leaves the first source authoritative and keeps both original rows.
    chosen = flow.record_cross_source_decision(
        combined, review, conflict.binding, "existing", expected_revision=flow.revision(review))
    saved = flow.saved_bundle(chosen, second.source.id, "workorders")
    result = publish(chosen, saved)
    assert work_block(result) == work_block(accepted)
    assert row_statuses(result) == row_statuses(accepted)
    assert len(flow.saved_bundle(result, second.source.id, "workorders")["cross_source_receipts"]) == 2
    assert sources.source_bytes(PROFILE, second.source) == newer_csv


def test_one_incoming_choice_rebuilds_old_counts_and_keeps_unrelated_site(storage):
    draft, first_source = draft_source()
    draft, initial = stored(draft, first_source)
    accepted = publish(draft, initial)
    raw = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                      b"0001,North,2026-09-03,Closed,PM")
    combined, review, second = joined(accepted, raw, "current-cmms.csv")
    conflict = next(c for c in flow.cross_source_candidates(combined, review)
                    if c.kind == "conflict")
    chosen = flow.record_cross_source_decision(
        combined, review, conflict.binding, "incoming",
        expected_revision=flow.revision(review))
    current = flow.saved_bundle(chosen, second.source.id, "workorders")
    result = publish(chosen, current)
    assert sorted(row_statuses(result)) == [
        ("0001", "north", "Completed"), ("0002", "south", "Completed")]
    assert len(row_statuses(result)) == 2
    old_bundle = flow.saved_bundle(result, first_source.source.id, "workorders")
    assert len(old_bundle["published"]) == 2
    assert old_bundle["cross_source_superseded"][0]["source"] == second.source.id
    assert old_bundle["groups"][0]["record"] == initial["groups"][0]["record"]
    assert work_block(result).text == work_block(accepted).text
    # The original raw claim remains for reversal/audit and no standing record is touched.
    assert sources.source_bytes(PROFILE, first_source.source) == CSV
    assert sources.source_bytes(PROFILE, second.source) == raw
    assert row_statuses(publish(result, flow.saved_bundle(result, second.source.id, "workorders"))) == row_statuses(result)


def test_decision_persists_across_snapshot_reload_without_rewriting_old_claim(storage):
    previous = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                           b"0001,North,2026-09-03,Closed,PM")
    draft, first_source = draft_source(previous, "prior-review.csv")
    draft, first = stored(draft, first_source)
    accepted = publish(draft, first)
    newer = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                        b"0001,North,2026-09-03,Pending,PM")
    combined, review, second = joined(accepted, newer, "scheduled-export.csv")
    conflict = next(c for c in flow.cross_source_candidates(combined, review)
                    if c.kind == "conflict")
    chosen = flow.record_cross_source_decision(
        combined, review, conflict.binding, "incoming",
        expected_revision=flow.revision(review))
    result = publish(chosen, flow.saved_bundle(chosen, second.source.id, "workorders"))
    assert ("0001", "north", "Open") in row_statuses(result)
    # Scheduled/pending is never fabricated into completed work.
    summary = [table for table in work_block(result).extra_tables
               if any("Recorded completed" in col for col in table.columns)]
    assert summary
    assert sum(int(table.rows[0][-2]) for table in summary) == 1
    library.save_profile(PROFILE, expected_revision=0, actor="Synthetic Reviewer", confirmed=True)
    library.save_snapshot(result, expected_revision=0)
    restored = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    assert restored == result
    history = flow.saved_bundle(restored, second.source.id, "workorders")
    assert history["cross_source_decisions"][-1] == {
        "binding": conflict.binding, "winner": "incoming"}
    assert row_statuses(restored) == row_statuses(result)


def test_changed_status_source_date_site_and_period_never_reuse_old_choice(storage):
    draft, first_source = draft_source()
    draft, first = stored(draft, first_source)
    accepted = publish(draft, first)
    raw = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                      b"0001,North,2026-09-03,Closed,PM")
    combined, review, second = joined(accepted, raw, "changed.csv")
    conflict = next(c for c in flow.cross_source_candidates(combined, review)
                    if c.kind == "conflict")
    chosen = flow.record_cross_source_decision(
        combined, review, conflict.binding, "existing",
        expected_revision=flow.revision(review))
    saved = flow.saved_bundle(chosen, second.source.id, "workorders")
    changed = flow.change_row(saved, 0, flow.restored_group(saved, saved["groups"][0]).rows[0].key,
                              {"work_date": "2026-09-06"})
    changed_draft = flow.store_bundle(chosen, changed, expected_revision=flow.revision(saved))
    current = flow.saved_bundle(changed_draft, second.source.id, "workorders")
    with pytest.raises(ValueError, match="Two sources disagree"):
        publish(changed_draft, current)
    assert current["cross_source_decisions"][0]["binding"] == conflict.binding
    assert all(c.binding != conflict.binding for c in flow.cross_source_candidates(changed_draft, current)
               if c.kind == "conflict")
    altered_old = replace(first_source.source, vendor="New source revision")
    source_changed = replace(chosen, sources=(altered_old, second.source))
    with pytest.raises(ValueError, match="changed or removed"):
        flow.cross_source_candidates(source_changed, saved)
    separate_period = replace(combined, period=ReportPeriod(2026, 10))
    new_review = flow.prepare_bundle(separate_period, second, kind="workorders")
    assert not flow.cross_source_candidates(separate_period, new_review)
    south = CSV.replace(b"0001,North", b"0001,South").splitlines(keepends=True)
    distinct_raw = b"".join(south[:2])
    across_sites, site_review, _ = joined(accepted, distinct_raw, "other-site.csv")
    assert not flow.cross_source_candidates(across_sites, site_review)


def test_missing_or_malformed_choice_never_approves_a_conflict(storage):
    draft, first_source = draft_source()
    draft, first = stored(draft, first_source)
    accepted = publish(draft, first)
    raw = CSV.replace(b"0001,North,2026-09-03,Open,PM",
                      b"0001,North,2026-09-03,Closed,PM")
    combined, review, _ = joined(accepted, raw, "third.csv")
    candidate = next(c for c in flow.cross_source_candidates(combined, review)
                     if c.kind == "conflict")
    with pytest.raises(ValueError, match="changed"):
        flow.record_cross_source_decision(combined, review, "0" * 64, "incoming",
                                          expected_revision=flow.revision(review))
    with pytest.raises(ValueError, match="changed"):
        flow.record_cross_source_decision(combined, review, candidate.binding, "completed",
                                          expected_revision=flow.revision(review))
    with pytest.raises(ValueError):
        flow.decoded(json.dumps({**review, "cross_source_decisions": [
            {"binding": candidate.binding, "winner": "automatically completed"}]}))
    incoming_claim = candidate.incoming
    assert compare(incoming_claim, incoming_claim, report_scope=flow.scope(combined)) is None
    assert compare(replace(incoming_claim, site=""), candidate.existing,
                   report_scope=flow.scope(combined)) is None
    assert compare(replace(incoming_claim, work_order=""), candidate.existing,
                   report_scope=flow.scope(combined)) is None
