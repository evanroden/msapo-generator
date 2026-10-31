"""Whole-PDF shortcuts cannot hide the existing financial consent route."""
from dataclasses import replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_mbcx_financial_pages as financial
from app import monthly_report_mbcx_pdf as whole_pdf
from app import monthly_report_upload_ui as upload_ui
from test_monthly_report_mbcx_pdf import APP, pdf_bytes


def launch(monkeypatch, tmp_path, destination="mbcx_report", raw=None):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "isolated-store"))
    stream = BytesIO(pdf_bytes() if raw is None else raw)
    stream.name = "synthetic-dispatch.pdf"
    monkeypatch.setattr(upload_ui.st, "file_uploader", lambda *a, **kw: [stream])
    script = APP.replace("ReportPeriod, synthetic_profiles", "ReportPeriod, synthetic_profiles, default_sections")
    script = script.replace('"mbcx_report"', repr(destination))
    script = script.replace("sources, additions, _ =", "sources, additions, incoming =")
    script = script.replace("blocks=blocks)", "blocks=blocks, sections=default_sections())")
    script += '\nst.session_state["incoming"] = incoming\n'
    return AppTest.from_string(script, default_timeout=20).run()


def test_real_financial_opt_in_stays_visible_and_suppresses_generic_shortcut(monkeypatch, tmp_path):
    app = launch(monkeypatch, tmp_path)
    assert not app.exception
    consent = next(c for c in app.checkbox if c.label == "Review client-facing ENFRA financial pages")
    assert not consent.value
    assert any(b.label == "Include all 3 PDF pages" for b in app.button)
    original = app.session_state["sources"]
    consent.check().run()
    assert not app.exception
    assert any(c.label == "This is an ENFRA report intended for the client" for c in app.checkbox)
    assert not any(b.label.startswith("Include all ") for b in app.button)
    assert app.session_state["sources"] == original
    assert app.session_state["blocks"] == {}
    assert not original[0].client_page_reviews


def test_default_whole_pdf_cannot_approve_financial_amounts(monkeypatch, tmp_path):
    from app import monthly_report_sources as sources
    from app.monthly_report_model import synthetic_profiles
    raw = pdf_bytes(bad_page="ENFRA client report revenue $500.")
    app = launch(monkeypatch, tmp_path, raw=raw)
    assert not app.exception
    assert not next(c for c in app.checkbox if c.label == "Review client-facing ENFRA financial pages").value
    assert next(b for b in app.button if b.label == "Include all 3 PDF pages").disabled
    assert app.session_state["blocks"] == {}
    source = app.session_state["sources"][0]
    assert not source.client_page_reviews and not source.financial_page_reviews
    assert source.financial_source_review is None
    app.run()
    assert not app.exception and app.session_state["blocks"] == {}
    assert app.session_state["sources"] == (source,)
    assert sources.source_bytes(synthetic_profiles()[0], source) == raw


@pytest.mark.parametrize("pending", [False, True])
def test_financial_handled_never_calls_generic_or_persists_uncommitted_source(monkeypatch, tmp_path, pending):
    calls, original = [], []
    token = {"synthetic_pending_batch": True} if pending else {}
    def handled(profile, content, *args, **kwargs):
        calls.append("financial")
        original.append(content.source)
        revised = replace(content, source=replace(content.source, service_date="2026-10-19"))
        return True, revised, token
    def forbidden(*args, **kwargs):
        pytest.fail("Financial handled route must return before generic whole-PDF inclusion")
    monkeypatch.setattr(financial, "render_reviewed_batch", handled)
    monkeypatch.setattr(whole_pdf, "render_whole_pdf", forbidden)
    app = launch(monkeypatch, tmp_path)
    assert not app.exception and calls == ["financial"]
    assert app.session_state["sources"] == (original[0],)
    assert app.session_state["blocks"] == {}
    expected = {"financial_batch": token, "financial_evidence_key": "synthetic_evidence"} if pending else {}
    assert app.session_state["incoming"] == expected


@pytest.mark.parametrize("destination", ["mbcx_report", "utility_analysis"])
def test_eligible_generic_path_remains_reachable_in_correct_order(monkeypatch, tmp_path, destination):
    calls = []
    def decline(profile, content, *args, **kwargs):
        calls.append("financial")
        assert destination == "mbcx_report", "Scorecard must not enter the financial route"
        return False, content, {}
    native = whole_pdf.render_whole_pdf
    def generic(*args, **kwargs):
        calls.append("generic")
        return native(*args, **kwargs)
    monkeypatch.setattr(financial, "render_reviewed_batch", decline)
    monkeypatch.setattr(whole_pdf, "render_whole_pdf", generic)
    app = launch(monkeypatch, tmp_path, destination)
    expected = ["financial", "generic"] if destination == "mbcx_report" else ["generic"]
    assert not app.exception and calls == expected
    next(b for b in app.button if b.label == "Include all 3 PDF pages").click().run()
    assert not app.exception
    assert len(app.session_state["blocks"][destination].asset_hashes) == 3
    # Successful inclusion schedules an existing editor-refresh rerun. Every
    # complete run must preserve dispatch order; the rerun count is not fixed.
    assert len(calls) >= 2 * len(expected)
    assert len(calls) % len(expected) == 0
    assert calls == expected * (len(calls) // len(expected))
    assert app.session_state["incoming"] == {}
