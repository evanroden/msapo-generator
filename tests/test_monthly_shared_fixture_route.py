"""Route isolation, independent from shared-upload and real-importer tests."""
from types import SimpleNamespace
import sys

import pytest
from streamlit.testing.v1 import AppTest

from app import memory, monthly_report_testing as testing
from app.monthly_report_ui import shared_fixture_run_token


COOKIE = "a" * 32
SCRIPT = '''
from app.monthly_report_ui import render_monthly_report_workflow
render_monthly_report_workflow("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
'''


def _probe(monkeypatch):
    import streamlit as st

    def render(token, timezone, field, move, live_root):
        st.session_state["observed_scope"] = testing.scope()
        st.session_state["observed_generation"] = testing.generation()
        st.session_state["observed_token"] = token
        st.session_state["observed_root"] = str(memory._data_dir())
        st.session_state["observed_base"] = str(live_root)
    monkeypatch.setitem(sys.modules, "app.monthly_report_shared_testing_ui", SimpleNamespace(render=render))


def test_hidden_route_uses_separate_synthetic_and_live_storage_and_recovers(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    _probe(monkeypatch)
    with testing.isolated(COOKIE):
        synthetic_root = memory._data_dir()
    app = AppTest.from_string(SCRIPT)
    app.query_params["monthly_qa"] = "fixtures"
    app.session_state["report_old_text"] = "old live text"
    app.run()
    assert not app.exception
    assert "report_old_text" not in app.session_state
    root = app.session_state["observed_root"]
    generation = app.session_state["observed_generation"]
    assert root not in {str(tmp_path), str(synthetic_root)}
    assert app.session_state["observed_base"] == str(tmp_path)
    assert app.session_state["observed_token"] == shared_fixture_run_token(COOKIE)
    fresh = AppTest.from_string(SCRIPT)
    fresh.query_params["monthly_qa"] = "fixtures"
    fresh.run()
    assert not fresh.exception
    assert fresh.session_state["observed_root"] == root
    assert fresh.session_state["observed_generation"] == generation
    assert testing.scope() is None


def test_external_reset_clears_old_editors_but_preserves_delivered_start_action(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    _probe(monkeypatch)
    app = AppTest.from_string(SCRIPT)
    app.query_params["monthly_qa"] = "fixtures"
    app.run()
    old = app.session_state["observed_generation"]
    app.session_state["report_old_text"] = "stale text"
    app.session_state["_shared_fixture_staged"] = "stale staged input"
    app.session_state["_shared_fixture_pending"] = {"action": "start", "generation": old}
    with testing.isolated(shared_fixture_run_token(COOKIE)):
        memory._data_dir()
        testing.reset(tmp_path)
    app.run()
    assert not app.exception
    assert app.session_state["observed_generation"] != old
    assert "report_old_text" not in app.session_state
    assert "_shared_fixture_staged" not in app.session_state
    assert app.session_state["_shared_fixture_pending"]["generation"] == old


@pytest.mark.parametrize("cookie", [None, "", "not-a-device", "A" * 32, "a" * 32 + "\n"])
def test_derived_run_identity_does_not_turn_invalid_cookie_into_valid_scope(cookie):
    with pytest.raises(ValueError):
        shared_fixture_run_token(cookie)
