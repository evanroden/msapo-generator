"""Completed sessions use one scoped form with direct feedback and row editing."""
from dataclasses import replace
from datetime import date

import pytest

from app.monthly_report_training import EVENT_REF, load_training
from test_monthly_report_training_retention import training, current, widget, NOTE


def rows(app):
    return next((table.rows for table in current(app).extra_tables if table.reference == EVENT_REF), ())


def fill_session(app, *, title="Synthetic inspection refresher", when=date(2026, 9, 29), hours="1"):
    widget(app, "text_input", "Training topic").set_value(title)
    widget(app, "date_input", "Training date").set_value(when)
    widget(app, "multiselect", "Participants").set_value(["Synthetic Hospital Tech"])
    widget(app, "text_input", "Hours (optional)").set_value(hours)


def action(app, first_line, title="Accepted safety event"):
    return next(button for button in app.button if button.label.startswith(first_line + "\n\n") and title in button.label)


def test_success_add_shows_row_resets_stays_open_and_allows_a_deliberate_second_entry(training):
    app, draft, matrix, event, standing, saved = training
    old_key = widget(app, "text_input", "Training topic").key
    fill_session(app)
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception and not app.error
    assert len(rows(app)) == 2
    assert rows(app)[-1] == ("Synthetic inspection refresher", "2026-09-29", "In person", "Synthetic Hospital Tech", "1")
    assert widget(app, "text_input", "Training topic").value == ""
    assert widget(app, "text_input", "Training topic").key != old_key
    assert widget(app, "date_input", "Training date").value is None
    assert widget(app, "multiselect", "Participants").value == []
    assert widget(app, "text_input", "Hours (optional)").value == ""
    assert next(e for e in app.expander if e.label == "Add completed training").proto.expanded is True
    assert any("Training added to this report." == message.value for message in app.success)
    fresh_key = widget(app, "text_input", "Training topic").key
    app.run()
    assert widget(app, "text_input", "Training topic").key == fresh_key
    assert next(e for e in app.expander if e.label == "Add completed training").proto.expanded is True
    assert any(" · 1 hour" in caption.value for caption in app.caption)
    assert not any("1 hours" in caption.value for caption in app.caption)
    widget(app, "button", "Add completed training").click().run()
    assert len(rows(app)) == 2, "The cleared form cannot add a duplicate of its earlier submission"
    fill_session(app, title="Second deliberate training", when=date(2026, 9, 30), hours="")
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception and not app.error
    assert len(rows(app)) == 3 and rows(app)[-1][-1] == ""
    app.run()
    assert len(rows(app)) == 3
    assert load_training(draft.profile.contract) == standing
    assert current(app).text == NOTE and matrix in current(app).extra_tables


def test_invalid_values_keep_native_identity_and_show_each_error_beside_its_field(training):
    app, *_ = training
    topic = widget(app, "text_input", "Training topic")
    identity = topic.proto.id
    widget(app, "text_input", "Hours (optional)").set_value("unknown value")
    widget(app, "button", "Add completed training").click().run()
    assert not app.exception
    assert {error.value for error in app.error} == {
        "Enter a topic", "Choose a date in September 2026", "Choose at least one participant",
        "Enter positive hours, or leave blank if unknown",
    }
    assert widget(app, "text_input", "Training topic").proto.id == identity
    assert widget(app, "text_input", "Hours (optional)").value == "unknown value"
    form = app.get("form")[0]
    items = list(form.children.values())
    for label, expected in (("Training topic", "Enter a topic"),
                            ("Training date", "Choose a date in September 2026"),
                            ("Participants", "Choose at least one participant"),
                            ("Hours (optional)", "Enter positive hours, or leave blank if unknown")):
        index = next(n for n, element in enumerate(items) if getattr(element, "label", "") == label)
        assert items[index + 1].value == expected
    assert len(rows(app)) == 1 and current(app).text == NOTE


def test_edit_updates_only_selected_session_and_preserves_same_action_notes(training):
    app, draft, matrix, event, standing, _ = training
    action(app, "Edit session").click().run()
    assert widget(app, "text_input", "Training topic").value == "Accepted safety event"
    assert widget(app, "date_input", "Training date").value == date(2026, 9, 1)
    assert widget(app, "multiselect", "Participants").value == ["Synthetic Hospital Tech"]
    assert widget(app, "text_input", "Hours (optional)").value == "0.75"
    assert next(e for e in app.expander if e.label == "Edit training session").proto.expanded is True
    widget(app, "text_input", "Training topic").set_value("Corrected accepted session")
    widget(app, "text_input", "Hours (optional)").set_value("")
    widget(app, "text_area", "Training notes").set_value("Notes delivered with Save session.")
    widget(app, "button", "Save session").click().run()
    assert not app.exception and not app.error
    assert rows(app) == (("Corrected accepted session", "2026-09-01", "In person", "Synthetic Hospital Tech", ""),)
    assert current(app).text == "Notes delivered with Save session."
    assert any(message.value == "Training session updated." for message in app.success)
    assert widget(app, "text_input", "Training topic").value == ""
    assert matrix in current(app).extra_tables
    assert load_training(draft.profile.contract) == standing
    app.run()
    assert len(rows(app)) == 1


