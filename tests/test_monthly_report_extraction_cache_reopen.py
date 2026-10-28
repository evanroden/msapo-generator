"""Native guided reopen rebuilds disposable cache data without replaying edits.

AppTest exercises native widget messages and the actual disk recovery path;
served-browser timing and Word/PDF acceptance remain separate release gates.
"""
from io import BytesIO

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active_work
from app import monthly_report_library as library
from app import monthly_report_sources as sources
from test_monthly_report_activity_intake_commit import (
    APP, TOKEN, activity, draft, editor, setup_app,
)


@pytest.mark.parametrize("manual", ["Human reviewed wording.\n\nKeep the pending inspection.", ""])
@pytest.mark.parametrize("damaged_cache", [b'{"schema":1,"tables":[]}', b'{"schema":', None],
                         ids=["missing-source", "invalid-json", "healthy"])
def test_native_reopen_recovers_tables_and_sibling_without_changing_delivered_work(
        monkeypatch, tmp_path, manual, damaged_cache):
    app, profile = setup_app(monkeypatch, tmp_path)
    originals = (
        ("synthetic-observations.csv", b"Asset,Observation\nP-64,Seal inspection pending\n"),
        ("synthetic-maintenance report.txt", b"Technician inspected reserve fan F-82.\n"),
    )
    original_uploader = st.file_uploader

    def upload(label, *args, **kwargs):
        if label == "Add source files":
            uploads = []
            for filename, raw in originals:
                stream = BytesIO(raw)
                stream.name = filename
                uploads.append(stream)
            return uploads
        return original_uploader(label, *args, **kwargs)

    monkeypatch.setattr(st, "file_uploader", upload)
    app.run()
    assert not app.exception
    assert len(draft(app).sources) == 2, "The native upload must actually accept both originals."
    monkeypatch.setattr(st, "file_uploader", original_uploader)
    editor(app).set_value(manual).run()
    assert not app.exception and activity(app).text == manual
    saved_draft = draft(app)
    saved = active_work.load(TOKEN, profile.contract, profile.key, saved_draft.period)
    assert saved and saved.draft == saved_draft
    journal_path = active_work._directory(
        TOKEN, profile.contract, profile.key, saved_draft.period) / "working.json"
    journal_bytes = journal_path.read_bytes()
    cache_paths = tuple(sources._path(profile, source.sha256, ".json")
                        for source in saved_draft.sources)
    healthy_cache = cache_paths[1].read_bytes()
    original_paths = tuple(sources._path(profile, source.sha256, source.suffix)
                           for source in saved_draft.sources)
    original_state = tuple((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                           for path in original_paths)
    if damaged_cache is not None:
        cache_paths[0].write_bytes(damaged_cache)

    reopened = AppTest.from_string(APP, default_timeout=45).run()
    assert not reopened.exception
    assert draft(reopened) == saved_draft
    assert activity(reopened).text == manual and editor(reopened).value == manual
    state = reopened.session_state.filtered_state
    draft_keys = [key for key, value in state.items()
                  if key.startswith("report_guided_") and key.endswith("_draft")
                  and value == saved_draft]
    assert len(draft_keys) == 1
    evidence = state[draft_keys[0].removesuffix("_draft") + "_evidence"]
    assert tuple(content.source for content in evidence) == saved_draft.sources
    assert evidence[0].tables[0].columns == ("Asset", "Observation")
    assert evidence[0].tables[0].rows == (("P-64", "Seal inspection pending"),)
    assert not any("Could not read saved file" in item.value for item in reopened.warning)
    if damaged_cache is not None:
        assert cache_paths[0].read_bytes() != damaged_cache
    assert cache_paths[1].read_bytes() == healthy_cache
    assert tuple((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns)
                 for path in original_paths) == original_state
    assert journal_path.read_bytes() == journal_bytes
    assert active_work.load(TOKEN, profile.contract, profile.key, saved_draft.period) == saved
    assert library.load_snapshot(profile.contract, profile.key, saved_draft.period) is None

    # A second new session uses the healthy rebuilt cache, with no extra source
    # extraction or duplicate reapplication of the native upload's wording.
    monkeypatch.setattr(sources, "_spreadsheet", lambda *a: pytest.fail("Healthy cache was reparsed."))
    again = AppTest.from_string(APP, default_timeout=45).run()
    assert not again.exception and draft(again) == saved_draft
    assert editor(again).value == manual
