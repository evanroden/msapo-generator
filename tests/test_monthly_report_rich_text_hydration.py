"""Streamlit must not turn a hydrated saved Activity value into empty text.

A blank widget mounted before saved-draft hydration is NOT a user edit.
A user explicitly deleting text remains a valid, persistent edit.
"""
import pytest
from streamlit.testing.v1 import AppTest


APP = '''
import streamlit as st
from app.monthly_report_guided import _edit_content, _rich_text_editor_key
from app.monthly_report_model import BlockSpec, ResolvedBlock
from app.monthly_report_ui import _field
from app.monthly_report_editor import _signature

block = st.session_state.setdefault(
    "canonical_block",
    ResolvedBlock("activity_summary", "This month",
                  text="Three September work orders: 3 total, 2 completed, 1 open (66.7%)."))
spec = BlockSpec("activity_summary", "rich_text")
editor_key = _rich_text_editor_key("hydration_probe", block)
st.session_state.setdefault(editor_key, "")
result = _edit_content(spec, block, None, "hydration_probe", {}, _field)
st.session_state["result"] = result
st.session_state["canonical_block"] = result
st.session_state["editor_key"] = editor_key
'''


def test_committed_activity_text_wins_over_unedited_blank_widget_mount():
    app = AppTest.from_string(APP, default_timeout=15).run()
    assert not app.error and not app.exception
    expected = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    assert editor.value == expected
    assert app.session_state["result"].text == expected
    with pytest.raises(KeyError):
        _ = app.session_state[app.session_state["editor_key"] + "_explicitly_edited"]
    app.run()
    assert next(widget for widget in app.text_area if widget.label == "Activity summary").value == expected
    assert app.session_state["result"].text == expected


def test_explicit_clear_and_replacement_are_not_reverted_by_hydration_guard():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("").run()
    assert not app.error and not app.exception
    marker = app.session_state["editor_key"] + "_explicitly_edited"
    assert app.session_state[marker]["text"] == ""
    assert app.session_state["result"].text == ""
    app.run()
    with pytest.raises(KeyError):
        _ = app.session_state[marker]
    assert app.session_state["result"].text == ""
    editor = next(widget for widget in app.text_area if widget.label == "Activity summary")
    editor.set_value("A current, deliberate updated work-order statement.").run()
    assert app.session_state["result"].text == "A current, deliberate updated work-order statement."


def test_stale_blank_cannot_erase_a_previous_explicit_operator_edit():
    app = AppTest.from_string(APP, default_timeout=15).run()
    new_text = "Verified September pump work with a manual correction."
    next(w for w in app.text_area if w.label == "Activity summary").set_value(new_text).run()
    assert app.session_state["canonical_block"].text == new_text
    key = app.session_state["editor_key"]
    assert app.session_state[key + "_explicitly_edited"]["text"] == new_text
    # Generate/preview rerender can present a stale frontend empty widget
    # without a user callback. It must not change the authoritative draft.
    app.session_state[key] = ""
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == new_text
    assert app.session_state["canonical_block"].text == new_text


def test_unacknowledged_nonempty_widget_mismatch_does_not_overwrite_external_draft():
    app = AppTest.from_string(APP, default_timeout=15).run()
    key = app.session_state["editor_key"]
    from dataclasses import replace
    latest = "Reviewed source text arrived from another editor."
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"], text=latest)
    app.session_state[key] = "Obsolete mounted widget data."
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == latest
    assert app.session_state["canonical_block"].text == latest


def test_a_deliberate_empty_clear_and_reentry_both_stay_authoritative():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    editor.set_value("").run()
    assert app.session_state["canonical_block"].text == ""
    for _ in range(2):
        app.run()
        assert app.session_state["canonical_block"].text == ""
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Re-entered current-month work.").run()
    assert app.session_state["canonical_block"].text == "Re-entered current-month work."
    app.run()
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Re-entered current-month work.")


def test_interrupted_fragment_rerun_replays_exact_edit_until_canonical_commit():
    # The browser can emit a partial preview/fragment run after accepting the
    # textarea change but before the full draft reaches its final save point.
    # The receipt must not disappear merely because _edit_content was called.
    app_source = APP.replace(
        'st.session_state["canonical_block"] = result',
        'if st.session_state.get("commit_enabled", True):\n'
        '    st.session_state["canonical_block"] = result',
    )
    app = AppTest.from_string(app_source, default_timeout=15)
    app.session_state["commit_enabled"] = True
    app.run()
    assert not app.exception
    original = app.session_state["canonical_block"].text
    app.session_state["commit_enabled"] = False
    update = "Latest September repair before the preview interruption."
    next(w for w in app.text_area if w.label == "Activity summary").set_value(update).run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == original
    assert app.session_state["result"].text == update
    marker = app.session_state["editor_key"] + "_explicitly_edited"
    assert app.session_state[marker]["text"] == update

    # The next complete editor run must replay and commit that edit without
    # requiring a second click, and the following run acknowledges its receipt.
    app.session_state["commit_enabled"] = True
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == update
    assert next(w for w in app.text_area if w.label == "Activity summary").value == update
    app.run()
    with pytest.raises(KeyError):
        _ = app.session_state[marker]
    assert app.session_state["canonical_block"].text == update



def _interrupted_edit(text):
    source = APP.replace(
        'st.session_state["canonical_block"] = result',
        'if st.session_state.get("commit_enabled", True):\n'
        '    st.session_state["canonical_block"] = result',
    )
    app = AppTest.from_string(source, default_timeout=15).run()
    app.session_state["commit_enabled"] = False
    next(w for w in app.text_area if w.label == "Activity summary").set_value(text).run()
    assert not app.exception
    assert app.session_state["result"].text == text
    app.session_state["commit_enabled"] = True
    return app


def test_pending_edit_cannot_overwrite_newer_canonical_wording_and_is_recoverable():
    from dataclasses import replace
    interrupted = "My interrupted manual correction."
    app = _interrupted_edit(interrupted)
    latest = "A newer reviewed source correction."
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"], text=latest)
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == latest
    assert next(w for w in app.text_area if w.label == "Activity summary").value == latest
    key = app.session_state["editor_key"]
    assert app.session_state[key + "_explicitly_edited_recovery"]["text"] == interrupted
    # Recovery is an explicit new operation against the currently displayed
    # version; merely expanding/re-rendering the disclosure cannot apply it.
    app.run()
    assert app.session_state["canonical_block"].text == latest
    next(b for b in app.button if b.label == "Apply interrupted edit").click().run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == interrupted
    with pytest.raises(KeyError):
        _ = app.session_state[key + "_explicitly_edited_recovery"]


def test_interrupted_clear_does_not_erase_newer_content_and_can_be_dismissed():
    from dataclasses import replace
    app = _interrupted_edit("")
    latest = "Newer source text which must survive the old clear."
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"], text=latest)
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == latest
    assert any("cleared this section" in c.value for c in app.get("caption"))
    next(b for b in app.button if b.label == "Keep current wording").click().run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == latest
    assert not any(b.label == "Apply interrupted edit" for b in app.button)


@pytest.mark.parametrize("generation_key", [
    "hydration_probe_rich_text_epoch", "_monthly_qa_generation",
])
def test_pending_receipt_from_earlier_report_generation_cannot_repopulate_new_work(generation_key):
    app = _interrupted_edit("Old generation's interrupted text.")
    original = app.session_state["canonical_block"].text
    app.session_state[generation_key] = "new-generation"
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == original
    assert next(w for w in app.text_area if w.label == "Activity summary").value == original
    assert not any(b.label == "Apply interrupted edit" for b in app.button)
    with pytest.raises(KeyError):
        _ = app.session_state[app.session_state["editor_key"] + "_explicitly_edited"]


def test_equal_text_is_not_acknowledgment_of_an_unrelated_block_revision():
    from dataclasses import replace
    text = "A manual edit shared by both candidate versions."
    app = _interrupted_edit(text)
    newer = replace(app.session_state["canonical_block"], text=text,
                    pending_library_save=True)
    app.session_state["canonical_block"] = newer
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"] == newer
    assert app.session_state[app.session_state["editor_key"] + "_explicitly_edited_recovery"]["text"] == text


@pytest.mark.parametrize("receipt", [True, "Obsolete receipt", {"text": "Obsolete receipt"}])
def test_legacy_or_incomplete_receipt_does_not_authorize_widget_overwrite(receipt):
    app = AppTest.from_string(APP, default_timeout=15).run()
    key = app.session_state["editor_key"]
    original = app.session_state["canonical_block"].text
    app.session_state[key] = "Obsolete receipt"
    app.session_state[key + "_explicitly_edited"] = receipt
    app.run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == original
    assert next(w for w in app.text_area if w.label == "Activity summary").value == original


def _wire_value(widget_id, text):
    from streamlit.proto.WidgetStates_pb2 import WidgetStates
    message = WidgetStates()
    message.widgets.add(id=widget_id, string_value=text)
    return message


def test_native_mount_default_is_canonical_before_the_one_shot_hydration_arrives():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    expected = app.session_state["canonical_block"].text
    # Test the actual native protocol, not just AppTest's server-side value.
    # A newly mounted browser first initializes from default; another widget's
    # rerun can echo that value before set_value has reached its effect.
    assert editor.proto.default == expected
    app._run(_wire_value(editor.proto.id, editor.proto.default))
    assert not app.exception
    assert app.session_state["canonical_block"].text == expected
    assert next(w for w in app.text_area if w.label == "Activity summary").value == expected


@pytest.mark.parametrize("generation_key", ["hydration_probe_rich_text_epoch", "_monthly_qa_generation"])
def test_old_incarnation_native_clear_cannot_be_relabelled_as_new_report_input(generation_key):
    app = AppTest.from_string(APP, default_timeout=15).run()
    old = next(w for w in app.text_area if w.label == "Activity summary")
    stale_message = _wire_value(old.proto.id, "")
    expected = app.session_state["canonical_block"].text
    app.session_state[generation_key] = "new-report-incarnation"
    app.run()
    current = next(w for w in app.text_area if w.label == "Activity summary")
    assert current.proto.id != old.proto.id
    # Deliver an actual older frontend WidgetStates message after the new
    # callback has registered, not a manufactured old application receipt.
    app._run(stale_message)
    assert not app.exception
    assert app.session_state["canonical_block"].text == expected
    assert next(w for w in app.text_area if w.label == "Activity summary").value == expected
    assert not any(b.label == "Apply interrupted edit" for b in app.button)


def test_native_current_clear_and_reentry_keep_identity_and_mount_defaults_exact():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    identity = editor.proto.id
    app._run(_wire_value(identity, ""))
    assert not app.exception and app.session_state["canonical_block"].text == ""
    app.run()
    current = next(w for w in app.text_area if w.label == "Activity summary")
    assert current.proto.id == identity and current.proto.default == "" and current.value == ""
    app._run(_wire_value(identity, "A partial new sentence — still typing"))
    assert not app.exception
    app.run()
    current = next(w for w in app.text_area if w.label == "Activity summary")
    assert current.proto.id == identity
    assert current.proto.default == current.value == app.session_state["canonical_block"].text == "A partial new sentence — still typing"


def test_initial_journal_and_preview_reruns_do_not_change_native_editor_identity():
    app = AppTest.from_string(APP, default_timeout=15).run()
    identity = next(w for w in app.text_area if w.label == "Activity summary").proto.id
    app.session_state["hydration_probe_active_generation"] = "durable-journal-initialized"
    app.session_state["hydration_probe_active_sequence"] = 4
    app.run()
    assert next(w for w in app.text_area if w.label == "Activity summary").proto.id == identity


@pytest.mark.parametrize("widget_state", [{}, {"editor": None}, {"editor": 0}])
def test_missing_or_nontext_widget_callback_cannot_authorize_clear(monkeypatch, widget_state):
    from types import SimpleNamespace
    from app import monthly_report_guided as guided
    from app.monthly_report_model import ResolvedBlock
    state = dict(widget_state)
    monkeypatch.setattr(guided, "st", SimpleNamespace(session_state=state))
    block = ResolvedBlock("activity_summary", "This month", text="Keep my current wording.")
    guided._mark_explicit_rich_text_edit("receipt", "editor", block, "current-scope")
    assert "receipt" not in state
    # An unrelated missing callback must also retain a previously delivered
    # recoverable receipt instead of replacing it with a fabricated clear.
    pending = {"text": "An interrupted sentence", "scope": "current-scope"}
    state["receipt"] = pending
    guided._mark_explicit_rich_text_edit("receipt", "editor", block, "current-scope")
    assert state["receipt"] is pending


