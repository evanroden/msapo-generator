"""Section-page replacement has an explicit, revision-bound local undo."""
from dataclasses import replace
from io import BytesIO

from streamlit.testing.v1 import AppTest

from app import monthly_report_guided as guided
from test_monthly_report_sources import image_bytes


def replacement_app(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    upload = BytesIO(image_bytes())
    upload.name = "synthetic-replacement.png"
    uploader = guided.st.file_uploader
    monkeypatch.setattr(guided.st, "file_uploader", lambda label, *a, **kw:
        upload if label == "Replacement image for Water treatment reports" else uploader(label, *a, **kw))
    app = AppTest.from_string('''
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_guided import _edit_content
from app.monthly_report_model import ResolvedBlock, default_sections, synthetic_profiles
spec = next(b for s in default_sections() for b in s.blocks if b.key == "water_reports")
original = ResolvedBlock("water_reports", "This month", asset_hashes=("original-a", "original-b"),
    asset_captions=("Page A", "Page B"), references=("source-one", "source-two"))
st.session_state.setdefault("original", original)
st.session_state.setdefault("draft", original)
st.session_state.setdefault("assets", {})
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
st.session_state["draft"] = _edit_content(spec, st.session_state["draft"],
    SimpleNamespace(profile=synthetic_profiles()[0]), "synthetic", st.session_state["assets"],
    field, manage_saved_pictures=False)
''').run()
    assert not app.exception
    return app


def test_page_replacement_names_its_section_count_and_restores_original(monkeypatch, tmp_path):
    app = replacement_app(monkeypatch, tmp_path)
    assert any("Replaces 2 attached pages in Water treatment reports" in item.value for item in app.caption)
    next(b for b in app.button if b.label == "Use this replacement in this report").click().run()
    assert not app.exception
    replaced = app.session_state["draft"]
    assert len(replaced.asset_hashes) == 1
    assert replaced.asset_hashes != app.session_state["original"].asset_hashes
    app.run()
    next(b for b in app.button if b.label == "Undo attached-page replacement").click().run()
    assert not app.exception
    assert app.session_state["draft"] == app.session_state["original"]
    # The action returns the restored block before its caller commits the draft.
    # A neutral render retires the old button; no mid-editor rerun is required.
    app.run()
    assert app.session_state["draft"] == app.session_state["original"]
    assert not any(b.label == "Undo attached-page replacement" for b in app.button)
    assert replaced.asset_hashes[0] in app.session_state["assets"]


def test_page_replacement_undo_cannot_overwrite_later_report_edit(monkeypatch, tmp_path):
    app = replacement_app(monkeypatch, tmp_path)
    next(b for b in app.button if b.label == "Use this replacement in this report").click().run()
    changed = replace(app.session_state["draft"], text="A later human correction.")
    app.session_state["draft"] = changed
    app.run()
    assert next(b for b in app.button if b.label == "Undo attached-page replacement").disabled
    assert app.session_state["draft"] == changed
    assert app.session_state["original"].asset_hashes == ("original-a", "original-b")
