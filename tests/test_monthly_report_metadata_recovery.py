"""Damaged synthetic metadata stays recoverable without replacing saved work."""

from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


PERIOD = ReportPeriod(2026, 9)
TOKEN = "e" * 32
UNREADABLE = "Saved report data could not be read; existing data was preserved."
INVALID_METADATA = (
    pytest.param(b'{"schema":1,"revision":' + b"9" * 4301 + b"}", ValueError,
                 id="integer-conversion-limit"),
    pytest.param(b'{"schema":1,"nested":' + b"[" * 10000 + b"0" + b"]" * 10000 + b"}",
                 RecursionError, id="nested-array-limit"),
    pytest.param(b'{"schema":1,"nested":' + b'{"x":' * 10000 + b"0" + b"}" * 10001,
                 RecursionError, id="nested-object-limit"),
)


@pytest.fixture
def draft(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_draft(synthetic_profiles()[0], PERIOD)


def stored_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("raw,cause", INVALID_METADATA)
def test_decoder_limits_become_recoverable_library_errors(draft, tmp_path, raw, cause):
    path = tmp_path / "damaged.json"
    path.write_bytes(raw)
    with pytest.raises(library.LibraryError, match=UNREADABLE) as raised:
        library._read_with_bytes(path)
    assert type(raised.value.__cause__) is cause
    assert path.read_bytes() == raw


@pytest.mark.parametrize("raw", [b"{broken", b'{"schema":1,"name":"\xff"}'])
def test_existing_invalid_json_and_encoding_recovery_is_unchanged(draft, tmp_path, raw):
    path = tmp_path / "unreadable.json"
    path.write_bytes(raw)
    with pytest.raises(library.LibraryError, match=UNREADABLE):
        library._read(path)
    assert path.read_bytes() == raw


@pytest.mark.parametrize("raw", [b'{"schema":2}', b"[]"])
def test_unsupported_schema_keeps_its_specific_error(draft, tmp_path, raw):
    path = tmp_path / "foreign-schema.json"
    path.write_bytes(raw)
    with pytest.raises(library.LibraryError, match="Unsupported report storage schema") as raised:
        library._read(path)
    assert raised.value.__cause__ is None
    assert path.read_bytes() == raw


def test_oversized_metadata_keeps_its_specific_limit_without_reading(draft, tmp_path, monkeypatch):
    path = tmp_path / "oversized.json"
    with path.open("wb") as output:
        output.seek(library.MAX_JSON_BYTES)
        output.write(b" ")
    original_read = Path.read_bytes

    def guarded_read(candidate):
        assert candidate != path, "An already oversized file must not be read."
        return original_read(candidate)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(library.LibraryError, match="Saved report metadata exceeds the storage limit") as raised:
        library._read(path)
    assert raised.value.__cause__ is None
    assert path.stat().st_size == library.MAX_JSON_BYTES + 1


def test_missing_metadata_uses_existing_read_error(draft, tmp_path):
    with pytest.raises(library.LibraryError, match=UNREADABLE) as raised:
        library._read(tmp_path / "absent.json")
    assert isinstance(raised.value.__cause__, FileNotFoundError)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_valid_metadata_returns_exact_original_bytes(draft, tmp_path, encoding):
    raw = ' {"schema": 1, "name": "Synthetic café", "values": [0, 17, {"kept": true}]}\n'.encode(encoding)
    path = tmp_path / "valid.json"
    path.write_bytes(raw)
    value, original = library._read_with_bytes(path)
    assert value == {"schema": 1, "name": "Synthetic café", "values": [0, 17, {"kept": True}]}
    assert original == raw == path.read_bytes()


HISTORY_APP = '''
import streamlit as st
from app.monthly_report_history_ui import render_snapshot_history
render_snapshot_history(st.session_state['draft'], 'metadata_history', {}, st.session_state['snapshot'])
st.text_input('Continue editing current draft', value='Unpublished synthetic edit', key='current_edit')
'''


@pytest.mark.parametrize("raw,cause", INVALID_METADATA)
def test_history_decoder_failure_keeps_current_edit_controls_and_saved_bytes(draft, tmp_path, raw, cause):
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic editor")
    root = library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True)
    history = root / "history" / (PERIOD.key + "-00000001.json")
    valid_history = history.read_bytes()
    history.write_bytes(raw)
    before = stored_bytes(tmp_path)

    app = AppTest.from_string(HISTORY_APP, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["snapshot"] = saved
    app.run()
    assert not app.exception
    assert [item.value for item in app.error] == ["Shared report history could not be read: " + UNREADABLE]
    assert any("current draft and existing saved versions have not been changed" in item.value for item in app.caption)
    app.text_input(key="current_edit").set_value("Still editable after failed history read").run()
    assert not app.exception
    assert app.text_input(key="current_edit").value == "Still editable after failed history read"
    assert stored_bytes(tmp_path) == before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, PERIOD) == saved

    # Repair only this disposable fixture; normal viewing never rewrites it.
    history.write_bytes(valid_history)
    restored = stored_bytes(tmp_path)
    app.run()
    assert not app.exception and not app.error
    assert any(item.label == "Inspect a saved version" for item in app.selectbox)
    assert app.text_input(key="current_edit").value == "Still editable after failed history read"
    assert stored_bytes(tmp_path) == restored


@pytest.mark.parametrize("raw,cause", INVALID_METADATA)
@pytest.mark.parametrize("kind", ["shared-snapshot", "browser-journal"])
def test_failed_decode_never_overwrites_a_saved_head_or_journal(draft, tmp_path, raw, cause, kind):
    library.save_snapshot(draft, expected_revision=0)
    active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=1)
    if kind == "shared-snapshot":
        path = library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True) / (PERIOD.key + ".json")
        read = lambda: library.load_snapshot(draft.profile.contract, draft.profile.key, PERIOD)
        save = lambda: library.save_snapshot(replace(draft, prepared_by="Later editor"), expected_revision=1)
    else:
        path = active._directory(TOKEN, draft.profile.contract, draft.profile.key, PERIOD) / "working.json"
        read = lambda: active.load(TOKEN, draft.profile.contract, draft.profile.key, PERIOD)
        save = lambda: active.save(TOKEN, replace(draft, prepared_by="Later editor"), expected_revision=1,
                                   base_snapshot_revision=1)
    path.write_bytes(raw)
    before = stored_bytes(tmp_path)
    for operation in (read, save):
        with pytest.raises(library.LibraryError, match=UNREADABLE):
            operation()
        assert stored_bytes(tmp_path) == before
