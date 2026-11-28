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
    scope = app.session_state[stage_key.removesuffix("_stage") + "_active_section_review"][1] + "_"
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
    plans_key = app.session_state[stage_key.removesuffix("_stage") + "_active_section_review"][1] + "_section_plans"
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


@pytest.mark.parametrize('cleanup_fails', [False, True])
@pytest.mark.parametrize('failed_replacement', [False, True])
def test_first_use_sidebar_original_retires_pending_entry_before_review(monkeypatch, tmp_path, cleanup_fails, failed_replacement):
    from app.monthly_report_entry_upload import ENTRY_STAGE
    from io import BytesIO
    app, source, incoming = stage_source(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == 'Continue to this month’s updates').click().run()
    assert not app.exception
    incoming.clear()
    app.run()
    pending = BytesIO()
    incoming_doc = Document(source)
    incoming_doc.add_paragraph('Different pending synthetic file, never committed.')
    incoming_doc.save(pending)
    pending.seek(0)
    pending.name, pending.size = 'pending-source.docx', len(pending.getvalue())
    incoming['Starting report'] = pending
    app.run()
    assert not app.exception
    assert ENTRY_STAGE in app.session_state.filtered_state
    stage = app.session_state[ENTRY_STAGE]
    assert stage[0] is not None
    if failed_replacement:
        malformed = BytesIO(b'not a Word package')
        malformed.name, malformed.size = 'malformed.docx', len(malformed.getvalue())
        incoming['Starting report'] = malformed
        app.run()
        assert not app.exception
        assert app.session_state[ENTRY_STAGE] is stage
        assert 'report_entry_failed_digest' in app.session_state.filtered_state
    if cleanup_fails:
        def failed_cleanup():
            raise OSError('Synthetic temporary cleanup failure')
        monkeypatch.setattr(stage[0], 'cleanup', failed_cleanup)
    before = current(app)
    stored = library.load_imported_draft(before.profile.contract, before.profile.key)
    original = library.imported_original(before.profile.contract, before.profile.key).read_bytes()
    action = next(b for b in app.sidebar.button if b.label == 'Open the saved original for section review')
    from app import monthly_report_import as importer
    real_inspect = importer.inspect_docx
    def rejected_original(path):
        if path == library.imported_original(before.profile.contract, before.profile.key):
            raise ValueError('Synthetic unreadable saved original')
        return real_inspect(path)
    monkeypatch.setattr(importer, 'inspect_docx', rejected_original)
    epoch = app.session_state.filtered_state.get('report_entry_upload_epoch', 0)
    action.click().run()
    assert not app.exception
    assert app.session_state[ENTRY_STAGE] is stage
    assert stage[1].exists()
    assert app.session_state.filtered_state.get('report_entry_upload_epoch', 0) == epoch
    assert current(app) == before
    monkeypatch.setattr(importer, 'inspect_docx', real_inspect)
    action = next(b for b in app.sidebar.button if b.label == 'Open the saved original for section review')
    # Model the native upload identity: the pending bytes stay mounted until
    # the product rotates the first-use picker, then the new picker is empty.
    from app import monthly_report_section_ui as section_ui
    upload = section_ui.st.file_uploader
    def keyed_upload(label, *args, **kwargs):
        if (str(kwargs.get('key', '')).startswith('report_entry_upload_v')
                or str(kwargs.get('key', '')).startswith('report_setup_')):
            return None
        return upload(label, *args, **kwargs)
    monkeypatch.setattr(section_ui.st, 'file_uploader', keyed_upload)
    action.click().run()
    assert not app.exception
    assert ENTRY_STAGE not in app.session_state.filtered_state
    assert 'report_entry_failed_digest' not in app.session_state.filtered_state
    assert stage[1].exists() is cleanup_fails
    if cleanup_fails:
        assert any('temporary copy could not be cleaned up' in w.value for w in app.warning)
    saved_stage = next(value for key, value in app.session_state.filtered_state.items()
                       if key.startswith('report_setup_') and key.endswith('_stage'))
    assert saved_stage[0] is None
    assert any(b.label == 'Cancel saved-original review' for b in app.button)
    assert current(app) == before
    next(b for b in app.button if b.label == 'Cancel saved-original review').click().run()
    assert not app.exception
    assert not any(b.label == 'Cancel saved-original review' for b in app.button)
    assert current(app) == before
    assert library.load_imported_draft(before.profile.contract, before.profile.key) == stored
    assert library.imported_original(before.profile.contract, before.profile.key).read_bytes() == original


def test_failed_entry_without_stage_rotates_picker_when_saved_original_opens(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    app, source, incoming = stage_source(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == 'Continue to this month’s updates').click().run()
    draft = current(app)
    stored = library.load_imported_draft(draft.profile.contract, draft.profile.key)
    raw = library.imported_original(draft.profile.contract, draft.profile.key).read_bytes()
    recovered = AppTest.from_string('''
import hashlib
from io import BytesIO
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
state = library.load_profile(st.session_state['contract'], st.session_state['profile'])
upload = None
if not st.session_state.get('report_entry_upload_epoch'):
    upload = BytesIO(b'not a Word package')
    st.session_state['report_entry_failed_digest'] = hashlib.sha256(upload.getvalue()).hexdigest()
    st.session_state['report_entry_failed_notice'] = 'Synthetic rejected first-use file'
render_section_setup(state.profile.contract, st.session_state['period'], 'Synthetic Editor', _field,
    state=state, identity=state.profile, working_draft=st.session_state['working'],
    entry_active=True, entry_upload=upload)
''', default_timeout=30)
    recovered.session_state['contract'] = draft.profile.contract
    recovered.session_state['profile'] = draft.profile.key
    recovered.session_state['period'] = draft.period
    recovered.session_state['working'] = draft
    recovered.run()
    assert not recovered.exception
    assert 'report_entry_stage' not in recovered.session_state.filtered_state
    assert 'report_entry_failed_digest' in recovered.session_state.filtered_state
    next(b for b in recovered.sidebar.button if b.label == 'Open the saved original for section review').click().run()
    assert not recovered.exception
    assert recovered.session_state['report_entry_upload_epoch'] == 1
    assert 'report_entry_failed_digest' not in recovered.session_state.filtered_state
    assert 'report_entry_failed_notice' not in recovered.session_state.filtered_state
    assert any(b.label == 'Cancel saved-original review' for b in recovered.button)
    assert recovered.session_state['working'] == draft
    assert library.load_imported_draft(draft.profile.contract, draft.profile.key) == stored
    assert library.imported_original(draft.profile.contract, draft.profile.key).read_bytes() == raw
