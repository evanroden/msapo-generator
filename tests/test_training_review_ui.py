"""Native review controls reach the real source-bound Training acceptance flow."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_training_review_flow as flow
from app import monthly_report_library as library
from app.monthly_report_training_import import restore_training_review
from test_training_review_flow import report, CSV, storage

APP = '''
import streamlit as st
from app.monthly_report_training_review_ui import render_training_import
draft = st.session_state['draft']
draft, blocks = render_training_import(draft, {b.key:b for b in draft.blocks}, 'training-review')
st.session_state['draft'] = draft
'''


def open_app(draft):
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = draft
    app.run()
    assert not app.exception
    return app


def widget(app, kind, label):
    return next(value for value in getattr(app, kind) if value.label == label)


def click(app, label):
    widget(app, "button", label).click().run()
    assert not app.exception


def test_visible_review_corrects_unknown_hours_and_keeps_original_then_reopens():
    app = open_app(report(b"Topic,Date,Method,Participants,Hours,Status\nDrill,2026-09-12,Virtual,Alice,0,Completed\n"))
    assert not app.session_state['draft'].source_row_reviews
    click(app, "Review this Training table")
    widget(app, "text_input", "Hours").set_value("")
    click(app, "Save Training row review")
    current = app.session_state['draft']
    value = flow.saved_review(current, current.sources[0], 1)
    row, = restore_training_review(value['record']).rows
    assert row.values[-1] == "" and row.origin.cells[4] == "0"
    click(app, "Include reviewed Training rows")
    accepted = app.session_state['draft']
    assert accepted.blocks[0].extra_tables[0].rows[0][-1] == ""
    library.save_snapshot(accepted, expected_revision=0, entered_editor="Synthetic Editor")
    reopened = library.load_snapshot(accepted.profile.contract, accepted.profile.key, accepted.period).draft
    second = open_app(reopened)
    assert widget(second, "text_input", "Hours").value == ""
    click(second, "Include reviewed Training rows")
    assert second.session_state['draft'] == reopened


def test_visible_historical_selection_is_explicit_and_does_not_relabel_date():
    app = open_app(report(b"Topic,Date,Method,Participants,Hours,Status\nOld drill,2026-08-12,Virtual,Alice,,Completed\n"))
    click(app, "Review this Training table")
    click(app, "Include reviewed Training rows")
    assert not app.session_state['draft'].blocks[0].extra_tables
    widget(app, "checkbox", "Include this older dated session as historical").check()
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    table, = app.session_state['draft'].blocks[0].extra_tables
    assert table.columns[0] == "Historical training"
    assert table.rows[0][1] == "2026-08-12"


def test_unknown_requirements_year_can_be_confirmed_without_reentering_cells():
    app = open_app(report(b"Team member,Site,Safety\nAlice,Synthetic North,Completed\n"))
    click(app, "Review this Training table")
    click(app, "Include reviewed Training rows")
    assert not app.session_state['draft'].blocks[0].extra_tables
    widget(app, "text_input", "Confirmed requirements source year").set_value("2026")
    click(app, "Confirm requirements year")
    click(app, "Include reviewed Training rows")
    table, = app.session_state['draft'].blocks[0].extra_tables
    assert table.reference == "training:matrix:v2:2026"
    assert table.rows == (("Alice", "Synthetic North", "Completed"),)


def test_stale_native_accept_keeps_newer_report_notes():
    app = open_app(report(b"Topic,Date,Method,Participants,Hours,Status\nDrill,2026-09-12,Virtual,Alice,,Completed\n"))
    click(app, "Review this Training table")
    stale = widget(app, "button", "Include reviewed Training rows")
    current = app.session_state['draft']
    newer = replace(current, blocks=(replace(current.blocks[0], text="Newer manually authored note"),))
    app.session_state['draft'] = newer
    stale.click().run()
    assert not app.exception
    assert app.session_state['draft'] == newer
    assert any("Training changed" in value.value for value in app.warning)


def test_ordinary_guided_training_reaches_durable_review_and_preserves_accepted_rows():
    guided = '''
import streamlit as st
from dataclasses import replace
from app.monthly_report_guided import _render_ordered_section
draft = st.session_state['draft']
def field(key, value):
    st.session_state.setdefault(key, value)
    return key
section = draft.sections[0]
draft, blocks = _render_ordered_section(draft, section, {b.key:b for b in draft.blocks},
    {s.key:s for s in section.blocks}, None, 'guided-training', {}, field)
st.session_state['draft'] = replace(draft, blocks=tuple(blocks.values()))
'''
    draft = report(b"Topic,Date,Method,Participants,Hours,Status\nDrill,2026-09-12,Virtual,Alice,,Completed\n")
    app = AppTest.from_string(guided, default_timeout=30)
    app.session_state['draft'] = draft
    app.run()
    assert not app.exception
    click(app, "Review this Training table")
    click(app, "Include reviewed Training rows")
    accepted = app.session_state['draft']
    assert accepted.source_row_reviews
    assert accepted.blocks[0].extra_tables[0].rows[0][0] == "Drill"
    app.run()
    assert not app.exception
    assert app.session_state['draft'] == accepted
    assert widget(app, "text_area", "Training notes").value == "Manual notes"


def test_hosted_browser_fixture_runs_real_guided_save_and_reload(monkeypatch):
    from pathlib import Path
    monkeypatch.setenv("EPC_TRAINING_SOURCE_QA", "1")
    fixture = Path(__file__).parent / "fixtures/workspaces/training_import_app.py"
    app = AppTest.from_file(fixture, default_timeout=30).run()
    assert not app.exception
    click(app, "Review this Training table")
    widget(app, "text_input", "Hours").set_value("")
    click(app, "Save Training row review")
    click(app, "Include reviewed Training rows")
    click(app, "Save synthetic shared version")
    accepted = app.session_state['draft']
    reopened = AppTest.from_file(fixture, default_timeout=30).run()
    assert not reopened.exception
    assert reopened.session_state['draft'] == accepted
    assert widget(reopened, "text_input", "Hours").value == ""


def test_year_confirmation_keeps_deliberate_duplicate_row_omission():
    app = open_app(report(b"Team member,Site,Safety\nAlice,Synthetic North,Completed\nAlice,Synthetic North,Completed\n"))
    click(app, "Review this Training table")
    widget(app, "checkbox", "Omit this Training source row").check()
    click(app, "Save Training row review")
    widget(app, "text_input", "Confirmed requirements source year").set_value("2026")
    click(app, "Confirm requirements year")
    click(app, "Include reviewed Training rows")
    table, = app.session_state['draft'].blocks[0].extra_tables
    assert table.rows == (("Alice", "Synthetic North", "Completed"),)


def test_missing_native_field_delivery_never_becomes_literal_none():
    import pytest
    from app.monthly_report_training_review_ui import apply_request
    draft = report(b"Topic,Date,Method,Participants,Hours,Status\nDrill,2026-09-12,Virtual,Alice,,Completed\n")
    value = flow.prepare_review(draft, draft.sources[0], 1)
    draft = flow.store_review(draft, value)
    review = restore_training_review(value['record'])
    columns = (*review.normalized_columns, "Completion status")
    fields = dict(zip(columns, (*review.rows[0].values, review.rows[0].status)))
    fields.update({"Hours": None, "excluded": False, "historical": False})
    request = {"scope": flow.scope(draft), "source_id": draft.sources[0].id,
        "source": draft.sources[0].fingerprint, "table": 1, "expected": flow.revision(value),
        "action": "row", "row": review.rows[0].key, "columns": columns, "values": fields}
    with pytest.raises(ValueError, match="not delivered"):
        apply_request(draft, request)
    assert flow.revision(flow.saved_review(draft, draft.sources[0], 1)) == flow.revision(value)


def test_bad_xlsx_upload_preserves_current_review_and_valid_retry(monkeypatch):
    from io import BytesIO
    from app import monthly_report_training_review_ui as ui
    app = open_app(report(b"Topic,Date,Method,Participants,Hours,Status\nDrill,2026-09-12,Virtual,Alice,,Completed\n"))
    click(app, "Review this Training table")
    before = app.session_state['draft']
    uploads = [BytesIO(b"not a zip or workbook")]
    uploads[0].name = "broken.xlsx"
    real = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw:
        uploads[0] if label == "Prior Training report or table" else real(label, *a, **kw))
    app.run()
    widget(app, "checkbox", "This Training source belongs to the selected report sites").check().run()
    click(app, "Add Training source")
    assert app.session_state['draft'] == before
    assert any("could not" in value.value.lower() or "not read" in value.value.lower() for value in app.warning)
    uploads[0] = BytesIO(b"Topic,Date,Method,Participants,Hours,Status\nSecond drill,2026-09-14,Virtual,Bob,,Completed\n")
    uploads[0].name = "valid-retry.csv"
    app.run()
    click(app, "Add Training source")
    after = app.session_state['draft']
    assert len(after.sources) == 2
    assert after.source_row_reviews == before.source_row_reviews
    assert after.blocks == before.blocks
