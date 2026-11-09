"""Failed workbook replacements preserve reviews through monthly administration."""
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from test_monthly_report_directory_batch import detail, summary, workbook


APP = '''
import streamlit as st
from unittest.mock import patch
from app.monthly_report_ui import render_monthly_report_workflow
with patch.object(st, "file_uploader", return_value=st.session_state.get("synthetic_upload")):
    render_monthly_report_workflow("b" * 32)
'''
CONTRACT = "Synthetic Route Recovery Contract"
SINGLE = "Import a workbook"
BATCH = "Import all contract contacts"


def control(items, label):
    return next(item for item in items if item.label == label)


def confirmation(app):
    return next(item for item in app.checkbox if item.label.startswith("I reviewed"))


def disk(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def snapshot(app, mode):
    save_label = "Save contract directory" if mode == SINGLE else "Save all reviewed contacts"
    choice_label = "Address row (0 if absent)" if mode == SINGLE else "Create these new contracts"
    controls = app.number_input if mode == SINGLE else app.multiselect
    choice = next((item.value for item in controls if item.label == choice_label), None)
    confirmed = next((item.value for item in app.checkbox if item.label.startswith("I reviewed")), None)
    save = next((item for item in app.button if item.label == save_label), None)
    return {"choice": choice, "confirmed": confirmed, "save_visible": save is not None,
            "save_enabled": save is not None and not save.disabled,
            "errors": [item.value for item in app.error]}


@pytest.mark.parametrize("mode", [SINGLE, BATCH])
def test_rejected_workbook_keeps_reviewed_choice_on_actual_admin_route(monkeypatch, tmp_path, mode):
    # The ordinary route uses a temporary synthetic data root, never production.
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    other = directory.save_directory("Synthetic Unrelated Contract", (), expected_revision=0,
        actor="Synthetic Other Editor", confirmed=True,
        contract_contacts=(directory.DirectoryContact("Manager", "Synthetic Other Person"),))
    raw = workbook((("Active Contracts", summary(B6=CONTRACT)),
                    (CONTRACT + " Sites", detail())))
    app = AppTest.from_string(APP, default_timeout=30)
    app.query_params["monthly_admin"] = "directory"
    app.session_state["report_directory_actor"] = "Synthetic Route Reviewer"
    app.session_state["report_directory_mode"] = mode
    app.session_state["synthetic_upload"] = BytesIO(raw)
    app.run()
    assert not app.exception and not app.error
    assert app.title[0].value == "Monthly administration"
    control(app.button, "Read workbook").click().run()
    assert not app.exception and not app.error
    if mode == SINGLE:
        control(app.selectbox, "Contract worksheet").select(CONTRACT + " Sites").run()
        control(app.number_input, "Address row (0 if absent)").set_value(0).run()
        wanted = 0
    else:
        control(app.multiselect, "Create these new contracts").set_value([CONTRACT]).run()
        wanted = [CONTRACT]
    confirmation(app).check().run()
    reviewed = snapshot(app, mode)
    assert reviewed["choice"] == wanted and reviewed["confirmed"] and reviewed["save_enabled"]
    saved_bytes = disk(tmp_path)

    app.session_state["synthetic_upload"] = BytesIO(b"invalid synthetic workbook")
    control(app.button, "Read workbook").click().run()
    assert not app.exception and app.error
    rejected = snapshot(app, mode)
    assert rejected["choice"] == wanted
    assert rejected["confirmed"] and rejected["save_enabled"]
    assert app.session_state["report_directory_workbook"][0] == raw
    assert disk(tmp_path) == saved_bytes

    app.run()
    assert not app.exception and not app.error
    resumed = snapshot(app, mode)
    assert app.session_state["report_directory_workbook"][0] == raw
    assert disk(tmp_path) == saved_bytes
    assert directory.load_directory(CONTRACT) is None
    assert directory.load_directory(other.contract) == other
    assert resumed["choice"] == wanted, "Rejected replacement discarded the user's reviewed choice"
    assert resumed["confirmed"] and resumed["save_enabled"]
