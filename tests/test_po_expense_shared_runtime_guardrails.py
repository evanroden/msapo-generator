"""A21 shared-runtime guardrails for the independent PO and Expense workflows.

The complete served browser, live Smartsheet, real receipt OCR and authentic
client PDFs are not exercised here. Tests use isolated synthetic AppTest state,
a locally generated PDF, and fail-closed network/reader mocks. The root
Smartsheet entrypoint source-count contract remains owned by its original test.
"""
from __future__ import annotations

from hashlib import sha256
from urllib.parse import parse_qs, urlsplit

import pymupdf as fitz

from app import expense_ui
from app.po_context import build_po_context
from app.smartsheet import build_prefilled_form_url, load_config
from test_po_adaptive_workspace import isolated_purchase, sample_app
from test_po_context import _state


def _control(app, kind: str, label: str):
    return next(control for control in getattr(app, kind) if control.label == label)


def _switch(app, name: str):
    app.segmented_control[0].set_value(name).run()
    assert not app.exception


def test_po_original_pdf_prefill_and_expense_first_edit_survive_switch(isolated_purchase):
    """One joined first-use path, rather than three separate unit controls."""
    isolated, generated = isolated_purchase
    app = sample_app()
    assert app.segmented_control[0].value == "Purchase order"
    source = app.session_state["uploaded_file_bytes"]
    source_hash = sha256(source).hexdigest()
    assert app.session_state["extract_hash"] == source_hash

    _control(app, "text_input", "Your name (Requester / Asset Manager) *").set_value(
        "Synthetic Cross-Workflow Reviewer"
    ).run()
    _control(app, "button", "Generate both files and Smartsheet link").click().run()
    assert not app.exception
    assert len(generated) == 1
    assert len(app.get("download_button")) == 2

    context = build_po_context(app.session_state.filtered_state)
    assert context.ready and not context.warnings
    assert len(context.attachments) == 2
    assert context.attachments[0][1] == source
    assert sha256(context.attachments[0][1]).hexdigest() == source_hash
    assert context.attachments[1][1] == app.session_state["scope_pdf_bytes"]
    with fitz.open(stream=context.attachments[1][1], filetype="pdf") as pdf:
        assert len(pdf) == 1
        assert "Synthetic reviewed MSAPO" in pdf[0].get_text()

    links = app.get("link_button")
    assert len(links) == 1
    query = parse_qs(urlsplit(links[0].url).query)
    for field, label in (
        ("requester_name", "REQUESTER"),
        ("site_location", "SITE NUMBER / LOCATION"),
        ("vendor", "VENDOR NAME"),
        ("contact_name", "VENDOR CONTACT NAME"),
        ("contact_email", "VENDOR CONTACT EMAIL"),
        ("asset_id", "ASSET ID"),
    ):
        assert context.fields[field], f"{field} was not hydrated"
        assert query[label] == [context.fields[field]]
    assert "Clifton" in context.fields["site_location"]
    assert context.fields["contact_email"] == "mbell@example.com"
    assert "PO #" not in query and "WORK ORDER #" not in query

    _switch(app, "Expense reimbursement")
    _control(app, "text_input", "Employee name *").set_value(
        "Synthetic Expense Reviewer"
    ).run()
    assert not app.exception
    account = _control(app, "selectbox", "Account / contract *").value
    account_token = sha256(account.encode("utf-8")).hexdigest()[:10]
    expense_key = f"expense_employee_name_{account_token}"
    assert app.session_state[expense_key] == "Synthetic Expense Reviewer"

    _switch(app, "Purchase order")
    app.run()  # The second rerun exercises Streamlit's unrendered-widget cleanup.
    assert not app.exception
    assert app.session_state["uploaded_file_bytes"] == source
    assert sha256(app.session_state["uploaded_file_bytes"]).hexdigest() == source_hash
    assert app.session_state["scope_pdf_bytes"] == context.attachments[1][1]
    assert len(app.get("download_button")) == 2
    assert len(app.get("link_button")) == 1
    assert len(generated) == 1  # Neither navigation nor rerun regenerates a PO.

    _switch(app, "Expense reimbursement")
    assert _control(app, "text_input", "Employee name *").value == (
        "Synthetic Expense Reviewer"
    )
    assert app.session_state[expense_key] == "Synthetic Expense Reviewer"
    snapshot = (
        app.session_state["expense_draft_snapshot"]
        if "expense_draft_snapshot" in app.session_state
        else {}
    )
    assert not any(key.startswith("expense_receipt_files") for key in snapshot)
    assert isolated.is_dir()


