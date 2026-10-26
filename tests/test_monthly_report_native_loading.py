"""Native placeholder sizing must preserve real inputs and their delivered values."""
import re

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_native_loading as loading


APP = """
import streamlit as st
from app.monthly_report_native_loading import reserve_text_area, reserve_empty_uploader
reserve_text_area("working_notes", 140)
text = st.text_area("Notes", value="Original note", height=140, key="working_notes")
reserve_empty_uploader("source_upload", "Add source files")
st.file_uploader("Add source files", type=["pdf"],
                 accept_multiple_files=True, key="source_upload")
if st.button("Keep notes"):
    st.session_state["submitted_note"] = text
"""


def test_placeholder_styles_keep_native_identity_and_same_action_text(monkeypatch):
    text_reserve, upload_reserve = loading.reserve_text_area, loading.reserve_empty_uploader
    monkeypatch.setattr(loading, "reserve_text_area", lambda *args: None)
    monkeypatch.setattr(loading, "reserve_empty_uploader", lambda *args: None)
    app = AppTest.from_string(APP).run()
    assert not app.exception
    text_id = app.text_area[0].proto.id
    upload_id = app.get("file_uploader")[0].proto.id
    assert not app.get("html")
    monkeypatch.setattr(loading, "reserve_text_area", text_reserve)
    monkeypatch.setattr(loading, "reserve_empty_uploader", upload_reserve)
    app.text_area[0].set_value("Keep this pending human note.")
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["submitted_note"] == "Keep this pending human note."
    assert app.text_area[0].proto.id == text_id
    assert app.get("file_uploader")[0].proto.id == upload_id
    assert len(app.get("html")) == 2
    app.text_area[0].set_value("")
    app.button[0].click().run()
    assert app.session_state["submitted_note"] == ""
    assert app.text_area[0].proto.id == text_id


def test_sizing_is_scoped_to_the_existing_skeleton_and_wraps_its_native_label():
    app = AppTest.from_string(APP).run()
    assert not app.exception
    text_css, upload_css = [item.proto.body for item in app.get("html")]
    assert '.st-key-working_notes > [data-testid="stSkeleton"]{height:140px;}' in text_css
    assert 'Add source files' in upload_css
    assert 'visibility:hidden' in upload_css
    assert 'height:4.25rem' in upload_css and 'height:6.15rem' in upload_css
    assert '(width < 23rem)' in upload_css
    assert 'textarea' not in text_css and '<input' not in upload_css
    assert len(app.text_area) == len(app.get("file_uploader")) == 1


def test_populated_upload_does_not_claim_the_empty_dropzone_geometry():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_native_loading import reserve_empty_uploader
st.session_state["selected_upload"] = ["existing uploaded file"]
reserve_empty_uploader("selected_upload", "Add source files")
""").run()
    assert not app.exception and not app.get("html")


def test_unusual_key_and_label_cannot_escape_the_style_element():
    app = AppTest.from_string("""
from app.monthly_report_native_loading import reserve_empty_uploader
reserve_empty_uploader(' bad</style> key ', '</style><script>untrusted</script>')
""").run()
    assert not app.exception
    css = app.get("html")[0].proto.body
    assert '.st-key-bad--style--key > [data-testid="stSkeleton"]' in css
    assert len(re.findall(r"</style>", css)) == 1
    assert "<script>" not in css
    assert r"\3c /style\3e " in css


@pytest.mark.parametrize("height", [None, "content", 0, -1, True, 140.5])
def test_unspecified_or_invalid_text_height_adds_no_sizing_rule(height):
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_native_loading import reserve_text_area
reserve_text_area("notes", st.session_state["height"])
""")
    app.session_state["height"] = height
    app.run()
    assert not app.exception and not app.get("html")


def test_another_streamlit_version_requires_a_fresh_geometry_review(monkeypatch):
    monkeypatch.setattr(loading.st, "__version__", "future-unreviewed")
    app = AppTest.from_string(APP).run()
    assert not app.exception and not app.get("html")


def test_period_reservation_keeps_widget_identity_defaults_and_native_submission(monkeypatch):
    reserve = loading.reserve_period_selector
    monkeypatch.setattr(loading, "reserve_period_selector", lambda *args: None)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_setup import month_selector
from app.monthly_report_model import ReportPeriod
def field(key, default):
    st.session_state.setdefault(key, default)
    return key
period = month_selector(field, 'report', ReportPeriod(2026, 9))
if st.button('Record'):
    st.session_state['received_period'] = period.key
''').run()
    assert not app.exception and not app.get('html')
    ids = [widget.proto.id for widget in app.selectbox]
    monkeypatch.setattr(loading, "reserve_period_selector", reserve)
    app.selectbox('report_month_number').set_value(3)
    app.selectbox('report_year').set_value(2025)
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['received_period'] == '2025-03'
    assert [widget.proto.id for widget in app.selectbox] == ids
    assert [widget.value for widget in app.selectbox] == [3, 2025]
    assert [widget.options[widget.proto.default] for widget in app.selectbox] == ['March', '2025']
    assert len(app.get('html')) == len(app.selectbox) == 2
    app.run()
    assert [widget.proto.id for widget in app.selectbox] == ids
    assert [widget.value for widget in app.selectbox] == [3, 2025]


def test_period_placeholder_is_scoped_escaped_and_version_bound(monkeypatch):
    source = '''
from app.monthly_report_native_loading import reserve_period_selector
reserve_period_selector(' test</style> key ', '</style><script>synthetic</script>')
'''
    app = AppTest.from_string(source).run()
    assert not app.exception
    css = app.get('html')[0].proto.body
    assert '.st-key-test--style--key > [data-testid="stSkeleton"]' in css
    assert len(re.findall(r'</style>', css)) == 1
    assert '<script>' not in css
    assert r'\3c /style\3e ' in css
    monkeypatch.setattr(loading.st, '__version__', 'future-unreviewed')
    app.run()
    assert not app.exception and not app.get('html')
