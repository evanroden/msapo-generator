"""Cancel a saved-original review without saving or disturbing current work.

These AppTests exercise the real import/editor handoff. The source upload uses
the existing AppTest seam, not native browser file delivery.
"""

import pytest

from docx import Document

from app import monthly_report_library as library
from app.monthly_report_import import inspect_docx
from test_cover_import_task_ui import current, stage_source


def _open_saved_review(monkeypatch, tmp_path, *, keep_upload=False):
    app, source, incoming = stage_source(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Continue to this month’s updates").click().run()
    assert not app.exception
    if not keep_upload:
        incoming.clear()
        app.run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Synthetic unsaved current-report edit.").run()
    next(b for b in app.button if b.label == "Open the saved original for section review").click().run()
    assert not app.exception
    stage_key = next(key for key in app.session_state.filtered_state if key.endswith("_stage"))
    stage = app.session_state[stage_key]
    assert stage[0] is None, "This must be the saved-original path, not a temporary upload"
    assert app.session_state[stage_key.removesuffix("_stage") + "_original_review_token"]
    assert not any(e.label == "Change cover photograph" for e in app.expander)
    return app, source, stage_key, stage


@pytest.mark.parametrize("keep_upload,clear_preparer", [
    (False, False),
    (True, False),
    (False, True),
])
def test_cancel_saved_original_restores_current_cover_without_saving(
        monkeypatch, tmp_path, keep_upload, clear_preparer):
    app, source, stage_key, stage = _open_saved_review(
        monkeypatch, tmp_path, keep_upload=keep_upload)
    if clear_preparer:
        next(w for w in app.text_input if w.label == "Prepared by").set_value("").run()
        assert not app.exception
    before = current(app)
    stored = library.load_imported_draft(before.profile.contract, before.profile.key)
    original = stage[1].read_bytes()
    source_bytes = source.read_bytes()

    def forbidden_save(*args, **kwargs):
        raise AssertionError("Canceling review must not save or replace the source")

    monkeypatch.setattr(library, "save_report_setup", forbidden_save)
    cancel = next((b for b in app.button if b.label == "Cancel saved-original review"), None)
    assert cancel is not None, "A saved-original review needs a reachable explicit cancel"
    assert not cancel.disabled
    cancel.click().run()
    assert not app.exception
    assert stage_key not in app.session_state.filtered_state
    assert stage_key.removesuffix("_stage") + "_original_review_token" not in app.session_state.filtered_state
    assert any(e.label == "Change cover photograph" for e in app.expander)
    assert not any(e.label == "Cover photograph" for e in app.expander)
    assert not any("not saved until you continue" in c.value for c in app.caption)
    assert current(app) == before
    assert library.load_imported_draft(before.profile.contract, before.profile.key) == stored
    assert stage[1].read_bytes() == original
    assert source.read_bytes() == source_bytes
    for _ in range(2):
        app.run()
        assert not app.exception
        assert stage_key not in app.session_state.filtered_state
        assert current(app) == before


def test_cancel_discards_only_saved_original_review_choices_and_reopens_cleanly(monkeypatch, tmp_path):
    app, _, stage_key, stage = _open_saved_review(monkeypatch, tmp_path)
    scope = stage_key.removesuffix("_stage") + "_" + stage[2].sha256[:16] + "_"
    plans_key = scope + "section_plans"
    next(b for b in app.button if b.label == "No cover photograph").click().run()
    assert not app.exception
    assert app.session_state[plans_key]["cover"]["cover_photo_omitted"]
    before = current(app)
    cancel = next((b for b in app.button if b.label == "Cancel saved-original review"), None)
    assert cancel is not None, "Discard must not require committing the entire saved-original review"
    cancel.click().run()
    assert not app.exception
    assert not any(key.startswith(scope) for key in app.session_state.filtered_state)
    assert current(app) == before
    next(b for b in app.button if b.label == "Open the saved original for section review").click().run()
    assert not app.exception
    assert app.session_state[stage_key][0] is None
    assert not app.session_state[plans_key]["cover"].get("cover_photo_omitted")
    assert current(app) == before


def test_delayed_cancel_from_previous_original_does_not_cancel_new_source(monkeypatch, tmp_path):
    app, _, stage_key, first = _open_saved_review(monkeypatch, tmp_path)
    old_cancel = next(b for b in app.button if b.label == "Cancel saved-original review")
    second_path = tmp_path / "newer-saved-original.docx"
    document = Document(first[1])
    document.add_paragraph("Synthetic newer saved original with distinct source bytes.")
    document.save(second_path)
    second = (None, second_path, inspect_docx(second_path))
    assert second[2].sha256 != first[2].sha256
    # Model delivery of an old displayed button after another source became
    # the current review; the stale event must not act on that newer identity.
    app.session_state[stage_key] = second
    old_cancel.click().run()
    assert not app.exception
    assert stage_key in app.session_state.filtered_state
    assert app.session_state[stage_key][2].sha256 == second[2].sha256
    next(b for b in app.button if b.label == "Cancel saved-original review").click().run()
    assert not app.exception
    assert stage_key not in app.session_state.filtered_state


def test_delayed_cancel_does_not_cancel_reopened_same_original(monkeypatch, tmp_path):
    app, _, stage_key, stage = _open_saved_review(monkeypatch, tmp_path)
    old_cancel = next(b for b in app.button if b.label == "Cancel saved-original review")
    token_key = stage_key.removesuffix("_stage") + "_original_review_token"
    old_token = app.session_state[token_key]
    old_cancel.click().run()
    assert not app.exception and stage_key not in app.session_state.filtered_state
    assert token_key not in app.session_state.filtered_state
    next(b for b in app.button if b.label == "Open the saved original for section review").click().run()
    assert not app.exception
    assert app.session_state[stage_key][2].sha256 == stage[2].sha256
    assert app.session_state[token_key] != old_token
    next(b for b in app.button if b.label == "No cover photograph").click().run()
    plans_key = stage_key.removesuffix("_stage") + "_" + stage[2].sha256[:16] + "_section_plans"
    assert app.session_state[plans_key]["cover"]["cover_photo_omitted"]
    before = current(app)
    old_cancel.click().run()
    assert not app.exception
    assert stage_key in app.session_state.filtered_state, "An old cancel must not retire a new review of the same bytes"
    assert app.session_state[plans_key]["cover"]["cover_photo_omitted"]
    assert current(app) == before
    next(b for b in app.button if b.label == "Cancel saved-original review").click().run()
    assert not app.exception and stage_key not in app.session_state.filtered_state
    assert token_key not in app.session_state.filtered_state


def test_saved_original_commit_retires_token_and_keeps_mounted_upload_receipt(monkeypatch, tmp_path):
    app, _, stage_key, stage = _open_saved_review(monkeypatch, tmp_path, keep_upload=True)
    prefix = stage_key.removesuffix("_stage")
    next(b for b in app.button if b.label == "Continue to this month’s updates").click().run()
    assert not app.exception
    assert stage_key not in app.session_state.filtered_state
    assert prefix + "_original_review_token" not in app.session_state.filtered_state
    assert app.session_state[prefix + "_committed_upload_digest"] == stage[2].sha256
    app.run()
    assert not app.exception and stage_key not in app.session_state.filtered_state