def test_synthetic_activity_callback_diagnostics_are_bounded_hashes_only(monkeypatch):
    from hashlib import sha256
    from types import SimpleNamespace
    from app import monthly_report_guided as guided
    from app.monthly_report_model import ResolvedBlock
    state = {"_monthly_report_storage_mode": "isolated"}
    monkeypatch.setattr(guided, "st", SimpleNamespace(session_state=state))
    block = ResolvedBlock("activity_summary", "This month", text="Synthetic baseline")
    for number in range(12):
        state["editor"] = f"Synthetic edit {number}"
        guided._mark_explicit_rich_text_edit("receipt", "editor", block, "synthetic-scope")
    events = state["monthly_qa_activity_callbacks"]
    assert len(events) == 8
    assert events[0]["after"] == sha256(b"Synthetic edit 4").hexdigest()
    assert events[-1]["after"] == sha256(b"Synthetic edit 11").hexdigest()
    assert events[-1]["before"] == sha256(block.text.encode()).hexdigest()
    assert set(events[-1]) == {"widget", "scope", "baseline", "before", "after"}
    assert "Synthetic" not in str(events)


@pytest.mark.parametrize("mode", [None, "live", "fixtures"])
def test_ordinary_and_shared_fixture_edits_do_not_emit_synthetic_diagnostics(monkeypatch, mode):
    from types import SimpleNamespace
    from app import monthly_report_guided as guided
    from app.monthly_report_model import ResolvedBlock
    state = {"_monthly_report_storage_mode": mode, "editor": "Current wording"}
    monkeypatch.setattr(guided, "st", SimpleNamespace(session_state=state))
    block = ResolvedBlock("activity_summary", "This month", text="Previous wording")
    guided._mark_explicit_rich_text_edit("receipt", "editor", block, "current-scope")
    assert state["receipt"]["text"] == "Current wording"
    assert "monthly_qa_activity_callbacks" not in state


def test_interrupted_edit_conflict_is_visible_inline_with_both_explicit_choices():
    # A warning cannot be hidden behind an unopened disclosure: the operator
    # must see the currently retained text and the uncommitted old replacement
    # beside the affected Activity editor after a normal rerun.
    from dataclasses import replace
    old_edit = "Synthetic earlier interrupted work."
    current = "Synthetic newer reviewed Activity description."
    app = _interrupted_edit(old_edit)
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"], text=current)
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == current
    marker = app.session_state["editor_key"] + "_explicitly_edited_recovery"
    assert app.session_state[marker]["text"] == old_edit
    assert not any(e.label == "Review interrupted edit" for e in app.expander)
    assert any("Current wording (kept in this report)" in e.value for e in app.markdown)
    assert any("Interrupted wording (not applied)" in e.value for e in app.markdown)
    assert any("nothing has been overwritten" in e.value for e in app.warning)
    assert {b.label for b in app.button} >= {"Apply interrupted edit", "Keep current wording"}
    app.run()
    assert app.session_state[marker]["text"] == old_edit
    assert app.session_state["canonical_block"].text == current
    # The explicit current-version choice dismisses only this pending conflict.
    next(b for b in app.button if b.label == "Keep current wording").click().run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == current
    assert not any(b.label == "Apply interrupted edit" for b in app.button)


def test_interrupted_clear_displays_intent_inline_without_autoapplying():
    from dataclasses import replace
    app = _interrupted_edit("")
    app.session_state["canonical_block"] = replace(
        app.session_state["canonical_block"],
        text="Newer synthetic Activity that must remain.")
    app.run()
    assert not app.exception
    assert not any(e.label == "Review interrupted edit" for e in app.expander)
    assert any("interrupted edit cleared the section" in e.value for e in app.caption)
    assert app.session_state["canonical_block"].text == "Newer synthetic Activity that must remain."
    next(b for b in app.button if b.label == "Apply interrupted edit").click().run()
    assert not app.exception
    assert app.session_state["canonical_block"].text == ""
