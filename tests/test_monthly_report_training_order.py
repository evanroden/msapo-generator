"""Monthly Training input precedes shared requirements without changing content."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Block

from app import monthly_report_library as library, monthly_report_training_ui as ui
from app.monthly_report_training import load_training
from test_monthly_report_training_retention import APP, training, current, widget


def _path(root, target, path=()):
    if root is target:
        return path
    if isinstance(root, Block):
        for index, child in root.children.items():
            found = _path(child, target, (*path, index))
            if found is not None:
                return found
    return None


def _assert_monthly_first(app):
    notes = widget(app, "text_area", "Training notes")
    topic = widget(app, "text_input", "Training topic")
    heading = next(h for h in app.subheader if h.value == "Staff training requirements")
    assert _path(app._tree, topic) < _path(app._tree, notes) < _path(app._tree, heading)
    requirement = widget(app, "text_input", "Requirement name")
    assert _path(app._tree, notes) < _path(app._tree, requirement)


def test_monthly_first_preserves_content_and_widget_identity(training):
    app, draft, matrix, event, standing, saved = training
    _assert_monthly_first(app)
    before = current(app)
    identities = {label: widget(app, kind, label).proto.id for kind, label in (
        ("text_area", "Training notes"), ("text_input", "Training topic"),
        ("text_input", "Requirement name"))}
    app.run()
    assert not app.exception
    _assert_monthly_first(app)
    assert current(app) == before == draft.blocks[0]
    for kind, label in (("text_area", "Training notes"), ("text_input", "Training topic"),
                        ("text_input", "Requirement name")):
        assert widget(app, kind, label).proto.id == identities[label]
    assert load_training(draft.profile.contract) == standing
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved


def test_fresh_and_reopened_reports_put_monthly_fields_first(training):
    _, draft, *_ = training
    for block in (replace(draft.blocks[0], text="", extra_tables=()), draft.blocks[0]):
        app = AppTest.from_string(APP)
        app.session_state["draft"] = replace(draft, blocks=(block,))
        app.session_state["blocks"] = {block.key: block}
        app.run()
        assert not app.exception
        _assert_monthly_first(app)
        assert current(app).text == block.text


def test_matrix_failure_keeps_monthly_fields_before_error_and_preserves_clear(training, monkeypatch):
    app, draft, matrix, event, standing, saved = training
    for key in list(app.session_state.filtered_state):
        if key.startswith("test_training_") and key.endswith("_saved"):
            del app.session_state[key]
    def fail(*args, **kwargs):
        raise OSError("Synthetic matrix read failed")
    monkeypatch.setattr(ui, "load_training", fail)
    widget(app, "text_area", "Training notes").set_value("").run()
    assert not app.exception
    error = next(e for e in app.error if e.value == "Synthetic matrix read failed")
    assert _path(app._tree, widget(app, "text_area", "Training notes")) < _path(app._tree, error)
    assert current(app).text == ""
    assert current(app).extra_tables == (matrix, event)
    app.run()
    assert current(app).text == ""
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved
