"""Final-output copy is concise while exact shared-save receipts remain truthful.

Synthetic Streamlit UI only; this does not exercise production or real reports.
"""
import re

import pytest
from streamlit.testing.v1 import AppTest


SCRIPT = """
import streamlit as st
from types import SimpleNamespace
from app.monthly_report_output_ui import record_shared_save, render_output_status

mode = st.session_state.get("test_mode", "unconfirmed")
pdf = st.session_state.get("test_pdf", True)
prefix = "synthetic_outcome"
package = SimpleNamespace(
    fingerprint="synthetic-draft", docx=b"synthetic-word",
    pdf=b"%PDF-synthetic" if pdf else None,
)
draft = SimpleNamespace(
    fingerprint="synthetic-draft",
    period=SimpleNamespace(label="September 2026"),
)
snapshot = None
if mode == "failed":
    record_shared_save(prefix, package, error="Synthetic shared disk unavailable")
elif mode == "saved":
    record_shared_save(prefix, package,
                       saved=SimpleNamespace(revision=2, generated_at="synthetic-time"))
elif mode in {"same_snapshot", "newer_snapshot"}:
    st.session_state[prefix + "_revision"] = 2
    record_shared_save(prefix, package, error="Synthetic shared disk unavailable")
    snapshot = SimpleNamespace(draft=draft, revision=2 if mode == "same_snapshot" else 3)
st.session_state["needs_save"] = render_output_status(package, draft, snapshot, prefix)
"""


def view(mode, *, pdf=True):
    app = AppTest.from_string(SCRIPT, default_timeout=20)
    app.session_state["test_mode"] = mode
    app.session_state["test_pdf"] = pdf
    app.run()
    assert not app.exception
    return app


def _words(text):
    return len(re.findall(r"\b[\w’-]+\b", text))


@pytest.mark.parametrize("pdf,success", [
    (True, "Word and PDF ready to download"),
    (False, "Word ready to download"),
])
def test_unconfirmed_shared_save_never_claims_a_saved_version(pdf, success):
    app = view("unconfirmed", pdf=pdf)
    assert app.session_state["needs_save"] is True
    assert [item.value for item in app.success] == [success]
    assert [item.value for item in app.warning] == ["Shared save not confirmed."]
    assert [item.value for item in app.get("caption")] == [
        "Retry saving below. Files remain available; this won't regenerate them."
    ]
    assert not any("Shared version" in item.value for item in app.get("caption"))


def test_failed_shared_save_keeps_exact_reason_and_ready_files():
    app = view("failed")
    assert app.session_state["needs_save"] is True
    assert [item.value for item in app.warning] == [
        "Shared save failed: Synthetic shared disk unavailable"
    ]
    assert [item.value for item in app.success] == ["Word and PDF ready to download"]
    copy = app.warning[0].value + " " + app.get("caption")[0].value
    old = ("Downloads are ready, but this version was not saved in shared report history: "
           "Synthetic shared disk unavailable. "
           "Retry saving this version below. Your files stay available; "
           "saving does not generate them again.")
    assert _words(copy) * 10 <= _words(old) * 7


def test_confirmed_save_names_only_the_actual_shared_revision():
    app = view("saved")
    assert app.session_state["needs_save"] is False
    assert not app.warning
    assert [item.value for item in app.get("caption")] == [
        "[Shared version 2](#shared-report-history) · September 2026"
    ]
    assert [item.value for item in app.success] == ["Word and PDF ready to download"]


def test_old_matching_snapshot_cannot_override_failed_save():
    app = view("same_snapshot")
    assert app.session_state["needs_save"] is True
    assert [item.value for item in app.warning] == [
        "Shared save failed: Synthetic shared disk unavailable"
    ]
    assert not any("Shared version" in item.value for item in app.get("caption"))


def test_later_matching_snapshot_can_confirm_shared_save_without_regeneration():
    app = view("newer_snapshot")
    assert app.session_state["needs_save"] is False
    assert not app.warning
    assert [item.value for item in app.get("caption")] == [
        "[Shared version 3](#shared-report-history) · September 2026"
    ]
