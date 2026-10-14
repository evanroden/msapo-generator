"""PO adaptive checks run only in temporary local storage with external actions denied."""
from hashlib import sha256
from pathlib import Path

import fitz
import pytest
import requests
from streamlit.testing.v1 import AppTest

from app import memory, web_ui, smartsheet, receipt_jobs, expense_ui
from app.contracts import RRH_CONTRACT
from app.po_context import build_po_context
from test_web_ui_app import _configure_smartsheet

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_purchase(monkeypatch, tmp_path):
    _configure_smartsheet(monkeypatch)
    isolated = tmp_path / "purchase-test-only"
    isolated.mkdir()
    live_sentinel = tmp_path / "outside-test-sentinel"
    live_sentinel.write_bytes(b"Live records must remain untouched")
    monkeypatch.setenv("EPC_DATA_DIR", str(isolated))
    monkeypatch.setenv("SMARTSHEET_API_MODE", "disabled")
    denied = []
    def forbid(*args, **kwargs):
        denied.append("external action")
        pytest.fail("Isolated PO test attempted an external reader, submission, share or request")
    monkeypatch.setattr(web_ui, "analyze_quote", forbid)
    monkeypatch.setattr(web_ui, "extract_text", forbid)
    monkeypatch.setattr(receipt_jobs, "start_receipt", forbid)
    monkeypatch.setattr(smartsheet, "submit_po", forbid)
    monkeypatch.setattr(expense_ui, "_render_ios_mail_share", forbid)
    monkeypatch.setattr(requests.sessions.Session, "request", forbid)
    real_data_dir = memory._data_dir
    def only_test_storage():
        actual = real_data_dir()
        assert actual == isolated, "PO storage fell back outside its explicit test root"
        return actual
    monkeypatch.setattr(memory, "_data_dir", only_test_storage)
    generated = []
    def synthetic_pdf(**kwargs):
        generated.append(kwargs)
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), "Synthetic reviewed MSAPO")
            return doc.tobytes()
    monkeypatch.setattr(web_ui, "build_msapo_pdf", synthetic_pdf)
    yield isolated, generated
    assert denied == []
    assert live_sentinel.read_bytes() == b"Live records must remain untouched"


def sample_app():
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    assert not app.exception
    next(w for w in app.button if w.label == "Built by Evan Roden").click().run()
    assert not app.exception
    return app


def test_purchase_storage_and_external_actions_are_isolated_before_adaptive_changes(isolated_purchase):
    isolated, generated = isolated_purchase
    app = sample_app()
    original = app.session_state["uploaded_file_bytes"]
    assert original == app.session_state["quote_text"].encode("utf-8")
    assert app.session_state["quote_source"] == "synthetic"
    assert memory._data_dir() == isolated
    next(w for w in app.text_input if w.label == "Your name (Requester / Asset Manager) *").set_value(
        "Synthetic Isolated Reviewer").run()
    next(w for w in app.button if w.label == "Generate both files and Smartsheet link").click().run()
    assert not app.exception
    assert len(generated) == 1
    context = build_po_context(app.session_state.filtered_state)
    assert context.ready
    assert context.attachments[0][1] == original
    assert context.attachments[1][1] == app.session_state["scope_pdf_bytes"]
    assert len(app.get("download_button")) == 2
    assert memory._db_path().is_relative_to(isolated)
    assert memory.remembered_vendor_contact(RRH_CONTRACT, "Northeast Mechanical Services") == (
        "Morgan Bell", "mbell@example.com")
    before = {p.relative_to(isolated): sha256(p.read_bytes()).hexdigest()
              for p in isolated.rglob("*") if p.is_file()}
    app.run()
    assert len(generated) == 1  # A rerun does not generate/submit again.
    assert before == {p.relative_to(isolated): sha256(p.read_bytes()).hexdigest()
                      for p in isolated.rglob("*") if p.is_file()}


def test_adaptive_pairs_show_exact_source_then_only_current_generated_form(
        isolated_purchase, monkeypatch):
    from app import reference_preview
    isolated, generated = isolated_purchase
    shown = []
    monkeypatch.setattr(reference_preview, "render_reference", lambda **values: shown.append(values))
    app = sample_app()
    identity = app.session_state["po_workspace_identity"]
    original = app.session_state["uploaded_file_bytes"]
    assert shown[-1]["raw"] == original
    assert shown[-1]["key"] == "purchase_quote"
    assert shown[-1]["title"] == "Synthetic sample quote"
    assert not any(item["key"] == "purchase_msapo" for item in shown)
    markers = [node.value for node in app.markdown if "data-epc-pair=" in node.value]
    assert sum('data-epc-pair="purchase_review"' in node for node in markers) == 1
    assert sum('data-epc-pair="purchase_package"' in node for node in markers) == 1
    assert len([field for field in app.text_area if field.label == "Scope of Work"]) == 1
    next(w for w in app.text_input if w.label == "Your name (Requester / Asset Manager) *").set_value(
        "Synthetic Isolated Reviewer").run()
    next(w for w in app.button if w.label == "Generate both files and Smartsheet link").click().run()
    assert not app.exception
    generated_bytes = app.session_state["scope_pdf_bytes"]
    signature = app.session_state["scope_pdf_signature"]
    assert shown[-1]["key"] == "purchase_msapo"
    assert shown[-1]["raw"] == generated_bytes
    before = {p.relative_to(isolated): sha256(p.read_bytes()).hexdigest()
              for p in isolated.rglob("*") if p.is_file()}
    # No compare toggle duplicates the source in the generated package.
    # The original remains visible in the preceding authoritative editor.
    assert not any(w.label == "Compare original quote" for w in app.toggle)
    assert any(item["key"] == "purchase_quote" and item["raw"] == original
               and item["owner_scope"] == identity for item in shown)
    app.run()
    assert shown[-1]["key"] == "purchase_msapo"
    assert shown[-1]["raw"] == generated_bytes
    assert shown[-1]["owner_scope"] == identity
    assert app.session_state["scope_pdf_signature"] == signature
    assert len(generated) == 1
    assert before == {p.relative_to(isolated): sha256(p.read_bytes()).hexdigest()
                      for p in isolated.rglob("*") if p.is_file()}
    shown.clear()
    next(w for w in app.text_area if w.label == "Scope of Work").set_value(
        "Manually corrected synthetic scope.").run()
    assert not app.exception
    assert "scope_pdf_bytes" not in app.session_state
    assert not any(item["key"] == "purchase_msapo" for item in shown)
    assert next(w for w in app.text_area if w.label == "Scope of Work").value == "Manually corrected synthetic scope."
    assert app.session_state["po_workspace_identity"] == identity


def test_paste_reference_is_selected_snapshot_and_workflow_return_keeps_corrections(
        isolated_purchase, monkeypatch):
    from app import reference_preview
    from app.workflow_state import PASTE_MODE
    shown = []
    monkeypatch.setattr(reference_preview, "render_reference", lambda **values: shown.append(values))
    # A deliberate new input exercises deterministic local analysis, never a network reader.
    monkeypatch.setattr(web_ui, "analyze_quote", lambda text: web_ui._build_test_analysis())
    app = sample_app()
    identity = app.session_state["po_workspace_identity"]
    original = app.session_state["uploaded_file_bytes"]
    quote = "  " + web_ui._build_test_analysis().scope_of_work + "\n"
    next(w for w in app.radio if w.label == "Quote source").set_value(PASTE_MODE).run()
    next(w for w in app.text_area if w.label == "Paste the full vendor quote text").set_value(quote).run()
    assert not app.exception
    assert shown[-1]["text"] == quote.strip()
    assert "raw" not in shown[-1]
    assert app.session_state["uploaded_file_bytes"] == original  # Retained, inactive.
    next(w for w in app.text_input if w.label == "PO/CO amount — final total including every fee and tax *").set_value("001900.00").run()
    next(w for w in app.text_area if w.label == "Scope of Work").set_value("Retain this manual scope.").run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Purchase order").run()
    assert not app.exception
    assert next(w for w in app.text_input if w.label == "PO/CO amount — final total including every fee and tax *").value == "001900.00"
    assert next(w for w in app.text_area if w.label == "Scope of Work").value == "Retain this manual scope."
    assert shown[-1]["text"] == quote.strip()
    assert app.session_state["po_workspace_identity"] == identity