@pytest.mark.parametrize("roster, participants, expected", [
    (("Taylor; Lead", "Taylor", "Lead"), ("Taylor; Lead",), ["Taylor; Lead"]),
    (("Taylor; Lead", "Morgan; Tech"), ("Taylor; Lead", "Morgan; Tech"), ["Taylor; Lead", "Morgan; Tech"]),
    (("Synthetic Hospital Tech",), ("Visiting; Instructor",), ["Visiting; Instructor"]),
    (("Taylor", "Morgan"), ("Taylor", "Morgan"), ["Taylor", "Morgan"]),
    (("Taylor; Lead", "Morgan", "Taylor", "Lead; Morgan"), ("Taylor; Lead", "Morgan"), ["Taylor; Lead; Morgan"]),
])
def test_edit_keeps_delimited_participant_identity_and_ambiguous_legacy_text(training, roster, participants, expected):
    from app.monthly_report_training import add_event
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_training_retention import APP

    app, draft, matrix, _, standing, _ = training
    matrix = replace(matrix, rows=tuple((name, "Synthetic North", "Not recorded") for name in roster))
    event = add_event(None, title="Accepted safety event", when=date(2026, 9, 1),
                      mode="In person", participants=participants, hours="0.75", period=draft.period)
    block = replace(current(app), extra_tables=(matrix, event))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["draft"] = replace(draft, blocks=(block,))
    app.session_state["blocks"] = {block.key: block}
    app.run()
    assert set(roster) <= set(widget(app, "multiselect", "Participants").options)
    action(app, "Edit session").click().run()
    assert widget(app, "multiselect", "Participants").value == expected
    widget(app, "text_input", "Hours (optional)").set_value("1")
    widget(app, "button", "Save session").click().run()
    assert not app.exception and not app.error
    assert rows(app) == ((*event.rows[0][:-1], "1"),)
    assert current(app).text == NOTE
    assert load_training(draft.profile.contract) == standing
    from app import monthly_report_library as library
    library.save_snapshot(replace(draft, blocks=(current(app),)), expected_revision=1,
                          entered_editor=draft.prepared_by)
    saved_again = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert saved_again.draft.blocks[0] == current(app)
    # A fresh session reconstructs selection from the saved report content;
    # this must not depend on a roster cache or the previous editor's token.
    reopened = AppTest.from_string(APP, default_timeout=30)
    reopened.session_state["draft"] = saved_again.draft
    reopened.session_state["blocks"] = {block.key: saved_again.draft.blocks[0]}
    reopened.run()
    action(reopened, "Edit session").click().run()
    assert widget(reopened, "multiselect", "Participants").value == expected


def test_cancel_edit_keeps_saved_row_and_resets_to_add(training):
    app, *_ = training
    before = rows(app)
    action(app, "Edit session").click().run()
    widget(app, "text_input", "Training topic").set_value("Unsubmitted correction")
    widget(app, "button", "Cancel editing").click().run()
    assert not app.exception and not app.error
    assert rows(app) == before
    assert widget(app, "text_input", "Training topic").value == ""
    assert not any(button.label == "Save session" for button in app.button)
    assert next(e for e in app.expander if e.label == "Add completed training").proto.expanded is False


def test_edit_rejects_a_changed_collection_without_replacing_a_different_row(training):
    app, draft, matrix, event, *_ = training
    action(app, "Edit session").click().run()
    widget(app, "text_input", "Training topic").set_value("My retained edit")
    current_event = replace(event, rows=(("Newer session from another edit", *event.rows[0][1:]),))
    original = current(app)
    app.session_state["blocks"] = {original.key: replace(original, extra_tables=(matrix, current_event))}
    widget(app, "button", "Save session").click().run()
    assert not app.exception
    assert rows(app) == current_event.rows
    assert widget(app, "text_input", "Training topic").value == "My retained edit"
    assert any("entered details are kept" in item.value for item in app.warning)


