"""The source workspace publishes only confirmed, source-bound grid cells."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library, monthly_report_sources as sources
from app import monthly_report_master_tables as masters
from app import monthly_report_work_order_review_flow as flow
from app.monthly_report_model import (
    Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable, ResolvedBlock,
    default_sections,
)
from app.monthly_report_rolling_workflow import check_binding, publish, remove
from app.monthly_report_work_order_review_ui import apply_request
from app.monthly_report_work_order_rolling import rolling_labels


def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = ReportProfile("Synthetic contract", "grid-workflow", "Two sites", (
        Facility("north", "Example North", ("North",)),
        Facility("south", "Example South", ("South",))), scope_type="multi_site")
    period = ReportPeriod(2027, 1)
    raw = (b"Work Order #,Site,Received Date,Closed Date,Status,PM/Non-PM\n"
           b"N-1,North,2026-12-05,2027-01-03,Closed,Non-PM\n"
           b"S-1,South,2026-12-12,,Open,Non-PM\n")
    content, _ = sources.ingest(profile, "synthetic.csv", raw)
    headings = ("PM Received", "Non-PM Received", "PM Closed", "Non-PM Closed")
    frames = tuple(masters.MasterTable("work_orders", i, f"master-table:test:{i}",
        (heading, *rolling_labels(period)), tuple(range(13)), 13)
        for i, heading in enumerate(headings))
    monkeypatch.setattr(masters, "for_profile", lambda _profile: frames)
    empty = tuple(ReportTable(frame.columns, (), frame.reference) for frame in frames)
    manual = ReportTable(("Manual note",), (("Keep this",),), "manual:test")
    draft = ReportDraft(profile, period, "Synthetic AM", default_sections(),
        (ResolvedBlock("work_orders", "This month", extra_tables=(*empty, manual)),),
        synthetic=True, sources=(content.source,))
    bundle = flow.prepare_bundle(draft, content)
    bundle = flow.confirm_coverage(draft, bundle, table_number=1, site="north",
        start_month="2026-12", end_month="2027-01",
        evidence="Synthetic export range and both event dates checked", confirmed=True)
    return flow.store_bundle(draft, bundle), content, bundle, raw, frames, manual


def apply_grid(draft, bundle, **changes):
    block = next(b for b in draft.blocks if b.key == "work_orders")
    options = dict(expected_revision=flow.revision(bundle), expected_block=block.fingerprint,
        group_index=0, metrics=("non_pm_received", "non_pm_closed"), confirmed=True)
    return publish(draft, bundle, **{**options, **changes})


def test_confirmed_source_reaches_two_site_grids_and_reopens(tmp_path, monkeypatch):
    draft, content, bundle, raw, frames, manual = prepared(tmp_path, monkeypatch)
    result = apply_grid(draft, bundle)
    grid = next(b for b in result.blocks if b.key == "work_orders")
    assert grid.extra_tables[-1] == manual
    pm_received, non_pm_received, pm_closed, non_pm_closed = grid.extra_tables[:4]
    assert non_pm_received.rows[0][-2:] == ("1", "0")
    assert non_pm_closed.rows[0][-2:] == ("0", "1")
    assert all(not value for row in non_pm_received.rows[1:] for value in row[1:])
    assert all(not value for table in (pm_received, pm_closed) for row in table.rows for value in row[1:])
    assert sources.source_bytes(result.profile, content.source) == raw
    assert check_binding(result) is None
    saved = flow.saved_bundle(result, content.source.id, "workorders")
    assert saved["grid_receipt"]["review_revision"] == flow.restored_group(saved, saved["groups"][0]).revision
    assert apply_grid(result, saved) == result
    library.save_profile(result.profile, expected_revision=0, actor="Synthetic AM", confirmed=True)
    library.save_snapshot(result, expected_revision=0)
    reopened = library.load_snapshot(result.profile.contract, result.profile.key, result.period).draft
    assert reopened == result and check_binding(reopened) is None


def test_review_or_coverage_change_blocks_old_grid_until_reapplied(tmp_path, monkeypatch):
    draft, content, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    accepted = apply_grid(draft, bundle)
    saved = flow.saved_bundle(accepted, content.source.id, "workorders")
    row = flow.restored_group(saved, saved["groups"][0]).rows[0]
    changed = flow.change_row(saved, 0, row.key, {"work_date": "2026-11-05"})
    newer = flow.store_bundle(accepted, changed, expected_revision=flow.revision(saved))
    assert check_binding(newer)
    from app.monthly_report_checks import preflight
    assert any(check.code == "work_order_grid_source" and check.blocking for check in preflight(newer))
    refreshed = apply_grid(newer, changed)
    assert check_binding(refreshed) is None
    table = next(b for b in refreshed.blocks if b.key == "work_orders").extra_tables[1]
    assert table.rows[0][-2:] == ("0", "0")
    refreshed_bundle = flow.saved_bundle(refreshed, content.source.id, "workorders")
    revoked = flow.revoke_coverage(refreshed, refreshed_bundle, site="north", table_number=1)
    revoked_draft = flow.store_bundle(refreshed, revoked, expected_revision=flow.revision(refreshed_bundle))
    assert check_binding(revoked_draft)


def test_unconfirmed_or_edited_grid_is_never_overwritten(tmp_path, monkeypatch):
    draft, content, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Confirm"):
        apply_grid(draft, bundle, confirmed=False)
    with pytest.raises(ValueError, match="Choose"):
        apply_grid(draft, bundle, metrics=())
    accepted = apply_grid(draft, bundle)
    saved = flow.saved_bundle(accepted, content.source.id, "workorders")
    block = next(b for b in accepted.blocks if b.key == "work_orders")
    edited_grid = replace(block.extra_tables[1], rows=(("Example North", *("99",) * 12), block.extra_tables[1].rows[1]))
    edited_block = replace(block, extra_tables=(block.extra_tables[0], edited_grid, *block.extra_tables[2:]))
    newer = replace(accepted, blocks=(edited_block,))
    assert check_binding(newer)
    with pytest.raises(ValueError, match="grid values changed"):
        apply_grid(newer, saved)
    assert newer.blocks[0].extra_tables[1] == edited_grid
    with pytest.raises(ValueError, match="table changed"):
        apply_grid(newer, saved, expected_block=block.fingerprint)


def test_ui_action_requires_explicit_metrics_and_current_receipt(tmp_path, monkeypatch):
    draft, content, bundle, _, _, _ = prepared(tmp_path, monkeypatch)
    block = draft.blocks[0]
    request = {"scope": flow.scope(draft), "source": content.source.fingerprint,
        "kind": "workorders", "expected": flow.revision(bundle), "action": "publish_grid",
        "group": 0, "block": block.fingerprint,
        "values": {"non_pm_received": True, "non_pm_closed": True,
                   "confirmed": True, "closed_statuses": "Closed, Complete"}}
    applied = apply_request(draft, content, request)
    assert check_binding(applied) is None
    with pytest.raises(ValueError, match="row review changed"):
        apply_request(applied, content, request)


def test_source_link_can_be_removed_without_losing_manual_edits(tmp_path, monkeypatch):
    draft, content, bundle, _, _, manual = prepared(tmp_path, monkeypatch)
    accepted = apply_grid(draft, bundle)
    saved = flow.saved_bundle(accepted, content.source.id, "workorders")
    block = accepted.blocks[0]
    restored = remove(accepted, saved, expected_revision=flow.revision(saved),
        expected_block=block.fingerprint, confirmed=True)
    assert restored.blocks[0].extra_tables == draft.blocks[0].extra_tables
    assert restored.blocks[0].extra_tables[-1] == manual
    assert check_binding(restored) is None

    edited = replace(block.extra_tables[1], rows=(("Example North", *("99",) * 12),
                                                block.extra_tables[1].rows[1]))
    changed_block = replace(block, extra_tables=(block.extra_tables[0], edited, *block.extra_tables[2:]))
    newer = replace(accepted, blocks=(changed_block,))
    with pytest.raises(ValueError, match="grids were edited"):
        remove(newer, saved, expected_revision=flow.revision(saved),
               expected_block=changed_block.fingerprint, confirmed=True)
    manual_result = remove(newer, saved, expected_revision=flow.revision(saved),
        expected_block=changed_block.fingerprint, confirmed=True, keep_manual=True)
    assert manual_result.blocks[0].extra_tables[1] == edited
    assert check_binding(manual_result) is None


def test_visible_source_workspace_applies_confirmed_grids(tmp_path, monkeypatch):
    draft, content, _, _, _, _ = prepared(tmp_path, monkeypatch)
    script = """
import streamlit as st
from app.monthly_report_work_order_review_ui import render_reviewed_rows
draft = st.session_state['draft']
draft, blocks = render_reviewed_rows(draft, {b.key:b for b in draft.blocks}, 'grid-ui', st.session_state['content'])
st.session_state['draft'] = draft
"""
    app = AppTest.from_string(script, default_timeout=20)
    app.session_state['draft'] = draft
    app.session_state['content'] = content
    app.run()
    assert not app.exception
    next(box for box in app.checkbox if box.label ==
         "I reviewed the rows and confirmed coverage for the selected measures").check()
    next(button for button in app.button if button.label == "Apply verified monthly grid counts").click().run()
    assert not app.exception and not app.warning
    result = app.session_state['draft']
    assert result.blocks[0].extra_tables[1].rows[0][-2:] == ("1", "0")
    assert check_binding(result) is None
