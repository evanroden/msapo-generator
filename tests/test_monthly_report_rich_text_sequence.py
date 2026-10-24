"""Native successive edits/actions bind the shown revision without a spare rerun."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from test_monthly_report_rich_text_hydration import APP


def editor(app):
    return next(w for w in app.text_area if w.label == "Activity summary")


def button(app, label):
    return next(w for w in app.button if w.label == label)


def assert_wording(app, text):
    assert not app.exception
    assert app.session_state["canonical_block"].text == editor(app).value == text
    assert not any("earlier edit was interrupted" in w.value for w in app.warning)


@pytest.mark.parametrize("acknowledge_rerun", [False, True])
def test_native_edit_clear_reentry_uses_current_revision_without_extra_stabilization(acknowledge_rerun):
    app = AppTest.from_string(APP, default_timeout=15).run()
    identity = editor(app).proto.id
    editor(app).set_value("An acknowledged September correction.").run()
    assert_wording(app, "An acknowledged September correction.")
    if acknowledge_rerun:
        app.run()
    button(app, "Clear Activity for this report").click().run()
    assert_wording(app, "")
    editor(app).set_value("Reentered work after deliberate clear.").run()
    assert_wording(app, "Reentered work after deliberate clear.")
    editor(app).set_value("A second consecutive correction.").run()
    assert_wording(app, "A second consecutive correction.")
    assert editor(app).proto.id == identity
    app.run()
    assert_wording(app, "A second consecutive correction.")


def test_native_clear_same_event_retains_delivered_text_in_scoped_undo():
    app = AppTest.from_string(APP, default_timeout=15).run()
    original = app.session_state["canonical_block"]
    editor(app).set_value("Text delivered by the native Clear click.")
    button(app, "Clear Activity for this report").click().run()
    assert_wording(app, "")
    button(app, "Undo Clear Activity").click().run()
    assert_wording(app, "Text delivered by the native Clear click.")
    result = app.session_state["canonical_block"]
    assert result.references == original.references and result.asset_hashes == original.asset_hashes
    app.run()
    assert_wording(app, "Text delivered by the native Clear click.")


def test_successive_edits_survive_interrupted_canonical_commit_before_clear_and_undo():
    source = APP.replace(
        'st.session_state["canonical_block"] = result',
        'if st.session_state.get("commit_enabled", True):\n'
        '    st.session_state["canonical_block"] = result',
    )
    app = AppTest.from_string(source, default_timeout=15).run()
    original = app.session_state["canonical_block"]
    app.session_state["commit_enabled"] = False
    editor(app).set_value("First delivered edit before commit.").run()
    editor(app).set_value("Second delivered edit before commit.").run()
    assert app.session_state["result"].text == "Second delivered edit before commit."
    assert app.session_state["canonical_block"] == original
    button(app, "Clear Activity for this report").click().run()
    assert app.session_state["result"].text == ""
    assert app.session_state["canonical_block"] == original
    app.session_state["commit_enabled"] = True
    app.run()
    assert_wording(app, "")
    button(app, "Undo Clear Activity").click().run()
    assert_wording(app, "Second delivered edit before commit.")


def test_clear_and_undo_do_not_replace_unseen_newer_revision():
    app = AppTest.from_string(APP, default_timeout=15).run()
    editor(app).set_value("The first session's current wording.").run()
    newer = replace(app.session_state["canonical_block"], text="New wording from another editing session.")
    app.session_state["canonical_block"] = newer
    button(app, "Clear Activity for this report").click().run()
    assert not app.exception
    assert app.session_state["canonical_block"] == newer
    assert editor(app).value == newer.text
    assert any("earlier edit was interrupted" in w.value for w in app.warning)
    marker = app.session_state["editor_key"] + "_explicitly_edited"
    assert app.session_state[marker + "_recovery"]["text"] == ""
    assert {c.value for c in app.code} >= {newer.text, "The first session's current wording."}
    assert not any(b.label == "Undo Clear Activity" and not b.disabled for b in app.button)
    button(app, "Apply interrupted edit").click().run()
    assert_wording(app, "")
    button(app, "Undo Clear Activity").click().run()
    assert_wording(app, newer.text)


@pytest.mark.parametrize("boundary", ["wording", "epoch", "qa_generation"])
def test_undo_clear_is_bound_to_cleared_revision_and_report_incarnation(boundary):
    app = AppTest.from_string(APP, default_timeout=15).run()
    button(app, "Clear Activity for this report").click().run()
    assert_wording(app, "")
    undo = button(app, "Undo Clear Activity")
    if boundary == "wording":
        current = replace(app.session_state["canonical_block"], text="New current wording.")
        app.session_state["canonical_block"] = current
    elif boundary == "epoch":
        app.session_state["hydration_probe_rich_text_epoch"] = "new-incarnation"
        current = app.session_state["canonical_block"]
    else:
        app.session_state["_monthly_qa_generation"] = "new-generation"
        current = app.session_state["canonical_block"]
    # A real old native trigger after the report changes must not apply Undo.
    undo.click().run()
    assert not app.exception
    assert app.session_state["canonical_block"] == current


def test_undo_does_not_discard_text_delivered_by_the_same_native_click():
    app = AppTest.from_string(APP, default_timeout=15).run()
    button(app, "Clear Activity for this report").click().run()
    editor(app).set_value("New text typed after Clear and delivered with Undo.")
    button(app, "Undo Clear Activity").click().run()
    assert_wording(app, "New text typed after Clear and delivered with Undo.")


def test_undo_clear_never_resurrects_after_deliberate_later_edits_return_to_empty():
    app = AppTest.from_string(APP, default_timeout=15).run()
    button(app, "Clear Activity for this report").click().run()
    assert any(b.label == "Undo Clear Activity" for b in app.button)
    editor(app).set_value("Later deliberate human wording.").run()
    assert_wording(app, "Later deliberate human wording.")
    editor(app).set_value("").run()
    assert_wording(app, "")
    assert not any(b.label == "Undo Clear Activity" for b in app.button)
    app.run()
    assert_wording(app, "")
    assert not any(b.label == "Undo Clear Activity" for b in app.button)


JOURNAL_APP = '''
import streamlit as st
from dataclasses import replace
from app import monthly_report_active_work as active
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import BlockSpec, ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
DEVICE = "a" * 32
initial = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
initial = replace(initial, blocks=(*initial.blocks,
    ResolvedBlock("activity_summary", "This month", text="Initial synthetic monthly Activity.")))
if "draft" not in st.session_state:
    loaded = active.load(DEVICE, initial.profile.contract, initial.profile.key, initial.period)
    st.session_state["draft"] = loaded.draft if loaded else initial
    st.session_state["revision"] = loaded.revision if loaded else 0
    st.session_state["generation"] = loaded.generation if loaded else ""
draft = st.session_state["draft"]
block = next(item for item in draft.blocks if item.key == "activity_summary")
result = _edit_content(BlockSpec("activity_summary", "rich_text"), block, None, "journal", {}, _field)
draft = replace(draft, blocks=tuple(result if item.key == result.key else item for item in draft.blocks))
st.session_state["draft"] = draft
try:
    saved = active.save(DEVICE, draft, expected_revision=st.session_state["revision"],
        expected_generation=st.session_state["generation"], base_snapshot_revision=0)
    st.session_state["revision"] = saved.revision
    st.session_state["generation"] = saved.generation
    st.caption("Saved in this browser")
except active.ActiveWorkConflict:
    st.error("Another tab has newer saved work. Your current wording remains here.")
except OSError:
    st.error("Could not keep this edit for recovery. Your current wording remains here.")
'''


def durable(app):
    from app import monthly_report_active_work as active
    draft = app.session_state["draft"]
    return active.load("a" * 32, draft.profile.contract, draft.profile.key, draft.period)


def test_acknowledged_edit_clear_undo_reentry_persist_exactly_and_reload(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    assert not app.exception
    original = app.session_state["draft"]
    editor(app).set_value("Saved September Activity before Clear.").run()
    assert not app.error and not app.exception
    assert any(c.value == "Saved in this browser" for c in app.caption)
    before_clear = durable(app)
    assert before_clear.draft.fingerprint == app.session_state["draft"].fingerprint
    button(app, "Clear Activity for this report").click().run()
    assert not app.error and not app.exception
    assert editor(app).value == ""
    cleared = durable(app)
    assert cleared.revision == before_clear.revision + 1
    assert cleared.draft.fingerprint == app.session_state["draft"].fingerprint
    button(app, "Undo Clear Activity").click().run()
    assert editor(app).value == "Saved September Activity before Clear."
    editor(app).set_value("Final September Activity after Undo.").run()
    assert not app.error and not app.exception
    current = durable(app)
    assert current.draft.fingerprint == app.session_state["draft"].fingerprint
    assert {b.key: b for b in current.draft.blocks if b.key != "activity_summary"} == {
        b.key: b for b in original.blocks if b.key != "activity_summary"}
    reloaded = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    assert not reloaded.error and not reloaded.exception
    assert editor(reloaded).value == "Final September Activity after Undo."
    assert durable(reloaded).revision == current.revision


def test_accepted_interrupted_clear_then_immediate_reentry_uses_cleared_revision(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    editor(app).set_value("Earlier wording still bound to the Clear button.").run()
    before = durable(app)
    # Establish a legitimate changed canonical version after the last widget
    # render. The native stale Clear must first require explicit recovery.
    changed = replace(before.draft, blocks=tuple(
        replace(block, text="Newer canonical wording to compare.") if block.key == "activity_summary" else block
        for block in before.draft.blocks))
    newer = active.save("a" * 32, changed, expected_revision=before.revision,
        expected_generation=before.generation, base_snapshot_revision=0)
    app.session_state["draft"] = changed
    app.session_state["revision"] = newer.revision
    button(app, "Clear Activity for this report").click().run()
    assert not app.exception
    assert any("earlier edit was interrupted" in item.value for item in app.warning)
    assert editor(app).value == "Newer canonical wording to compare."
    assert durable(app).draft == changed
    button(app, "Apply interrupted edit").click().run()
    assert not app.exception and not app.error
    assert editor(app).value == ""
    cleared = durable(app)
    assert cleared.draft.fingerprint == app.session_state["draft"].fingerprint
    editor(app).set_value("Immediate new wording after accepting the interrupted Clear.").run()
    assert not app.exception and not app.error
    assert not any("earlier edit was interrupted" in item.value for item in app.warning)
    kept = durable(app)
    assert kept.revision == cleared.revision + 1
    assert kept.draft.fingerprint == app.session_state["draft"].fingerprint
    reopened = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    assert editor(reopened).value == "Immediate new wording after accepting the interrupted Clear."


def test_two_independent_native_sessions_reject_stale_clear_and_keep_both_versions(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    first = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    second = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    assert not first.exception and not second.exception
    editor(first).set_value("Newer saved work from the first session.").run()
    newest = durable(first)
    editor(second).set_value("Other human work delivered with stale Clear.")
    button(second, "Clear Activity for this report").click().run()
    assert not second.exception
    assert any("Another tab" in e.value for e in second.error)
    assert durable(second) == newest
    assert editor(second).value == ""
    # Undo restores the second session's own delivered work locally; it still
    # cannot overwrite the first session's newer durable revision.
    button(second, "Undo Clear Activity").click().run()
    assert editor(second).value == "Other human work delivered with stale Clear."
    assert any("Another tab" in e.value for e in second.error)
    assert durable(second) == newest
    reloaded = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    assert editor(reloaded).value == "Newer saved work from the first session."


def test_failed_save_keeps_delivered_edit_and_clear_undo_retries_without_duplicates(monkeypatch, tmp_path):
    from app import monthly_report_active_work as active
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(JOURNAL_APP, default_timeout=15).run()
    initial = durable(app)
    original_save = active.save
    def fail(*args, **kwargs):
        raise OSError("Synthetic recovery write failure")
    monkeypatch.setattr(active, "save", fail)
    editor(app).set_value("Locally recoverable work during failed persistence.").run()
    assert editor(app).value == "Locally recoverable work during failed persistence."
    assert any("Could not keep" in e.value for e in app.error)
    button(app, "Clear Activity for this report").click().run()
    assert editor(app).value == ""
    button(app, "Undo Clear Activity").click().run()
    assert editor(app).value == "Locally recoverable work during failed persistence."
    assert durable(app) == initial
    monkeypatch.setattr(active, "save", original_save)
    app.run()
    assert not app.error and not app.exception
    saved = durable(app)
    assert saved.revision == initial.revision + 1
    assert saved.draft.fingerprint == app.session_state["draft"].fingerprint
    app.run()
    assert durable(app).revision == saved.revision


def test_whole_monthly_workspace_edit_clear_reentry_needs_no_extra_rerun(monkeypatch, tmp_path):
    from test_monthly_report_ui import monthly
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    identity = editor(app).proto.id
    editor(app).set_value("Native work in the full Monthly workspace.").run()
    assert not app.exception and not app.error
    button(app, "Clear Activity for this report").click().run()
    assert not app.exception and not app.error
    assert editor(app).value == ""
    assert not any("earlier edit was interrupted" in w.value for w in app.warning)
    editor(app).set_value("Reentered work in the same Monthly workspace.").run()
    assert not app.exception and not app.error
    assert editor(app).value == "Reentered work in the same Monthly workspace."
    assert editor(app).proto.id == identity
    assert not any("earlier edit was interrupted" in w.value for w in app.warning)
    app.run()
    assert editor(app).value == "Reentered work in the same Monthly workspace."
