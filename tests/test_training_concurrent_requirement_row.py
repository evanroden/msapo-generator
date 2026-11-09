"""Two independent Training editors must never silently overwrite one another.

Streamlit AppTest instances model two separate browser sessions, with separate
widget state and a real shared Training store. Native pointer/keyboard delivery
and the served browser remain separate acceptance checks.
"""
from dataclasses import replace

import pytest

from app import monthly_report_library as library
from app import monthly_report_training as training
from app.monthly_report_model import ResolvedBlock
from test_training_requirement_add_capture import (
    PROFILE, add, captured_cell, current, deliver, matrix, open_app, prepare,
    report, widget,
)


@pytest.mark.parametrize("first_writer", ("requirement", "row"))
def test_two_training_sessions_preserve_conflict_and_both_edits_after_review(
        monkeypatch, tmp_path, first_writer):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "synthetic-store"))
    original = matrix(2026)
    starting = report(original)
    standing = training.save_training(
        PROFILE, original, expected_revision=0, actor="Synthetic first editor")
    baseline = library.save_snapshot(starting, expected_revision=0)

    # Distinct AppTests retain independent native-grid widgets and cached
    # standing revisions, as two tabs open before either user saves would.
    requirement_tab, _ = open_app(monkeypatch, original, real_storage=True)
    row_tab, _ = open_app(monkeypatch, original, real_storage=True)
    prepare(requirement_tab, "Orientation")
    original_grid_key = deliver(row_tab, edits={0: {"Safety": "Completed"}})

    if first_writer == "requirement":
        add(requirement_tab)
        assert not requirement_tab.error
        assert current(requirement_tab).columns[-1] == "Orientation"
        row_tab.run()
        stale_tab = row_tab
    else:
        row_tab.run()
        assert not row_tab.exception and not row_tab.error
        assert current(row_tab).rows[0][2] == "Completed"
        add(requirement_tab)
        stale_tab = requirement_tab

    # Only the first write reached the revision-checked shared store. The
    # loser retains its edits in the native grid or the requirement input.
    assert not stale_tab.exception
    assert any("updated elsewhere" in item.value for item in stale_tab.error)
    assert any(button.label == "Reload saved training matrix"
               for button in stale_tab.button)
    assert training.load_training(PROFILE.contract)["revision"] == standing["revision"] + 1
    if first_writer == "requirement":
        grid = next(g for g in stale_tab.dataframe if "_grid_" in g.key)
        assert grid.key == original_grid_key
        assert captured_cell(stale_tab, grid, "Safety") == "Completed"
        assert current(stale_tab).rows[0][2] == "Pending"
    else:
        assert widget(stale_tab, "text_input", "Requirement name").value == "Orientation"
        assert current(stale_tab).columns == original.columns

    # A deliberate reload (not a silent overwrite) brings in the other
    # user's commit. Reapply the visibly retained pending change and save.
    widget(stale_tab, "button", "Reload saved training matrix").click().run()
    assert not stale_tab.exception and not stale_tab.error
    if first_writer == "requirement":
        assert "Orientation" in current(stale_tab).columns
        deliver(stale_tab, edits={0: {"Safety": "Completed"}})
        stale_tab.run()
    else:
        assert current(stale_tab).rows[0][2] == "Completed"
        assert widget(stale_tab, "text_input", "Requirement name").value == "Orientation"
        add(stale_tab)

    expected = replace(
        original, columns=(*original.columns, "Orientation"),
        rows=tuple((*row[:2], "Completed" if index == 0 else row[2],
                    "Not recorded") for index, row in enumerate(original.rows)))
    assert not stale_tab.exception and not stale_tab.error
    assert current(stale_tab) == expected
    latest = training.load_training(PROFILE.contract)
    assert latest["revision"] == standing["revision"] + 2
    assert training.seed_matrix(
        PROFILE, ResolvedBlock("training_summary", "This month"),
        latest, year=2026) == expected

    # A fresh report load must retain the two edits, original monthly notes,
    # and the monthly completed-session evidence, with earlier history intact.
    committed = library.save_snapshot(
        stale_tab.session_state["draft"], expected_revision=baseline.revision)
    reopened = library.load_snapshot(PROFILE.contract, PROFILE.key, starting.period)
    assert reopened == committed
    training_block = next(b for b in reopened.draft.blocks
                          if b.key == "training_summary")
    assert expected in training_block.extra_tables
    assert training_block.text == "Keep monthly note"
    assert any(t.reference == training.EVENT_REF and t.rows
               for t in training_block.extra_tables)
    assert library.load_snapshot_version(
        PROFILE.contract, PROFILE.key, starting.period, baseline.revision) == baseline
