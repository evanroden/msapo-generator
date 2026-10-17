"""Reserve real grid space while its lazy frontend loads, without remounts."""
import json
import re

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.proto.WidgetStates_pb2 import WidgetStates

from app import monthly_report_editor as editor


@pytest.mark.parametrize("count,mode,height", [
    (0, "fixed", "4.375rem"),
    (0, "dynamic", "4.375rem"),
    (1, "dynamic", "6.5625rem"),
    (2, "dynamic", "8.75rem"),
    (3, "dynamic", "10.9375rem"),
    (10_000, "dynamic", "26.25rem"),
])
def test_loading_box_matches_native_rows_header_border_and_cap(count, mode, height):
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_editor import _grid
_grid('synthetic_grid', [{'Name': str(i)} for i in range(st.session_state['count'])], num_rows=st.session_state['mode'])
""")
    app.session_state["count"] = count
    app.session_state["mode"] = mode
    app.run()
    assert not app.exception
    css = app.get("html")[0].proto.body
    assert '.st-key-synthetic_grid > [data-testid="stSkeleton"]' in css
    assert "display:inline-block" in css  # Same native table baseline spacing.
    assert f"height:min(25rem,calc({height} + 2px))" in css
    assert len(app.get("dataframe")) == 1


def test_loading_style_cannot_escape_its_owned_key_or_change_explicit_height():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_editor import _reserve_grid_loading_space
_reserve_grid_loading_space(' bad</style> key ', 2, num_rows='dynamic', row_height=48)
_reserve_grid_loading_space('explicit', 2, height=200)
""").run()
    assert not app.exception
    assert len(app.get("html")) == 1
    css = app.get("html")[0].proto.body
    assert '.st-key-bad--style--key > [data-testid="stSkeleton"]' in css
    assert "calc(2.1875rem + 146px)" in css
    assert "explicit" not in css
    assert len(re.findall(r"</style>", css)) == 1


def test_reserving_space_keeps_native_identity_and_pending_row_edits(monkeypatch):
    reserve = editor._reserve_grid_loading_space
    monkeypatch.setattr(editor, "_reserve_grid_loading_space", lambda *a, **kw: None)
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_editor import _grid
st.session_state['accepted_rows'] = _grid('synthetic_grid', [{'Name':'Original'}], num_rows='dynamic', hide_index=True)
""").run()
    assert not app.exception
    original_id = app.get("dataframe")[0].proto.id
    edit = {
        "edited_rows": {0: {"Name": "Human correction"}},
        "added_rows": [{"Name": "Another row"}], "deleted_rows": [],
    }
    # AppTest's dataframe element does not send editor state on app.run().
    # Deliver the real widget wire payload, including its unchanged identity.
    message = WidgetStates()
    message.widgets.add(id=original_id, string_value=json.dumps(edit))
    monkeypatch.setattr(editor, "_reserve_grid_loading_space", reserve)
    app._run(message)
    assert not app.exception
    assert app.get("dataframe")[0].proto.id == original_id
    assert app.session_state["accepted_rows"] == [{"Name": "Human correction"}, {"Name": "Another row"}]
    app._run(message)
    assert app.get("dataframe")[0].proto.id == original_id
    assert app.session_state["accepted_rows"] == [{"Name": "Human correction"}, {"Name": "Another row"}]
    assert "8.75rem" in app.get("html")[0].proto.body


def test_placeholder_adapter_requires_the_reviewed_streamlit_version(monkeypatch):
    monkeypatch.setattr(editor.st, "__version__", "next-version-needs-review")
    app = AppTest.from_string("""
from app.monthly_report_editor import _reserve_grid_loading_space
_reserve_grid_loading_space('synthetic_grid', 3, num_rows='dynamic')
""").run()
    assert not app.exception
    assert not app.get("html")
