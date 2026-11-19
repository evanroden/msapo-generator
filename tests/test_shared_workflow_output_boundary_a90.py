"""A90: exercised three-workflow output boundary, not just widget persistence.

Synthetic AppTest runs the real shared Streamlit selector and expense editor.
The PO PDF builder is local and deterministic; actual expense workbook creation
uses the approved template. No live Smartsheet, mail, OCR, production writes,
served browser JavaScript, real-source documents, or PDF conversion are tested.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
import tempfile
from urllib.parse import parse_qs, urlsplit

import pymupdf as fitz
from openpyxl import load_workbook

from app import expense_ui, smartsheet, web_ui
from app.contracts import RRH_CONTRACT
from app.monthly_report_editor import _signature
from app.expense_report import (
    build_expense_workbook,
    total_reimbursement,
    validate_expense_report,
)
from app.po_context import build_po_context
# Fixture dependencies are resolved in this test module, not the module
# where populated_workflows was originally defined.
from test_expense_workspace_isolation import isolated_expenses  # noqa: F401
from test_workflow_return_preservation import (
    change_workflow,
    populated_workflows,
    receipt_field,
    seed_expense_sources,
    text,
)


def _control(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def test_monthly_po_expense_monthly_preserves_identity_and_corrected_workbook(
    populated_workflows, monkeypatch
):
    app, gate = populated_workflows
    monthly_text = "A90_MONTHLY_ONLY: manually accepted September activity."
    _control(app, "text_area", "Activity summary").set_value(monthly_text).run()
    # Select the working report by its exact contract/profile/period key;
    # other guided session keys can also end in "_draft".
    monthly_key = (
        "report_guided_"
        + _signature((RRH_CONTRACT, "synthetic-guided", "2026-09"))
        + "_draft"
    )
    assert monthly_key in app.session_state.filtered_state
    monthly_draft = app.session_state[monthly_key]
    monthly_route = app.query_params["workflow"]
    assert monthly_route == ["monthly"]

    # Generate a real one-page synthetic PDF for the manual two-file handoff,
    # without launching a renderer or calling the Smartsheet API.
    built = []

    def synthetic_form(**kwargs):
        built.append(kwargs)
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((50, 50), "A90 synthetic reviewed MSAPO")
            return document.tobytes()

    monkeypatch.setattr(web_ui, "build_msapo_pdf", synthetic_form)
    change_workflow(app, "Purchase order")
    _control(app, "button", "Load synthetic quote").click().run()
    original_quote = app.session_state["uploaded_file_bytes"]
    original_quote_hash = sha256(original_quote).hexdigest()
    po_identity = app.session_state["po_workspace_identity"]
    po_scope = "A90_PO_ONLY: manually reviewed vendor work."
    _control(app, "text_area", "Scope of Work").set_value(po_scope).run()
    text(app, "Your name (Requester / Asset Manager) *").set_value(
        "A90 PO-only reviewer"
    ).run()
    _control(app, "button", "Generate both files and Smartsheet link").click().run()
    assert not app.exception and len(built) == 1
    assert len(app.get("download_button")) == 2

    context = build_po_context(app.session_state.filtered_state)
    assert context.ready and len(context.attachments) == 2
    assert context.attachments[0][1] == original_quote
    assert sha256(context.attachments[0][1]).hexdigest() == original_quote_hash
    generated_form_hash = sha256(context.attachments[1][1]).hexdigest()
    with fitz.open(stream=context.attachments[1][1], filetype="pdf") as document:
        assert len(document) == 1
        assert "A90 synthetic reviewed MSAPO" in document[0].get_text()
    links = app.get("link_button")
    assert len(links) == 1
    query = parse_qs(urlsplit(links[0].url).query)
    for name, label in (
        ("requester_name", "REQUESTER"),
        ("site_location", "SITE NUMBER / LOCATION"),
        ("vendor", "VENDOR NAME"),
        ("contact_name", "VENDOR CONTACT NAME"),
        ("contact_email", "VENDOR CONTACT EMAIL"),
        ("asset_id", "ASSET ID"),
    ):
        assert context.fields[name]
        assert query[label] == [context.fields[name]]
    assert "PO #" not in query and "WORK ORDER #" not in query
    po_fingerprint = smartsheet.submission_fingerprint(
        context.fields, list(context.attachments)
    )

    receipts = seed_expense_sources(app)
    original_receipt_hashes = tuple(sha256(raw).hexdigest() for _, raw, _ in receipts)
    snapshots = []
    actual_warnings = expense_ui.expense_report_warnings

    def capture_review(details, items, mileage_items):
        snapshots.append((details, tuple(items), tuple(mileage_items)))
        return actual_warnings(details, items, mileage_items)

    monkeypatch.setattr(expense_ui, "expense_report_warnings", capture_review)
    change_workflow(app, "Expense reimbursement")
    first, second = (digest[:12] for digest in original_receipt_hashes)
    receipt_field(app, "expense_amount_" + first).set_value("17.25").run()
    receipt_field(app, "expense_amount_" + second).set_value("24.75").run()
    assert snapshots
    details, items, mileage = snapshots[-1]
    assert [item.amount for item in items] == ["17.25", "24.75"]
    assert total_reimbursement(items, mileage) == Decimal("42.00")
    assert _control(app, "button", "Generate expense report and email draft").disabled

    # Missing signature confirmation is a genuine preflight block; the workbook
    # is tested only with an explicitly confirmed synthetic signature.
    confirmed = replace(details, employee_signature_confirmed=True)
    assert validate_expense_report(confirmed, list(items), mileage) == []
    # openpyxl writes each worksheet through a named temporary file, and the
    # isolation gate allows writes only under its own temporary root.
    monkeypatch.setattr(tempfile, "tempdir", str(gate["root"]))
    workbook_bytes = build_expense_workbook(
        confirmed, list(items), mileage_items=mileage
    )
    workbook_hash = sha256(workbook_bytes).hexdigest()
    workbook = load_workbook(BytesIO(workbook_bytes))
    form = workbook["EXPENSE REIMBURSEMENT"]
    assert [form["H24"].value, form["H25"].value] == [17.25, 24.75]
    assert form["Q60"].value == "=H18+H39+H59"
    assert form["C5"].value == details.employee_name
    assert workbook.calculation.fullCalcOnLoad
    assert "RECEIPTS" in workbook.sheetnames
    # PO contact/scope and monthly text have no place in an expense workbook.
    cell_text = "\n".join(
        str(cell.value) for sheet in workbook for row in sheet for cell in row
        if cell.value is not None
    )
    assert monthly_text not in cell_text
    assert po_scope not in cell_text
    assert "A90 PO-only reviewer" not in cell_text
    assert workbook_hash and generated_form_hash

    # A malformed corrected receipt must fail closed. Restore the exact prior
    # amount before navigating, and do not reuse the valid workbook for it.
    receipt_field(app, "expense_amount_" + first).set_value("not a price").run()
    assert _control(app, "button", "Generate expense report and email draft").disabled
    assert validate_expense_report(
        replace(snapshots[-1][0], employee_signature_confirmed=True),
        list(snapshots[-1][1]), snapshots[-1][2],
    )
    assert "expense_generated_package" not in app.session_state
    receipt_field(app, "expense_amount_" + first).set_value("17.25").run()
    assert total_reimbursement(snapshots[-1][1], snapshots[-1][2]) == Decimal("42.00")

    # Allow Streamlit to remove hidden widget keys on idle reruns. The session
    # mirrors must restore reviewed values without re-running builders or I/O.
    change_workflow(app, "Monthly report")
    app.run()
    assert _control(app, "text_area", "Activity summary").value == monthly_text
    assert app.session_state[monthly_key] == monthly_draft
    change_workflow(app, "Purchase order")
    app.run()
    assert app.session_state["po_workspace_identity"] == po_identity
    assert app.session_state["uploaded_file_bytes"] == original_quote
    assert sha256(app.session_state["uploaded_file_bytes"]).hexdigest() == original_quote_hash
    assert _control(app, "text_area", "Scope of Work").value == po_scope
    assert sha256(app.session_state["scope_pdf_bytes"]).hexdigest() == generated_form_hash
    assert smartsheet.submission_fingerprint(
        build_po_context(app.session_state.filtered_state).fields,
        list(build_po_context(app.session_state.filtered_state).attachments),
    ) == po_fingerprint
    change_workflow(app, "Expense reimbursement")
    app.run()
    assert receipt_field(app, "expense_amount_" + first).value == "17.25"
    assert receipt_field(app, "expense_amount_" + second).value == "24.75"
    assert tuple(sha256(raw).hexdigest() for _, raw, _ in
                 app.session_state["expense_receipt_files"]) == original_receipt_hashes
    assert total_reimbursement(snapshots[-1][1], snapshots[-1][2]) == Decimal("42.00")
    assert not any(key in app.session_state["expense_draft_snapshot"]
                   for key in ("expense_receipt_files", "expense_generated_package"))
    change_workflow(app, "Monthly report")
    app.run()
    assert _control(app, "text_area", "Activity summary").value == monthly_text
    assert app.session_state[monthly_key] == monthly_draft
    assert len(built) == 1
    assert gate["business_writes"] == [] and gate["attempts"] == []
