"""Actual three-workflow navigation, with all storage and actions isolated.

AppTest covers committed widget values and server-side view tickets/requests.
It cannot execute browser JavaScript, prove unblurred text/caret, or measure zoom.
"""
from datetime import date
from hashlib import sha256
import json

import pytest
import requests

from app import expense_ui, monthly_report_section_preview_ui as section_preview, reference_preview, web_ui, smartsheet
from app.monthly_report_preview_store import PreviewStore
from app.receipt_analyzer import ReceiptAnalysis
from test_expense_workspace_isolation import isolated_expenses, ACCOUNT, ACCOUNT_TOKEN
from test_monthly_report_ui import monthly
from test_reference_preview import pdf_bytes
from test_web_ui_app import _configure_smartsheet


@pytest.fixture
def populated_workflows(isolated_expenses, monkeypatch):
    gate = isolated_expenses
    denied_reader = expense_ui.start_receipt
    _configure_smartsheet(monkeypatch)
    monkeypatch.setattr(expense_ui, "start_receipt", denied_reader)
    monkeypatch.setattr(web_ui, "ensure_device_cookie", lambda **kwargs: None)
    monkeypatch.setattr(web_ui, "device_token", lambda *_args: "d" * 32)
    # Avoid unrelated build-provenance subprocess in this local AppTest fixture.
    monkeypatch.setattr("app.public_build.runtime_commit", lambda: "synthetic-local-workflow-test")

    def forbidden(*_args, **_kwargs):
        gate["attempts"].append("external or automatic generation")
        raise AssertionError("Workflow navigation attempted reading, generation, submission or sharing")

    for module, name in ((web_ui, "analyze_quote"), (web_ui, "extract_text"),
                         (web_ui, "build_msapo_pdf"), (expense_ui, "build_expense_package"),
                         (smartsheet, "submit_po"), (requests.sessions.Session, "request")):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(section_preview._PREVIEW_WORKER, "submit", forbidden)
    actual_section_preview = section_preview.render_section_preview
    app = monthly(monkeypatch, gate["root"])
    # Real preview state registration, with no browser visibility event. This
    # exercises scope retention without pretending a DOCX render occurred.
    monkeypatch.setattr(section_preview, "render_section_preview", actual_section_preview)
    store = PreviewStore()
    # The disposable raster cache is separate from EPC_DATA_DIR in production;
    # place this test's cache inside the same strictly guarded temporary root.
    import tempfile
    store._directory = tempfile.TemporaryDirectory(dir=gate["root"], prefix="preview-cache-")
    monkeypatch.setattr(reference_preview, "STORE", store)
    app.run()
    assert not app.exception
    yield app, gate
    store.close()


def text(app, label):
    return next(value for value in app.text_input if value.label == label)


def receipt_field(app, key):
    return next(value for value in app.text_input if value.key == key)


def change_workflow(app, name):
    app.segmented_control[0].set_value(name).run()
    assert not app.exception
    assert app.query_params["workflow"] == [{"Monthly report":"monthly", "Purchase order":"purchase", "Expense reimbursement":"expense"}[name]]


def preview_views(app):
    # These are actual component render payloads; no JS page/zoom is fabricated.
    return {data["viewScope"]: data["generation"] for node in app.get("bidi_component")
            if "viewScope" in (data := json.loads(node.proto.json))}


def seed_expense_sources(app):
    receipts = [("Synthetic_first.pdf", pdf_bytes(3), "application/pdf"),
                ("Synthetic_second.pdf", pdf_bytes(2), "application/pdf")]
    app.session_state["expense_receipt_files"] = receipts
    app.session_state["expense_account"] = ACCOUNT
    app.session_state["expense_draft_snapshot"] = {
        f"expense_employee_name_{ACCOUNT_TOKEN}": "Synthetic Workflow Reviewer",
        f"expense_employee_number_{ACCOUNT_TOKEN}": "000091",
        f"expense_manager_name_{ACCOUNT_TOKEN}": "Synthetic Manager",
        f"expense_manager_email_{ACCOUNT_TOKEN}": "manager@example.invalid",
        f"expense_report_date_{ACCOUNT_TOKEN}": date(2026, 9, 20),
    }
    for name, raw, _mime in receipts:
        app.session_state["expense_receipt_analysis_" + sha256(raw).hexdigest()] = ReceiptAnalysis(
            merchant_name="Synthetic Merchant", transaction_date=date(2026, 9, 10),
            total_amount="30.00", suggested_description="Synthetic business supplies", confidence="high")
    return receipts


