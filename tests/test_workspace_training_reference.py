"""The native observer reference uses the real editor in guarded QA storage."""
import pytest
from streamlit.testing.v1 import AppTest

from scripts.workspace_training_reference import render_reference


def test_native_reference_requires_both_marked_root_and_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("EPC_MONTHLY_DOM_FIXTURE", raising=False)
    with pytest.raises(ValueError, match="marked disposable"):
        render_reference(tmp_path, lambda key, default: key)
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    monkeypatch.setenv("EPC_MONTHLY_TRAINING_TASK", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    with pytest.raises(ValueError, match="isolated synthetic"):
        render_reference(tmp_path, lambda key, default: key)


def test_reference_renders_production_matrix_form_without_app_observers_or_standing_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "1")
    monkeypatch.setenv("EPC_MONTHLY_TRAINING_TASK", "1")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    from app import monthly_report_training_ui as ui, workspace_layout
    from app import monthly_report_preview_view as preview
    monkeypatch.setattr(ui, "save_training", lambda *a, **kw: pytest.fail("Reference display must not save standing training"))
    monkeypatch.setattr(workspace_layout, "workspace", lambda *a, **kw: pytest.fail("Reference must not mount a workspace"))
    monkeypatch.setattr(preview, "render_view", lambda *a, **kw: pytest.fail("Reference must not mount a preview"))
    app = AppTest.from_string('''
from pathlib import Path
import os
import streamlit as st
from app.monthly_report_testing import isolated
from app.monthly_report_ui import _field
from scripts.workspace_training_reference import render_reference
with isolated("2" * 32):
    render_reference(Path(os.environ["EPC_DATA_DIR"]), _field)
''', default_timeout=20).run()
    assert not app.exception
    assert [widget.label for widget in app.multiselect] == ["Participants"]
    assert app.multiselect[0].options == ["Synthetic Person North", "Synthetic Person South"]
    assert app.date_input[0].value is None
    assert [widget.label for widget in app.date_input] == ["Training date"]
    assert any(table.value.columns.tolist() == ["Team member", "Site", "Lockout safety"] for table in app.dataframe)
    before = app.session_state["_native_training_reference_draft"]
    app.run()
    assert not app.exception
    assert app.session_state["_native_training_reference_draft"] == before
