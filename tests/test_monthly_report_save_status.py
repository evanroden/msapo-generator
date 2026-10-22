"""Save acknowledgment never removes and reinserts space above native editors."""

from streamlit.delta_generator import DeltaGenerator

from app import monthly_report_active_work as active, monthly_report_library as library
from test_monthly_report_ui import monthly


TOKEN = "c" * 32


def _status(app):
    return [item.value for item in app.markdown if 'class="enfra-browser-save-status"' in item.value]


def _field(app):
    return next(item for item in app.text_area if item.label == "Activity summary")


def test_status_delta_path_stays_text_during_native_edit_full_render(monkeypatch, tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: TOKEN)
    app = monthly(monkeypatch, tmp_path)
    original = DeltaGenerator._enqueue
    messages = []

    def observed(self, delta_type, element_proto, *args, **kwargs):
        result = original(self, delta_type, element_proto, *args, **kwargs)
        messages.append((tuple(result._cursor.delta_path), delta_type,
                         getattr(element_proto, "body", "")))
        return result

    monkeypatch.setattr(DeltaGenerator, "_enqueue", observed)
    _field(app).set_value("Synthetic caption-adjacent work remains in place.").run()
    assert not app.exception
    status_paths = {path for path, _, body in messages if 'enfra-browser-save-status' in body or
                    'Current edits kept for this browser' in body}
    assert len(status_paths) == 1
    transitions = [(kind, body) for path, kind, body in messages if path in status_paths]
    assert all(kind == "markdown" for kind, _ in transitions), transitions
    assert 'Saving changes…' in transitions[0][1]
    assert 'Browser draft<br>Last saved' in transitions[-1][1]
    assert len(_status(app)) == 1


def test_status_uses_persisted_time_and_noop_does_not_claim_new_save(monkeypatch, tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: TOKEN)
    monkeypatch.setattr(library, "_now", lambda: "2026-10-17T22:45:01+00:00")
    app = monthly(monkeypatch, tmp_path)
    _field(app).set_value("Synthetic acknowledged content.").run()
    saved = _status(app)
    assert len(saved) == 1 and "Browser draft<br>Last saved · 22:45 UTC" in saved[0]
    assert 'title="2026-10-17T22:45:01+00:00"' in saved[0]
    monkeypatch.setattr(library, "_now", lambda: "2026-10-17T23:50:02+00:00")
    app.run()
    assert _status(app) == saved
    assert not any(item.label == "Retry browser save" for item in app.button)


def test_failed_save_has_one_explicit_retry_preserving_text_and_shared_history(monkeypatch, tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: TOKEN)
    app = monthly(monkeypatch, tmp_path)
    original = active.save
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        raise OSError("Synthetic unavailable journal")

    monkeypatch.setattr(active, "save", broken)
    _field(app).set_value("Synthetic unsaved human work.").run()
    assert not app.exception
    assert len(calls) == 1
    assert "Save failed" in _status(app)[0]
    assert "Last saved" not in _status(app)[0]
    assert any("not saved for a refresh" in item.value for item in app.error)
    next(item for item in app.button if item.label == "Retry browser save").click().run()
    assert len(calls) == 2, "one deliberate failed retry is one persistence attempt"
    monkeypatch.setattr(active, "save", original)
    next(item for item in app.button if item.label == "Retry browser save").click().run()
    assert not app.exception
    assert _field(app).value == "Synthetic unsaved human work."
    assert "Browser draft<br>Last saved" in _status(app)[0]
    assert not any(item.label == "Retry browser save" for item in app.button)
    draft = next(value for key, value in app.session_state.filtered_state.items()
                 if key.endswith("_draft") and hasattr(value, "blocks"))
    assert active.load(TOKEN, draft.profile.contract, draft.profile.key, draft.period).draft == draft
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_missing_or_invalid_timestamp_is_not_fabricated():
    from app.monthly_report_save_status import _saved_time
    for value in (None, "", "not a timestamp", "2026-10-17T22:45:01"):
        assert _saved_time(value) == "Time unavailable"
    assert _saved_time("2026-10-17T17:45:01-05:00") == "22:45 UTC"