@pytest.mark.parametrize("kind", ["Edit session", "Remove"])
def test_delayed_row_action_from_another_report_incarnation_is_rejected(training, kind):
    app, *_ = training
    old = action(app, kind)
    before = current(app)
    from streamlit.proto.WidgetStates_pb2 import WidgetStates
    stale = WidgetStates()
    stale.widgets.add(id=old.proto.id, trigger_value=True)
    app.session_state["test_rich_text_epoch"] = "replacement-report"
    app.run()
    app._run(stale)
    assert not app.exception and not app.error
    assert current(app) == before
    assert not any(button.label == "Save session" for button in app.button)


def test_short_row_action_retains_a_complete_distinct_native_accessible_name(training):
    app, *_ = training
    removal = action(app, "Remove")
    assert removal.label.split("\n\n")[0] == "Remove"
    assert " ".join(removal.label.split()) == "Remove session: Accepted safety event · 2026-09-01"
    assert "training_session_action" in removal.key
    assert any("clip:rect(0,0,0,0)" in item.value and "display:none" not in item.value for item in app.markdown)


def interrupted_app(training):
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_training_retention import APP
    original, draft, *_ = training
    source = APP.replace("st.session_state['blocks'] = render_training", "result = render_training")
    source += "\nst.session_state['result'] = result\nif st.session_state.get('commit_enabled', True):\n    st.session_state['blocks'] = result\n"
    app = AppTest.from_string(source, default_timeout=30)
    app.session_state["draft"] = draft
    app.session_state["blocks"] = original.session_state["blocks"]
    app.run()
    app.session_state["commit_enabled"] = False
    return app


def test_added_session_survives_interrupted_parent_commit_without_a_second_submission(training):
    app = interrupted_app(training)
    original = rows(app)
    fill_session(app)
    widget(app, "button", "Add completed training").click().run()
    assert rows(app) == original
    proposed = app.session_state["result"]["training_summary"]
    assert len(next(t.rows for t in proposed.extra_tables if t.reference == EVENT_REF)) == 2
    assert widget(app, "text_input", "Training topic").value == ""
    app.session_state["commit_enabled"] = True
    app.run()
    assert not app.exception and not app.error
    assert len(rows(app)) == 2 and rows(app)[-1][0] == "Synthetic inspection refresher"
    app.run()
    assert len(rows(app)) == 2


def test_add_then_remove_before_parent_commit_cannot_resurrect_removed_session(training):
    app = interrupted_app(training)
    original = rows(app)
    fill_session(app)
    widget(app, "button", "Add completed training").click().run()
    action(app, "Remove", "Synthetic inspection refresher").click().run()
    assert rows(app) == original
    app.session_state["commit_enabled"] = True
    app.run()
    app.run()
    assert not app.exception and not app.error
    assert rows(app) == original


@pytest.mark.parametrize("choice", ["Use pending sessions", "Keep current sessions"])
def test_interrupted_add_cannot_overwrite_newer_sessions_without_inspectable_choice(training, choice):
    app = interrupted_app(training)
    fill_session(app)
    widget(app, "button", "Add completed training").click().run()
    old = current(app)
    events = next(t for t in old.extra_tables if t.reference == EVENT_REF)
    newer = replace(events, rows=(("Newer current session", *events.rows[0][1:]),))
    app.session_state["blocks"] = {old.key: replace(old, extra_tables=tuple(newer if t.reference == EVENT_REF else t for t in old.extra_tables))}
    app.session_state["commit_enabled"] = True
    app.run()
    assert rows(app) == newer.rows
    assert any("Both versions" in warning.value for warning in app.warning)
    assert len(app.table) == 2
    assert widget(app, "button", "Add completed training").disabled
    widget(app, "button", choice).click().run()
    assert not app.exception and not app.error
    expected = newer.rows if choice == "Keep current sessions" else (*events.rows, ("Synthetic inspection refresher", "2026-09-29", "In person", "Synthetic Hospital Tech", "1"))
    assert rows(app) == expected
    app.run()
    assert rows(app) == expected and not app.warning


def test_successful_native_submission_resets_the_form_in_its_first_result(training):
    app, *_ = training
    fill_session(app)
    # Both labels are intentional here so the historical checkpoint exercises
    # the same native submission and fails on its retained input, not new copy.
    next(button for button in app.button if button.label in {"Add training session", "Add completed training"}).click().run()
    assert not app.exception and not app.error
    assert len(rows(app)) == 2
    assert widget(app, "text_input", "Training topic").value == ""
    assert widget(app, "date_input", "Training date").value is None
    assert widget(app, "multiselect", "Participants").value == []
