"""Training rollover retains requirements without accumulating completion headers.

All identities and dates are synthetic. AppTest assertions cover the native
widget protocol and real snapshot readback, not a production browser journey.
"""
from dataclasses import replace
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import (
    BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile, ReportTable,
    ResolvedBlock, SectionSpec, TrainingSessionTable,
)
from app.monthly_report_setup import new_month_draft
from app.monthly_report_training import (
    EVENT_COLUMNS, EVENT_REF, MATRIX_REF, add_event, apply_tables, events_for_period,
    load_training, save_training,
)


SEPTEMBER = ReportPeriod(2026, 9)
OCTOBER = ReportPeriod(2026, 10)
NOVEMBER = ReportPeriod(2026, 11)
APP = '''
import streamlit as st
from app.monthly_report_training_ui import render_training

def field(key, value):
    if key not in st.session_state:
        st.session_state[key] = value
    return key

st.session_state['blocks'] = render_training(
    st.session_state['draft'], st.session_state['blocks'], 'rollover-test', field)
'''


def _event(period):
    return add_event(
        None, title="TEST session " + period.key, when=date(period.year, period.month, 3),
        mode="Virtual", participants=["Synthetic Hospital Tech"], hours="", period=period,
    )


def _block(draft):
    return next(block for block in draft.blocks if block.key == "training_summary")


def _with_block(draft, block):
    return replace(draft, blocks=tuple(block if old.key == block.key else old for old in draft.blocks))


def _saved(draft, revision=0):
    library.save_snapshot(draft, expected_revision=revision, entered_editor=draft.prepared_by)
    return library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft


def _files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*.json")}


@pytest.fixture
def training_rollover(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    profile = ReportProfile(
        "Synthetic Training Rollover", "north", "Synthetic North",
        (Facility("north", "Synthetic North"),),
    )
    matrix = ReportTable(
        ("Team member", "Site", "TEST safety", "TEST lockout", "TEST infection",
         "TEST operations", "TEST orientation"),
        (("Synthetic Hospital Tech", "Synthetic North", "Completed", "Pending",
          "Not required", "Not recorded", ""),),
        MATRIX_REF,
    )
    event = _event(SEPTEMBER)
    block = ResolvedBlock(
        "training_summary", "This month", text="TEST ONLY September monthly note.",
        extra_tables=(matrix, event), references=("synthetic:reviewed-training",),
    )
    draft = ReportDraft(
        profile, SEPTEMBER, "Synthetic Editor",
        (SectionSpec("training", "10", "Training", (BlockSpec("training_summary", "rich_text"),)),),
        (block,), synthetic=True,
    )
    save_training(profile, matrix, expected_revision=0, actor=draft.prepared_by)
    _saved(draft)
    return draft, matrix, event


def test_new_month_keeps_the_exact_standing_matrix_and_its_unknown_values(training_rollover):
    prior, matrix, _ = training_rollover
    following = new_month_draft(prior, OCTOBER)
    block = _block(following)
    assert block.extra_tables == (matrix,)
    assert block.extra_tables[0].rows[0][2:] == (
        "Completed", "Pending", "Not required", "Not recorded", "",
    )
    assert not block.text and not block.rows and not block.references
    assert events_for_period(block, OCTOBER) is None
    assert _saved(following) == following


@pytest.mark.parametrize("legacy", [False, True])
def test_old_completion_table_is_absent_instead_of_an_anonymous_header(training_rollover, legacy):
    prior, _, event = training_rollover
    if legacy:
        event = ReportTable(event.columns, event.rows, EVENT_REF)
    prior = _with_block(prior, replace(_block(prior), extra_tables=(event,)))
    following = new_month_draft(prior, OCTOBER)
    assert _block(following).extra_tables == ()
    assert not _block(following).text
    assert _block(prior).extra_tables == (event,)


def test_same_month_keeps_completion_notes_and_row_identity(training_rollover):
    prior, matrix, event = training_rollover
    following = new_month_draft(prior, SEPTEMBER)
    assert following == prior
    assert _block(following).extra_tables == (matrix, event)
    assert _block(following).extra_tables[1].row_tokens == event.row_tokens
    assert event.rows[0][-1] == ""  # Unknown hours are not inferred.


def test_custom_imported_schema_is_retained_without_old_monthly_values(training_rollover):
    prior, _, _ = training_rollover
    custom = ReportTable(
        ("Native topic", "Audience", "Recorded duration", "Qualification"),
        (("TEST imported session", "Synthetic operators", "", "Recorded in source"),),
        "synthetic-source:table:5",
    )
    prior = _with_block(prior, replace(_block(prior), extra_tables=(custom,)))
    following = new_month_draft(prior, OCTOBER)
    expected = ReportTable(custom.columns, (), "")
    assert _block(following).extra_tables == (expected,)
    assert _block(new_month_draft(_saved(following), NOVEMBER)).extra_tables == (expected,)
    assert _block(prior).extra_tables == (custom,)


def test_two_saved_rollovers_do_not_grow_tables_or_rewrite_prior_history(training_rollover):
    prior, matrix, _ = training_rollover
    root = library._root()
    before = _files(root)
    standing = load_training(prior.profile.contract)
    current = prior
    counts = []
    for period in (OCTOBER, NOVEMBER):
        following = new_month_draft(current, period)
        event = _event(period)
        edited = apply_tables(_block(following), matrix, event)
        current = _saved(_with_block(following, edited))
        counts.append(len(_block(current).extra_tables))
        accepted = next(table for table in _block(current).extra_tables if table.reference == EVENT_REF)
        assert accepted == event
        assert accepted.rows[0][-1] == ""
        assert apply_tables(_block(current), matrix, accepted) == _block(current)
        assert new_month_draft(current, period) == current
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, SEPTEMBER).draft == prior
    assert library.load_snapshot_version(prior.profile.contract, prior.profile.key, SEPTEMBER, 1).draft == prior
    assert load_training(prior.profile.contract) == standing
    assert all((root / path).read_bytes() == raw for path, raw in before.items())
    assert counts == [2, 2]
    assert _block(current).extra_tables == (matrix, event)


