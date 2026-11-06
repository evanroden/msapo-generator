"""Imported headings remain literal during read-only recovery comparisons."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app.monthly_report_compare_ui import _table, compare_drafts
from app.monthly_report_model import (
    ColumnSpec, ReportDraft, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, synthetic_profiles,
)


@pytest.mark.parametrize("columns,rows,expected", [
    (("Asset", "Status"), (("Pump", "Pending"),), "Row 1: Asset: Pump; Status: Pending"),
    (("", "Status"), (("", "Pending"),), "Row 1: : ; Status: Pending"),
    (("Reading", "Reading"), (("0", "17"),), "Row 1: Reading: 0; Reading: 17"),
    (("Asset",), (("Pump", "Extra"),), "Row 1: Asset: Pump; Column 2: Extra"),
    (("Status",), (("Pending",), ("Complete",)), "Row 1: Status: Pending\nRow 2: Status: Complete"),
    ((ColumnSpec("amount", "Amount"), ColumnSpec("done", "Complete")),
     ((0, False),), "Row 1: Amount: 0; Complete: False"),
    ((ColumnSpec("blank", ""),), (("Kept",),), "Row 1: : Kept"),
    ((), ((0, False, ""),), "Row 1: Column 1: 0; Column 2: False; Column 3: "),
    (("Unused",), (), "None"),
])
def test_literal_and_canonical_labels_preserve_physical_values(columns, rows, expected):
    assert _table(columns, rows) == expected


def _copies(columns=("Asset", "Status")):
    table = ReportTable(columns, (("Synthetic pump", "Pending"),), "synthetic-source:page:1")
    saved = ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9), "Synthetic Editor",
        default_sections(), (ResolvedBlock("activity_summary", "This month", extra_tables=(table,)),))
    changed = replace(table, rows=(("Synthetic pump", "Complete"),))
    working = replace(saved, blocks=(replace(saved.blocks[0], extra_tables=(changed,)),))
    return saved, working


@pytest.mark.parametrize("columns", [("Asset", "Status"), ("", "Status"), ("Reading", "Reading")])
def test_imported_table_comparison_uses_each_literal_heading_without_mutation(columns):
    saved, working = _copies(columns)
    original = (saved, working)
    change, = compare_drafts(working, saved)
    for text, status in ((change.saved, "Pending"), (change.working, "Complete")):
        assert f"Row 1: {columns[0]}: Synthetic pump; {columns[1]}: {status}" in text
        assert "built-in method" not in text and "object at 0x" not in text
    assert (saved, working) == original
    assert compare_drafts(saved, saved) == ()
    assert saved.blocks[0].extra_tables[0].reference == working.blocks[0].extra_tables[0].reference


COMPARISON = '''
import streamlit as st
from app.monthly_report_compare_ui import render_conflict_comparison
render_conflict_comparison(st.session_state['working'], st.session_state['snapshot'])
'''


def _assert_labels(app):
    assert not app.exception
    shown = "\n".join(item.value for item in app.text)
    assert "Row 1: Asset: Synthetic pump; Status: Pending" in shown
    assert "Row 1: Asset: Synthetic pump; Status: Complete" in shown
    assert "built-in method" not in shown and "object at 0x" not in shown


def test_actual_shared_comparison_is_read_only_and_labels_both_copies(monkeypatch):
    saved, working = _copies()
    snapshot = library.SavedReport(saved, "2026-11-04T20:00:00Z", 2, entered_editor="Synthetic Colleague")

    def no_write(*args, **kwargs):
        pytest.fail("Reading a comparison must not save either copy")

    monkeypatch.setattr(library, "save_snapshot", no_write)
    monkeypatch.setattr(active_work, "save", no_write)
    app = AppTest.from_string(COMPARISON)
    app.session_state["working"] = working
    app.session_state["snapshot"] = snapshot
    app.run()
    _assert_labels(app)
    app.run()
    _assert_labels(app)
    assert not app.button and not app.checkbox
    assert app.session_state["working"] == working
    assert app.session_state["snapshot"] == snapshot


OLDER = '''
import streamlit as st
from app.monthly_report_active_conflict_ui import render_older_draft_conflict
st.session_state['choice'] = render_older_draft_conflict(
    st.session_state['active'], st.session_state['snapshot'], 'a' * 32, 'labels')
'''


def _older(active, snapshot):
    app = AppTest.from_string(OLDER)
    app.session_state["active"] = active
    app.session_state["snapshot"] = snapshot
    app.run()
    assert not app.exception
    next(b for b in app.button if b.label == "Review draft changes").click().run()
    return app


def test_actual_older_draft_review_keeps_choices_bound_to_unchanged_copies(monkeypatch):
    saved, working = _copies()
    snapshot = library.SavedReport(saved, "2026-11-04T20:00:00Z", 2)
    active = active_work.ActiveWork(working, 3, 1, generation="b" * 32)
    # Only the standing-profile read is supplied. The real review control,
    # comparison and pair-bound choice keys run; no persistence is simulated.
    monkeypatch.setattr(library, "load_profile", lambda *args: SimpleNamespace(profile=saved.profile))
    app = _older(active, snapshot)
    _assert_labels(app)
    choices = [(b.label, b.key, b.disabled) for b in app.button]
    assert [c[0] for c in choices] == ["Continue with unfinished draft", "Open saved report"]
    assert not any(c[2] for c in choices)
    assert app.session_state["choice"] is None
    app.run()
    assert [(b.label, b.key, b.disabled) for b in app.button] == choices
    assert app.session_state["active"] == active and app.session_state["snapshot"] == snapshot


@pytest.mark.parametrize("choice", ["Continue with unfinished draft", "Open saved report"])
def test_public_storage_recovery_choices_preserve_labels_and_shared_history(monkeypatch, tmp_path, choice):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    saved, working = _copies()
    library.save_profile(saved.profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    first = library.save_snapshot(saved, expected_revision=0)
    snapshot = library.save_snapshot(replace(saved, prepared_by="Synthetic Colleague"), expected_revision=1)
    active = active_work.save("a" * 32, working, expected_revision=0, base_snapshot_revision=1)
    app = _older(active, snapshot)
    _assert_labels(app)
    assert active_work.load("a" * 32, saved.profile.contract, saved.profile.key, saved.period) == active
    next(b for b in app.button if b.label == choice).click().run()
    assert not app.exception and not app.error
    expected = working if choice == "Continue with unfinished draft" else snapshot.draft
    reopened = active_work.load("a" * 32, saved.profile.contract, saved.profile.key, saved.period)
    assert reopened.draft == expected
    assert reopened.base_snapshot_revision == snapshot.revision
    assert library.load_snapshot(saved.profile.contract, saved.profile.key, saved.period) == snapshot
    assert library.load_snapshot_version(saved.profile.contract, saved.profile.key, saved.period, 1) == first
    assert [v.revision for v in library.snapshot_history(saved.profile.contract, saved.profile.key, saved.period)[0]] == [2, 1]
