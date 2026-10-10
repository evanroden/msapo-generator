"""The served Git commit must be verifiable without exposing environment details."""
from streamlit.testing.v1 import AppTest

from app.public_build import runtime_commit

SHA = "c" * 40


def test_runtime_commit_reports_only_valid_exact_git_sha():
    assert runtime_commit({"RENDER_GIT_COMMIT": SHA}) == SHA
    assert runtime_commit({"RENDER_GIT_COMMIT": "A" * 40}) == "a" * 40
    for value in ("", "master version 1", "not-deployed", "x" * 40,
                  SHA + "-EXTRA", "<script>alert(1)</script>"):
        assert runtime_commit({"RENDER_GIT_COMMIT": value}) == ""


def test_monthly_and_expense_footer_identify_workflow_and_real_build(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", SHA)
    app = AppTest.from_string("""
import streamlit as st
from app.web_ui import _render_footer, MONTHLY_REPORT_WORKFLOW, EXPENSE_WORKFLOW
_render_footer(MONTHLY_REPORT_WORKFLOW)
_render_footer(EXPENSE_WORKFLOW)
""").run()
    assert not app.exception
    markup = "\n".join(item.value for item in app.markdown)
    assert "monthly report preparation" in markup
    assert "expense reimbursement preparation" in markup
    assert "purchase-order prep" not in markup
    assert sum(SHA in item.value for item in app.caption) == 2


def test_unavailable_build_is_not_misrepresented_as_master_version(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    app = AppTest.from_string("""
from app.web_ui import _render_footer
_render_footer()
""").run()
    assert not app.exception
    assert any("build identifier unavailable" in c.value for c in app.caption)
