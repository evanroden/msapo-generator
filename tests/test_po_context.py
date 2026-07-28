from types import SimpleNamespace

from app.contracts import RRH_CONTRACT
from app.eml_builder import DAVID_EMAIL
from app.po_context import build_po_context


def _analysis(**overrides):
    values = {
        "vendor_name": "Vendor Co",
        "project_description": "Repair chilled water pump",
        "facility_name": "Tulane",
        "facility_address": "Example address",
        "scope_of_work": "Repair the chilled water pump and test operation.",
        "contact_name": "Alex Vendor",
        "contact_email": "alex@example.com",
        "subtotal_amount": "$100.00",
        "tax_amount": "$8.00",
        "total_amount": "$108.00",
        "short_description": "Pump Repair",
        "tax_status": "included",
        "tax_note": "Tax is itemized.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_generic_context_reuses_finalized_values_and_original_quote_bytes(tmp_path):
    docx = tmp_path / "internal.docx"
    pdf = tmp_path / "internal.pdf"
    docx.write_bytes(b"docx bytes")
    pdf.write_bytes(b"pdf bytes")

    state = {
        "analysis": _analysis(),
        "analysis_token": "tok",
        "epo_mode": False,
        "quote_text": "quote text",
        "uploaded_file_name": "vendor original.pdf",
        "uploaded_file_bytes": b"original quote bytes",
        "docx_path": docx,
        "pdf_path": pdf,
        "contract_tok": "Tulane",
        "gsite_tok_Tulane": "Tulane",
        "gcat_tok_Tulane": "Repairs",
        "gcost_tok_Tulane": "TUL-REPAIR",
        "recip_tok_Tulane": "administrator@example.com",
        "noasset_tok_Tulane_Tulane": False,
        "asset_tok_Tulane_Tulane": "EEA-CWP-07",
        "contact_tok": "Final Contact",
        "cemail_tok": "final@example.com",
        "desc_tok": "Final Pump Repair",
        "sub_tok": "$100.00",
        "tax_tok": "$8.00",
        "total_tok": "$108.00",
    }

    context = build_po_context(state, {"EPC_REQUESTER_NAME": "Evan Roden"})

    assert context is not None
    assert context.ready
    assert context.fields["requester_name"] == "Evan Roden"
    assert context.fields["contract"] == "Tulane"
    assert context.fields["site"] == "Tulane"
    assert context.fields["cost_code"] == "TUL-REPAIR"
    assert context.fields["asset_id"] == "EEA-CWP-07"
    assert context.fields["contact_name"] == "Final Contact"
    assert context.fields["description"] == "Final Pump Repair"
    assert context.attachments[0] == ("vendor original.pdf", b"original quote bytes")
    assert context.attachments[1][0].startswith("Tulane Tulane")
    assert context.attachments[1][0].endswith(".docx")
    assert context.attachments[1][1] == b"docx bytes"
    assert context.attachments[2][1] == b"pdf bytes"


def test_rrh_equipment_only_context_uses_known_cost_code_and_david():
    state = {
        "analysis": _analysis(
            facility_name="United Memorial Medical Center",
            facility_address="127 North St, Batavia, NY 14020",
        ),
        "analysis_token": "tok",
        "epo_mode": True,
        "quote_text": "equipment quote",
        "uploaded_file_name": "equipment.pdf",
        "uploaded_file_bytes": b"equipment bytes",
        "contract_tok": RRH_CONTRACT,
        "site_tok": "UMMC",
        "cat_tok_united_memorial": "Building Automation",
        "total_tok": "$108.00",
    }

    context = build_po_context(state, {})

    assert context is not None
    assert context.ready
    assert context.fields["order_type"] == "Equipment-only PO"
    assert context.fields["site"] == "UMMC"
    assert context.fields["cost_code"] == "01CEABA"
    assert context.fields["administrator_email"] == DAVID_EMAIL
    assert context.fields["asset_id"] == "None Applicable"
    assert context.attachments == (("equipment.pdf", b"equipment bytes"),)


def test_context_reports_missing_submission_requirements():
    state = {
        "analysis": _analysis(total_amount=None),
        "analysis_token": "tok",
        "epo_mode": False,
    }

    context = build_po_context(state, {})

    assert context is not None
    assert not context.ready
    assert "Select the contract in Email Process Control." in context.warnings
    assert "Confirm the total amount before submission." in context.warnings
    assert "No quote or generated document is available to attach." in context.warnings
    assert "Regenerate the MSAPO document before submission." in context.warnings
