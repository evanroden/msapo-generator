"""A84: stale shared revisions from independent editors need exact field choices.

These are synthetic Streamlit AppTest requests, not served browser acceptance.
"""
import re
from dataclasses import replace

from app import monthly_report_library as library
from app import monthly_report_shared_conflict_ui as shared
from app.contracts import RRH_CONTRACT
from test_monthly_report_active_recovery_ui import _visit, _value, PERIOD
from test_monthly_report_identity_history_ui import widget, save
from test_monthly_report_ui import monthly


def _state(app, suffix):
    # Exactly the guided report prefix plus suffix: other guided keys also
    # end in "_draft" (for example the AI draft flag).
    return next(value for key, value in app.session_state.filtered_state.items()
                if re.fullmatch(r"report_guided_[0-9a-f]+" + re.escape(suffix), key))


def _block(draft, key):
    return next(item for item in draft.blocks if item.key == key)


def _with_text(draft, key, text):
    return replace(draft, blocks=tuple(replace(item, text=text, source="This month")
                              if item.key == key else item for item in draft.blocks))


def _remote_start(app, base):
    # The second editor starts with the same stable default/standing seeding
    # but not with the first editor's manual Activity or preparer changes.
    local = _state(app, "_draft")
    original = _block(base, "activity_summary")
    return replace(local, prepared_by=base.prepared_by,
                   blocks=tuple(original if item.key == "activity_summary" else item
                                for item in local.blocks))


def _prepare(monkeypatch, tmp_path):
    _visit(monkeypatch)
    app = monthly(monkeypatch, tmp_path)
    base = _state(app, "_shared_base").draft
    _value(app, "Prepared by", "text_input").set_value("Synthetic local editor").run()
    _value(app, "Activity summary").set_value("Locally corrected Activity").run()
    assert not app.exception
    return app, base


def test_two_editors_preserve_disjoint_activity_and_training_after_reload(monkeypatch, tmp_path):
    app, base = _prepare(monkeypatch, tmp_path)
    remote = _with_text(_remote_start(app, base), "training_summary", "Newer independently approved training note")
    saved = library.save_snapshot(remote, expected_revision=0, entered_editor="Synthetic remote")
    assert saved.revision == 1
    app.run()
    assert not app.exception
    assert not any(item.label.startswith("Resolve ") for item in app.radio)
    widget(app, "checkbox", "I compared the saved version and want to save my draft as the next version").check().run()
    widget(app, "button", "Continue with my draft").click().run()
    assert not app.exception
    merged = _state(app, "_draft")
    assert _block(merged, "activity_summary").text == "Locally corrected Activity"
    assert _block(merged, "training_summary").text == "Newer independently approved training note"
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == saved
    save(app)
    after = library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD)
    assert after.revision == 2
    assert _block(after.draft, "activity_summary").text == "Locally corrected Activity"
    assert _block(after.draft, "training_summary").text == "Newer independently approved training note"


def test_same_activity_field_must_select_exact_value_before_continuing(monkeypatch, tmp_path):
    app, base = _prepare(monkeypatch, tmp_path)
    remote = _with_text(_remote_start(app, base), "activity_summary", "Newer accepted wording")
    saved = library.save_snapshot(remote, expected_revision=0, entered_editor="Synthetic remote")
    app.run()
    choices = [item for item in app.radio if item.label == "Resolve blocks[activity_summary].text"]
    assert len(choices) == 1
    assert widget(app, "button", "Continue with my draft").disabled
    widget(app, "checkbox", "I compared the saved version and want to save my draft as the next version").check().run()
    assert widget(app, "button", "Continue with my draft").disabled
    choices = [item for item in app.radio if item.label == "Resolve blocks[activity_summary].text"]
    choices[0].set_value("Use this page value").run()
    widget(app, "button", "Continue with my draft").click().run()
    assert not app.exception
    assert _block(_state(app, "_draft"), "activity_summary").text == "Locally corrected Activity"
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == saved


def test_shared_head_advances_during_explicit_choice_without_adopting_stale_edit(monkeypatch, tmp_path):
    app, base = _prepare(monkeypatch, tmp_path)
    remote = _with_text(_remote_start(app, base), "training_summary", "First shared training update")
    first = library.save_snapshot(remote, expected_revision=0, entered_editor="Synthetic remote")
    app.run()
    widget(app, "checkbox", "I compared the saved version and want to save my draft as the next version").check().run()
    original_merge = shared.merge_drafts
    original_save = library.save_snapshot
    raced = []

    def race(*args, **kwargs):
        result = original_merge(*args, **kwargs)
        if len(args) == 4 and not raced:
            raced.append(original_save(
                _with_text(first.draft, "training_summary", "Third editor's newer update"),
                expected_revision=first.revision, entered_editor="Synthetic third"))
        return result

    monkeypatch.setattr(shared, "merge_drafts", race)
    widget(app, "button", "Continue with my draft").click().run()
    assert not app.exception and len(raced) == 1
    assert any("shared report changed again" in item.value.lower() for item in app.error)
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) == raced[0]
    assert _block(_state(app, "_draft"), "activity_summary").text == "Locally corrected Activity"