def test_omitted_training_stays_omitted_when_standing_rows_are_retained(training_rollover):
    prior, matrix, _ = training_rollover
    prior = _with_block(prior, replace(_block(prior), source="Omit"))
    following = new_month_draft(prior, OCTOBER)
    assert _block(following).source == "Omit"
    assert _block(following).extra_tables == (matrix,)


def test_custom_session_shape_clears_obsolete_row_tokens_with_the_rows(training_rollover):
    prior, _, _ = training_rollover
    custom = TrainingSessionTable(
        ("Custom topic", "Custom date"), (("TEST topic", "2026-09-03"),),
        "synthetic-custom-table", ("synthetic-old-row",),
    )
    prior = _with_block(prior, replace(_block(prior), extra_tables=(custom,)))
    following = new_month_draft(prior, OCTOBER)
    expected = ReportTable(custom.columns, (), "")
    assert _block(following).extra_tables == (expected,)
    assert _saved(following) == following


@pytest.mark.parametrize("columns,reference,rows", [
    (("Team member", "Site", "Native qualification"), "", ()),
    (EVENT_COLUMNS, "synthetic-import-table", ()),
    (("Training", "Date", "Custom audience", "Hours"), "", ()),
])
def test_unowned_native_headers_are_not_promoted_to_shared_requirements_or_removed(
        training_rollover, columns, reference, rows):
    prior, _, _ = training_rollover
    custom = ReportTable(columns, rows, reference)
    prior = _with_block(prior, replace(_block(prior), extra_tables=(custom,)))
    following = new_month_draft(prior, OCTOBER)
    assert _block(following).extra_tables == (ReportTable(columns, (), ""),)


@pytest.mark.parametrize("reference", ["", "synthetic-custom-schema"])
def test_unknown_event_shaped_header_survives_repeated_months_without_new_ghosts(
        training_rollover, reference):
    prior, matrix, prior_event = training_rollover
    custom = ReportTable(EVENT_COLUMNS, (), reference)
    current = _with_block(prior, replace(_block(prior), extra_tables=(matrix, custom, prior_event)))
    expected_schema = ReportTable(EVENT_COLUMNS, (), "")
    before = _files(library._root())
    counts = []
    for period in (OCTOBER, NOVEMBER):
        following = new_month_draft(current, period)
        event = _event(period)
        edited = apply_tables(_block(following), matrix, event)
        current = _saved(_with_block(following, edited))
        tables = _block(current).extra_tables
        counts.append(len(tables))
        assert tuple(table for table in tables if table.reference == "") == (expected_schema,)
        assert tuple(table for table in tables if table.reference == MATRIX_REF) == (matrix,)
        assert tuple(table for table in tables if table.reference == EVENT_REF) == (event,)
    assert counts == [3, 3]
    assert all((library._root() / path).read_bytes() == raw for path, raw in before.items())


def _visit(draft):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["blocks"] = {block.key: block for block in draft.blocks}
    app.run()
    assert not app.exception and not app.error
    return app


def _widget(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def test_first_event_after_rollover_and_fresh_reentry_keep_one_matrix_and_one_session(training_rollover):
    prior, matrix, _ = training_rollover
    standing_before = _files(library._root() / "training")
    following = _saved(new_month_draft(prior, OCTOBER))
    app = _visit(following)
    assert _widget(app, "text_area", "Training notes").value == ""
    assert any("No training sessions added this month." == text.value for text in app.caption)
    _widget(app, "text_input", "Training topic").set_value("TEST October first entry")
    _widget(app, "date_input", "Training date").set_value(date(2026, 10, 3))
    _widget(app, "multiselect", "Participants").set_value(["Synthetic Hospital Tech"])
    _widget(app, "button", "Add completed training").click().run()
    assert not app.exception and not app.error
    edited = app.session_state["blocks"]["training_summary"]
    restored = _saved(_with_block(following, edited), revision=1)
    fresh = _visit(restored)
    final = fresh.session_state["blocks"]["training_summary"]
    fresh.run()
    assert fresh.session_state["blocks"]["training_summary"] == final
    assert _files(library._root() / "training") == standing_before
    assert library.load_snapshot(prior.profile.contract, prior.profile.key, SEPTEMBER).draft == prior
    assert len(final.extra_tables) == 2
    assert final.extra_tables[0] == matrix
    assert final.extra_tables[1].reference == EVENT_REF
    assert final.extra_tables[1].rows == (
        ("TEST October first entry", "2026-10-03", "In person", "Synthetic Hospital Tech", ""),
    )