def test_receipt_digests_and_draft_mirrors_are_session_owned(monkeypatch):
    """Identical uploads share an ID, not a cache object or another user's edits."""
    receipt = b"SYNTHETIC RECEIPT\nNO CUSTOMER DATA"
    mime = "image/png"
    a, b = {}, {}
    monkeypatch.setattr(expense_ui.st, "session_state", a)
    a_receipts, dropped = expense_ui._merge_receipt_sources(
        [("receipt-a.png", receipt, mime)],
        [("same-receipt-new-name.png", bytes(bytearray(receipt)), mime)],
    )
    assert [entry[0] for entry in a_receipts] == ["receipt-a.png"]
    assert dropped == ["same-receipt-new-name.png"]
    a["expense_receipt_files"] = a_receipts
    a["expense_employee_name_testaccount"] = "Session A corrected name"
    cache_a = expense_ui._content_digests()
    digest_a = expense_ui._receipt_digest(receipt)
    expense_ui.preserve_expense_draft_state()
    assert "expense_receipt_files" not in a["expense_draft_snapshot"]
    a.pop("expense_employee_name_testaccount")
    expense_ui.restore_expense_draft_state()
    assert a["expense_employee_name_testaccount"] == "Session A corrected name"

    monkeypatch.setattr(expense_ui.st, "session_state", b)
    b_receipts, dropped = expense_ui._merge_receipt_sources(
        [("receipt-b.png", receipt, mime)],
    )
    assert dropped == []
    b["expense_receipt_files"] = b_receipts
    b["expense_employee_name_testaccount"] = "Session B corrected name"
    cache_b = expense_ui._content_digests()
    assert cache_b is not cache_a
    assert expense_ui._receipt_digest(receipt) == digest_a
    expense_ui.preserve_expense_draft_state()
    assert b["expense_draft_snapshot"]["expense_employee_name_testaccount"] == (
        "Session B corrected name"
    )
    assert b["expense_receipt_files"][0][0] == "receipt-b.png"
    assert a["expense_receipt_files"][0][0] == "receipt-a.png"
    assert a["expense_employee_name_testaccount"] != b["expense_employee_name_testaccount"]


def test_stale_original_and_missing_form_contact_fail_closed():
    """A valid PDF in session state cannot bless a replaced source or blank link."""
    state = _state(route="onsite_labor")
    original_name, original_bytes = (
        state["uploaded_file_name"], state["uploaded_file_bytes"]
    )
    good = build_po_context(state)
    assert good.ready
    assert good.attachments[0] == (original_name, original_bytes)

    state["uploaded_file_bytes"] = b"REPLACED SYNTHETIC SOURCE"
    stale = build_po_context(state)
    assert not stale.ready
    assert any("original uploaded quote no longer matches" in problem.lower()
               for problem in stale.warnings)
    assert stale.attachments[0] != (original_name, original_bytes)

    config = load_config({
        "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/synthetic",
        "SMARTSHEET_URL_PREFILL_ENABLED": "true",
        "SMARTSHEET_FORM_FIELD_MAP_JSON":
            '{"request_type":"REQUEST TYPE","site_location":"SITE NUMBER / LOCATION"}',
        "SMARTSHEET_FORM_REQUIRED_FIELDS":
            "request_type,site_location,contact_name,contact_email",
    })
    result = build_prefilled_form_url({
        "request_type": "PO",
        "site_location": "SYNTHETIC SITE",
        "contact_name": "Synthetic Vendor",
        "contact_email": "vendor@example.invalid",
    }, config)
    assert result.missing_required == ("contact_name", "contact_email")
    assert "VENDOR CONTACT NAME" not in result.url
    assert "VENDOR CONTACT EMAIL" not in result.url


def test_checked_in_runtime_has_no_automatic_po_row_writer():
    """An enabled form-prefill URL must not turn on Smartsheet API creation."""
    import re
    from pathlib import Path

    root = Path(__file__).parents[1]
    deployment = (root / "render.yaml").read_text(encoding="utf-8")
    inline = (root / "app" / "smartsheet_inline.py").read_text(encoding="utf-8")
    legacy = (root / "pages" / "2_Smartsheet_PO.py").read_text(encoding="utf-8")
    assert re.search(
        r"- key: SMARTSHEET_API_MODE\s*\n\s*value: disabled(?:\s|$)",
        deployment,
    )
    assert 'SMARTSHEET_URL_PREFILL_ENABLED\n        value: "true"' in deployment
    assert "submit_po(" not in inline
    assert "submit_po(" not in legacy
