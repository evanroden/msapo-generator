"""Copy-only monthly evidence controls remain usable with help collapsed."""

from streamlit.testing.v1 import AppTest


SOURCE_APP = """
import streamlit as st
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_upload_ui import render_uploads

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

render_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9), "copy_test", field)
"""

PHOTO_APP = """
import streamlit as st
from app.monthly_report_model import ReportPeriod, synthetic_profiles, synthetic_draft, ResolvedBlock
from app.monthly_report_visual_ui import edit_photos

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

profile = synthetic_profiles()[0]
draft = synthetic_draft(profile, ReportPeriod(2026, 9))
block = ResolvedBlock("improvements", "This month")
edit_photos(draft, block, "copy_test", {}, field, show_preview=False)
"""


def test_optional_source_workspace_keeps_upload_and_limit_details(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(SOURCE_APP, default_timeout=20).run()
    assert not app.exception
    assert any(w.label == "Monthly source files" for w in app.get("file_uploader"))
    assert any(w.label == "File formats and limits" for w in app.expander)
    assert any(w.label == "Synthetic CMMS column example" for w in app.expander)
    assert any("PDF, Word, Excel, photos and email files" in w.value
               for w in app.get("caption"))
    assert not any("Files are stored with this profile on the persistent disk"
                   in w.value for w in app.get("caption"))


def test_empty_photo_workspace_has_one_visible_label_and_no_reassurance(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(PHOTO_APP, default_timeout=20).run()
    assert not app.exception
    assert sum(w.label == "Add photos" for w in app.expander) == 1
    assert next(w for w in app.expander if w.label == "Add photos").proto.expanded is False
    assert any(w.label == "Progress photos" for w in app.get("file_uploader"))
    assert not any("Add photos when you have them" in w.value for w in app.info)
