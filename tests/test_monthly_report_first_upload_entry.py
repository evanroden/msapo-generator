"""A12 first-upload intake regression: unique scope, replay, bad replacement.

These tests use invented bytes and synthetic site names only. They do not
establish authentic DOCX, native browser, served-production or output parity.
"""
from io import BytesIO
from types import SimpleNamespace
import hashlib

from streamlit.testing.v1 import AppTest

from app import monthly_report_entry_upload as entry
from app.monthly_report_model import Facility


def test_cover_suggests_account_only_when_unique(monkeypatch):
    inspection = SimpleNamespace(
        title_candidates=("Synthetic East Campus - September 2026",), items=())
    sites = {
        "Account One": (Facility("east", "Synthetic East Campus"),),
        "Account Two": (Facility("west", "Synthetic West Campus"),),
        "Account Three": (Facility("duplicate", "Synthetic East Campus"),),
    }
    monkeypatch.setattr(entry.library, "list_profiles", lambda contract: ())
    monkeypatch.setattr(entry, "site_choices", lambda contract, profiles: sites[contract])
    assert entry.inferred_contracts(inspection, ("Account One", "Account Two")) == ("Account One",)
    assert entry.inferred_contracts(inspection, ("Account Two",)) == ()
    # The same cover name in two accounts is ambiguous and must not auto-route.
    assert entry.inferred_contracts(inspection, tuple(sites)) == ("Account One", "Account Three")


def _upload(raw):
    stream = BytesIO(raw)
    stream.name, stream.size = "synthetic.docx", len(raw)
    return stream


def test_first_upload_is_automatically_read_once_and_invalid_replacement_is_not_applied(monkeypatch):
    selected = {"upload": _upload(b"synthetic-good-a")}
    calls, cleaned = [], []
    monkeypatch.setattr(entry.st, "file_uploader", lambda *a, **kw: selected["upload"])
    monkeypatch.setattr(entry, "inferred_contracts", lambda inspection, contracts: ("Synthetic",))

    def staged(upload):
        raw = upload.getvalue()
        calls.append(raw)
        if raw == b"synthetic-bad":
            raise ValueError("Unsupported input")
        handle = SimpleNamespace(cleanup=lambda: cleaned.append(raw))
        inspection = SimpleNamespace(sha256=hashlib.sha256(raw).hexdigest(),
                                     title_candidates=("Synthetic East, September 2026",))
        return handle, None, inspection

    monkeypatch.setattr(entry, "_stage", staged)
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_entry_upload import render_first_upload

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

upload, stage, contracts = render_first_upload(field, ("Synthetic",))
st.session_state["synthetic_result"] = (stage[2].sha256 if stage else "", contracts)
""", default_timeout=20)
    app.run()
    assert not app.exception
    assert calls == [b"synthetic-good-a"]
    assert app.session_state["synthetic_result"][1] == ("Synthetic",)
    app.run()
    assert calls == [b"synthetic-good-a"]  # duplicate re-render, no extra parse

    selected["upload"] = _upload(b"synthetic-bad")
    app.run()
    assert calls == [b"synthetic-good-a", b"synthetic-bad"]
    assert app.session_state["synthetic_result"] == ("", ())
    assert any("Unsupported" in w.value or "DOCX" in w.value or "report" in w.value.lower()
               for w in app.warning)
    app.run()
    assert calls == [b"synthetic-good-a", b"synthetic-bad"]  # failed hash is not retried
    assert cleaned == []  # prior valid original is kept until deliberate replacement

    selected["upload"] = _upload(b"synthetic-good-b")
    app.run()
    assert calls == [b"synthetic-good-a", b"synthetic-bad", b"synthetic-good-b"]
    assert cleaned == [b"synthetic-good-a"]
    selected["upload"] = None
    app.run()
    assert cleaned == [b"synthetic-good-a", b"synthetic-good-b"]
    assert app.session_state["synthetic_result"] == ("", ())
    # A committed file remains idempotent while mounted, but clearing the
    # picker allows an intentional same-byte re-import later.
    selected["upload"] = _upload(b"synthetic-good-b")
    app.session_state[entry.ENTRY_COMMITTED] = hashlib.sha256(b"synthetic-good-b").hexdigest()
    app.run()
    assert calls == [b"synthetic-good-a", b"synthetic-bad", b"synthetic-good-b"]
    selected["upload"] = None
    app.run()
    selected["upload"] = _upload(b"synthetic-good-b")
    app.run()
    assert calls[-1] == b"synthetic-good-b" and len(calls) == 4


def test_preselected_sites_do_not_cross_a_changed_source_digest(monkeypatch):
    from app import monthly_report_start_ui as start
    monkeypatch.setattr(start, "site_choices", lambda contract, profiles: (
        Facility("east", "Synthetic East"), Facility("west", "Synthetic West")))
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_start_ui import select_sites

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

candidate, _ = select_sites("Synthetic", (), "", field,
                           suggested_sites=st.session_state.get("suggested", ("east",)),
                           source_digest=st.session_state.get("digest", "1" * 64))
st.session_state["chosen_sites"] = tuple(f.key for f in candidate.facilities) if candidate else ()
""", default_timeout=20).run()
    assert not app.exception
    assert app.session_state["chosen_sites"] == ("east",)
    # Switching uploaded documents must initialize a different set of widgets.
    app.session_state["suggested"] = ("west",)
    app.session_state["digest"] = "2" * 64
    app.run()
    assert not app.exception
    assert app.session_state["chosen_sites"] == ("west",)


def test_removing_a_first_use_file_retires_its_picker_and_every_review(monkeypatch):
    raw = b"synthetic-remove-me"
    keys, cleaned = [], []

    def uploader(*args, **kwargs):
        keys.append(kwargs["key"])
        # A rotated key is a fresh, empty picker.
        return _upload(raw) if kwargs["key"] == entry.ENTRY_UPLOAD_KEY else None

    monkeypatch.setattr(entry.st, "file_uploader", uploader)
    monkeypatch.setattr(entry, "inferred_contracts", lambda inspection, contracts: ("Synthetic",))
    monkeypatch.setattr(entry, "_stage", lambda upload: (
        SimpleNamespace(cleanup=lambda: cleaned.append(raw)), None,
        SimpleNamespace(sha256=hashlib.sha256(raw).hexdigest(), title_candidates=("Synthetic East",))))
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_entry_upload import render_first_upload, remove_entry_upload, ENTRY_STAGE

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

if st.session_state.pop("synthetic_remove", False):
    remove_entry_upload()
upload, stage, contracts = render_first_upload(field, ("Synthetic",))
if stage is not None:
    # Two proposed site selections reviewed the same staged original.
    st.session_state["report_setup_a_stage"] = stage
    st.session_state["report_setup_b_stage"] = stage
st.session_state["synthetic_result"] = (upload is not None, stage is not None)
""", default_timeout=20)
    app.run()
    assert not app.exception and app.session_state["synthetic_result"] == (True, True)
    app.session_state["synthetic_remove"] = True
    app.run()
    assert not app.exception
    assert cleaned == [raw]
    assert app.session_state["synthetic_result"] == (False, False)
    assert keys[-1] == entry.ENTRY_UPLOAD_KEY + "_v1"
    assert entry.ENTRY_STAGE not in app.session_state
    assert "report_setup_a_stage" not in app.session_state
    assert "report_setup_b_stage" not in app.session_state
    app.run()
    assert cleaned == [raw] and app.session_state["synthetic_result"] == (False, False)