def test_populated_monthly_po_and_split_expenses_return_without_cross_workflow_loss(populated_workflows):
    app, gate = populated_workflows
    monthly_words = "Retained synthetic Activity correction; leave this report exactly as entered."
    next(value for value in app.text_area if value.label == "Activity summary").set_value(monthly_words).run()
    draft_key = next(key for key in app.session_state.filtered_state if key.startswith("report_guided_") and key.endswith("_draft"))
    monthly_draft = app.session_state[draft_key]
    monthly_view = preview_views(app)
    assert monthly_view
    state_key = next(key for key in app.session_state.filtered_state if key.endswith("_ordered_previews"))
    monthly_preview = app.session_state[state_key]
    monthly_preview["page_requests"]["activity"] = {"visible":False,"pages":(1,),"dpi":120}
    monthly_owner = monthly_preview["owner"]

    change_workflow(app, "Purchase order")
    next(button for button in app.button if button.label == "Built by Evan Roden").click().run()
    # The canned sample uses a TXT placeholder. Supply an actual invented PDF
    # so source-view identity and page retention exercise the real viewer.
    original_quote = pdf_bytes(2)
    app.session_state["uploaded_file_bytes"] = original_quote
    app.session_state["uploaded_file_name"] = "Synthetic_Original_Quote.pdf"
    app.session_state["extract_hash"] = sha256(original_quote).hexdigest()
    app.session_state["po_upload_available"] = True
    app.run()
    original_quote = app.session_state["uploaded_file_bytes"]
    quote_identity = app.session_state["extract_hash"]
    po_identity = app.session_state["po_workspace_identity"]
    next(value for value in app.text_area if value.label == "Scope of Work").set_value("Synthetic manually corrected PO scope.").run()
    text(app, "PO/CO amount — final total including every fee and tax *").set_value("001900.00").run()
    text(app, "Your name (Requester / Asset Manager) *").set_value("Synthetic PO Reviewer").run()
    po_view = preview_views(app)
    assert po_view
    po_owner = app.session_state["_workspace_reference_owners"][sha256(po_identity.encode()).hexdigest()]
    po_owner["entries"]["purchase_quote"]["view"] = {"visible":False,"pages":(0,),"dpi":120}

    receipts = seed_expense_sources(app)
    change_workflow(app, "Expense reimbursement")
    first = sha256(receipts[0][1]).hexdigest()[:12]
    second = sha256(receipts[1][1]).hexdigest()[:12]
    next(value for value in app.toggle if value.key == "expense_split_" + first).set_value(True).run()
    receipt_field(app, "expense_amount_" + first).set_value("11.00").run()
    receipt_field(app, "expense_amount_" + first + "_line_2").set_value("7.00").run()
    receipt_field(app, "expense_description_" + first + "_line_2").set_value("Separate synthetic split purpose.").run()
    receipt_field(app, "expense_amount_" + second).set_value("23.50").run()
    expense_identity = app.session_state["expense_report_memory_context"]
    expense_owner = app.session_state["_workspace_reference_owners"][sha256(expense_identity.encode()).hexdigest()]
    selected = expense_owner["entries"]["expense_receipt_" + first]
    selected["view"] = {"visible":True,"pages":(1,2),"dpi":96}
    app.run()  # Actual bounded PDF/raster store work, not OCR or report assembly.
    assert not selected["error"]
    assert selected["ticket"].pages == 3
    ticket = selected["ticket"]
    expense_view = preview_views(app)
    stored = {path.relative_to(gate["root"]): sha256(path.read_bytes()).hexdigest()
              for path in gate["root"].rglob("*") if path.is_file()}

    # Both directions, with idle reruns on the other workflows so Streamlit's
    # real widget cleanup occurs rather than an immediate fake state swap.
    for _ in range(2):
        change_workflow(app, "Monthly report")
        app.run()
        assert next(value for value in app.text_area if value.label == "Activity summary").value == monthly_words
        assert app.session_state[draft_key] == monthly_draft
        assert preview_views(app) == monthly_view
        assert app.session_state[state_key]["owner"] == monthly_owner
        assert app.session_state[state_key]["page_requests"]["activity"] == {"visible":False,"pages":(1,),"dpi":120}
        change_workflow(app, "Purchase order")
        app.run()
        assert next(value for value in app.text_area if value.label == "Scope of Work").value == "Synthetic manually corrected PO scope."
        assert text(app, "PO/CO amount — final total including every fee and tax *").value == "001900.00"
        assert app.session_state["uploaded_file_bytes"] == original_quote
        assert app.session_state["extract_hash"] == quote_identity
        assert app.session_state["po_workspace_identity"] == po_identity
        assert preview_views(app) == po_view
        assert po_owner["entries"]["purchase_quote"]["view"] == {"visible":False,"pages":(0,),"dpi":120}
        change_workflow(app, "Expense reimbursement")
        app.run()
        assert receipt_field(app, "expense_amount_" + first).value == "11.00"
        assert receipt_field(app, "expense_amount_" + first + "_line_2").value == "7.00"
        assert receipt_field(app, "expense_description_" + first + "_line_2").value == "Separate synthetic split purpose."
        assert receipt_field(app, "expense_amount_" + second).value == "23.50"
        assert app.session_state["expense_receipt_files"] == receipts
        assert app.session_state["expense_report_memory_context"] == expense_identity
        assert preview_views(app) == expense_view
        assert selected["ticket"] == ticket
        assert selected["view"] == {"visible":True,"pages":(1,2),"dpi":96}
        assert all(key not in app.session_state["expense_draft_snapshot"] for key in ("expense_receipt_files","expense_generated_package"))
    assert gate["business_writes"] == [] and gate["attempts"] == []
    assert {path.relative_to(gate["root"]): sha256(path.read_bytes()).hexdigest()
            for path in gate["root"].rglob("*") if path.is_file()} == stored

    # Deliberate removal persists through the same workflow cycle, while the
    # other receipt's values and the Monthly/PO drafts remain intact.
    next(button for button in app.button if button.key == "expense_remove_receipt_" + second).click().run()
    change_workflow(app, "Purchase order")
    change_workflow(app, "Monthly report")
    change_workflow(app, "Expense reimbursement")
    assert app.session_state["expense_receipt_files"] == receipts[:1]
    assert receipt_field(app, "expense_amount_" + first + "_line_2").value == "7.00"
    assert not any(key.startswith("expense_") and second in key for key in app.session_state["expense_draft_snapshot"])
    assert gate["business_writes"] == [] and gate["attempts"] == []
