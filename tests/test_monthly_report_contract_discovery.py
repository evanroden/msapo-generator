"""Full verified client title is primary; account code remains selectable identity."""
from types import SimpleNamespace
from unittest.mock import patch
from streamlit.testing.v1 import AppTest

from app import monthly_report_branding as branding, monthly_report_start_ui as ui


APP = """
import streamlit as st
from app.monthly_report_start_ui import choose_contract

def field(key, default):
    st.session_state.setdefault(key, default)
    return key
choose_contract("", field)
"""


def test_verified_account_title_search_finds_internal_code(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ui, "contract_choices", lambda: ["BRATH", "Unmapped Contract"])
    monkeypatch.setattr(branding, "load_branding", lambda: SimpleNamespace(logos=()))
    monkeypatch.setattr(branding, "find_logo", lambda code, **kwargs:
                        SimpleNamespace(title="The Water Campus") if code == "BRATH" else None)
    monkeypatch.setattr(ui, "_logo", lambda *args, **kwargs: None)
    app = AppTest.from_string(APP).run()
    assert not app.exception
    assert [b.label for b in app.button] == ["The Water Campus", "Unmapped Contract"]
    assert any("Account code: BRATH" in c.value for c in app.caption)
    next(w for w in app.text_input if w.label == "Find a contract").set_value("water campus").run()
    assert [b.label for b in app.button] == ["The Water Campus"]
    next(b for b in app.button if b.label == "The Water Campus").click().run()
    assert not app.exception
    assert app.session_state["report_contract"] == "BRATH"


def test_unmapped_client_has_initials_not_broken_image_and_no_fabricated_title():
    assert ui._contract_label("BRATH", None) == "BRATH"
    assert ui._fallback_initials("The Water Campus") == "TWC"
    assert ui._fallback_initials(" ") == "—"
