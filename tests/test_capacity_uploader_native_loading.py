"""Capacity's empty native uploader reserves its footprint before hydration.

AppTest proves the call/identity contract, not native browser geometry.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_capacity as capacity
from app import monthly_report_capacity_ui as ui
from app import monthly_report_native_loading as loading
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_capacity import profile as capacity_profile, draft, saved
from test_monthly_report_capacity_scope_task import _path
from test_monthly_report_capacity_ui import APP


@pytest.fixture
def profile(tmp_path, monkeypatch):
    return capacity_profile.__wrapped__(tmp_path, monkeypatch)


def reservation(app, key):
    styles = [node.proto.body for node in app.get("html")
              if ".st-key-" + key + ' > [data-testid="stSkeleton"]' in node.proto.body]
    assert len(styles) == 1
    return styles[0]


@pytest.mark.parametrize("state", ["empty", "report_only", "standing"])
def test_capacity_reserves_before_its_same_native_input_without_state_changes(profile, monkeypatch, state):
    block = ResolvedBlock("thermal_capacity", "Library")
    if state == "report_only":
        block = replace(block, source="This month", text="Keep this report-only note.")
    elif state == "standing":
        block = capacity.capacity_block(profile, saved(profile))
    original = draft(profile, block)
    standing = capacity.load_capacity(profile.contract)
    reserve, upload = loading.reserve_empty_uploader, ui.st.file_uploader
    events = []

    def observed_reserve(key, label, **kwargs):
        events.append(("reserve", key, label, kwargs))
        return reserve(key, label, **kwargs)

    def observed_upload(label, *args, **kwargs):
        events.append(("upload", kwargs["key"], label, kwargs))
        return upload(label, *args, **kwargs)

    monkeypatch.setattr(loading, "reserve_empty_uploader", observed_reserve)
    monkeypatch.setattr(ui.st, "file_uploader", observed_upload)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = original
    app.run()
    assert not app.exception
    assert [event[0] for event in events] == ["reserve", "upload"]
    assert events[0][1:3] == events[1][1:3] == ("test_capacity_upload", "Thermal capacity file")
    assert events[0][3] == {}, "Use the existing visible-label reservation."
    picker, = app.get("file_uploader")
    assert picker.key == "test_capacity_upload"
    assert picker.proto.max_upload_size_mb == 128
    assert {item.casefold() for item in picker.proto.type} == capacity.SUPPORTED
    assert picker.proto.help == ("DOCX: up to 128 MB. Other supported files: up to 30 MB. "
                                 "Use capacity values for the relevant sites.")
    panel, = [item for item in app.expander if item.label == "Capacity source and reusable data"]
    assert panel.proto.expanded is True
    assert _path(panel, picker) is not None
    css = reservation(app, picker.key)
    assert 'content:"Thermal capacity file"' in css
    assert 'height:4.25rem' in css and '(width < 23rem)' in css and 'height:6.15rem' in css
    assert 'visibility:hidden' in css
    assert all(token not in css for token in ("<input", "scroll", "position:fixed"))
    assert app.session_state["test_draft"] == original
    assert app.session_state["test_block"] == block
    assert capacity.load_capacity(profile.contract) == standing


def test_capacity_reservation_preserves_native_identity_arguments_and_subtree(profile, monkeypatch):
    reserve = loading.reserve_empty_uploader
    monkeypatch.setattr(loading, "reserve_empty_uploader", lambda *args, **kwargs: None)
    original = draft(profile)
    app = AppTest.from_string(APP)
    app.session_state["test_draft"] = original
    app.run()
    assert not app.exception
    picker, = app.get("file_uploader")
    before_id, before_path = picker.proto.id, _path(app._tree, picker)
    before_proto = picker.proto.SerializeToString()
    assert not app.get("html")
    monkeypatch.setattr(loading, "reserve_empty_uploader", reserve)
    for _ in range(2):
        app.run()
        assert not app.exception
        picker, = app.get("file_uploader")
        assert picker.proto.id == before_id
        assert picker.proto.SerializeToString() == before_proto
        assert _path(app._tree, picker) == before_path
        reservation(app, picker.key)
        assert app.session_state["test_draft"] == original
        assert capacity.load_capacity(profile.contract) is None
