"""The existing metadata cap must bound the read, including a stat/read race."""

from pathlib import Path
import os

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles


LIMIT_ERROR = "Saved report metadata exceeds the storage limit."


@pytest.fixture
def storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return tmp_path


def replace_after_stat(monkeypatch, path, raw, mode):
    """Real file growth/replacement after the reader receives its small stat."""
    original = Path.stat
    observations = []

    def observed(candidate, *args, **kwargs):
        result = original(candidate, *args, **kwargs)
        if candidate == path and not observations:
            observations.append(result.st_size)
            if mode == "grow":
                with path.open("ab") as output:
                    output.write(raw[result.st_size:])
            else:
                replacement = path.with_name(path.name + ".incoming")
                replacement.write_bytes(raw)
                os.replace(replacement, path)
        return result

    monkeypatch.setattr(Path, "stat", observed)
    return observations


def observe_reads(monkeypatch, path, *, fail=False):
    original = Path.open
    calls, handles = [], []

    class ObservedRead:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, size=-1):
            calls.append(size)
            if fail:
                raise OSError("Synthetic interrupted metadata read")
            return self.handle.read(size)

    def opened(candidate, *args, **kwargs):
        handle = original(candidate, *args, **kwargs)
        if candidate == path and (args[0] if args else kwargs.get("mode", "r")) == "rb":
            handles.append(handle)
            return ObservedRead(handle)
        return handle

    monkeypatch.setattr(Path, "open", opened)
    return calls, handles


@pytest.mark.parametrize("mode", ["grow", "replace"])
def test_growth_after_stat_is_bounded_and_refused_before_decoding(storage, monkeypatch, mode):
    path = storage / "growing.json"
    initial = b'{"schema":1}'
    path.write_bytes(initial)
    raw = initial + b" " * (library.MAX_JSON_BYTES + 1 - len(initial))
    sizes = replace_after_stat(monkeypatch, path, raw, mode)
    calls, handles = observe_reads(monkeypatch, path)
    decoded = []
    loads = library.json.loads

    def observed_loads(value):
        decoded.append(len(value))
        return loads(value)

    monkeypatch.setattr(library.json, "loads", observed_loads)
    with pytest.raises(library.LibraryError, match=LIMIT_ERROR):
        library._read_with_bytes(path)
    assert sizes == [len(initial)]
    assert calls and all(0 < size <= library.MAX_JSON_BYTES + 1 for size in calls)
    assert len(handles) == 1 and handles[0].closed
    assert decoded == [], "Oversized metadata must not reach the JSON decoder."
    with path.open("r+b") as unchanged:
        assert unchanged.read() == raw


@pytest.mark.parametrize("size", [32, library.MAX_JSON_BYTES - 1, library.MAX_JSON_BYTES])
def test_valid_metadata_at_or_below_cap_keeps_exact_bytes(storage, monkeypatch, size):
    prefix = '{"schema":1,"label":"café"}'.encode()
    raw = prefix + b" " * (size - len(prefix))
    path = storage / "valid.json"
    path.write_bytes(raw)
    calls, handles = observe_reads(monkeypatch, path)
    value, original = library._read_with_bytes(path)
    assert value == {"schema": 1, "label": "café"}
    assert len(original) == size and original == raw
    assert calls and all(0 < count <= library.MAX_JSON_BYTES + 1 for count in calls)
    assert len(handles) == 1 and handles[0].closed


def test_known_oversized_file_is_rejected_without_opening(storage, monkeypatch):
    path = storage / "oversized.json"
    with path.open("wb") as output:
        output.seek(library.MAX_JSON_BYTES)
        output.write(b" ")
    original = Path.open

    def forbidden(candidate, *args, **kwargs):
        assert candidate != path, "Do not open an already oversized metadata file."
        return original(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbidden)
    with pytest.raises(library.LibraryError, match=LIMIT_ERROR):
        library._read(path)
    assert path.stat().st_size == library.MAX_JSON_BYTES + 1


def test_interrupted_bounded_read_closes_file_and_keeps_existing_error(storage, monkeypatch):
    path = storage / "unreadable.json"
    path.write_bytes(b'{"schema":1}')
    calls, handles = observe_reads(monkeypatch, path, fail=True)
    with pytest.raises(library.LibraryError, match="Saved report data could not be read") as raised:
        library._read(path)
    assert isinstance(raised.value.__cause__, OSError)
    assert calls and all(0 < count <= library.MAX_JSON_BYTES + 1 for count in calls)
    assert len(handles) == 1 and handles[0].closed


HISTORY_APP = '''
import streamlit as st
from app.monthly_report_history_ui import render_snapshot_history
render_snapshot_history(st.session_state['draft'], 'metadata_size', {}, st.session_state['saved'])
st.text_input('Current draft note', value='Unpublished synthetic work', key='working_note')
'''


@pytest.mark.parametrize("mode", ["grow", "replace"])
def test_history_growth_reports_limit_and_preserves_head_and_current_edit(storage, monkeypatch, mode):
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic editor")
    root = library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True)
    head = root / (draft.period.key + ".json")
    history = root / "history" / (draft.period.key + "-00000001.json")
    head_before = head.read_bytes()
    valid = history.read_bytes()
    oversized = valid + b" " * (library.MAX_JSON_BYTES + 1 - len(valid))
    sizes = replace_after_stat(monkeypatch, history, oversized, mode)
    app = AppTest.from_string(HISTORY_APP, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["saved"] = saved
    app.run()
    assert not app.exception
    assert [item.value for item in app.error] == ["Shared report history could not be read: " + LIMIT_ERROR]
    assert sizes == [len(valid)]
    app.text_input(key="working_note").set_value("Still editing after a size refusal").run()
    assert not app.exception
    assert app.text_input(key="working_note").value == "Still editing after a size refusal"
    assert history.read_bytes() == oversized and head.read_bytes() == head_before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved
