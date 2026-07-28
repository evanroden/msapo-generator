import hashlib
from types import SimpleNamespace

from app.contracts import RRH_CONTRACT
from app.eml_builder import DAVID_EMAIL
from app.po_context import _document_signature, build_po_context


def _analysis(**overrides):
    values = {
        "vendor_name": "Vendor Co",
        "project_description": "Repair chilled water pump",
        "facility_name": "Tulane",
        "facility_address": "Example address",
        "scope_of_work": "Repair the chilled water pump and test operation.",
        "inclusions": ["Labor", "Startup testing"],
        "exclusions": ["Painting"],
        "ai_assumptions": [],
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


def _token(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def test_generic_context_reuses_finalized_values_and_original_quote_bytes(tmp_path):
    quote_text = "quote text"
    quote_bytes = b"original quote bytes"
    token = _token(quote_text)
    docx = tmp_path / "internal.docx"
    pdf = tmp_path / "internal.pdf"
    docx.write_bytes(b"docx bytes")
    pdf.write_bytes(b"pdf bytes")

    state = {
        "analysis": _analysis(),
        "analysis_token": token,
        "epo_mode": False,
        "quote_text": quote_text,
        "extracted_text": quote_text,
        "uploaded_file_name": "vendor original.pdf",
        "uploaded_file_bytes": quote_bytes,
        "extract_hash": hashlib.sha256(quote_bytes).hexdigest(),
        "docx_path": docx,
        "pdf_path": pdf,
        f"contract_{token}": "Tulane",
        f"gsite_{token}_Tulane": "Tulane",
        f"gcat_{token}_Tulane": "Repairs",
        f"gcost_{token}_Tulane": "TUL-REPAIR",
        f"recip_{token}_Tulane": "administrator@example.com",
        f"noasset_{token}_Tulane_Tulane": False,
        f"asset_{token}_Tulane_Tulane": "EEA-CWP-07",
        f"contact_{token}": "Final Contact",
        f"cemail_{token}": "final@example.com",
        f"desc_{token}": "Final Pump Repair",
        f"sub_{token}": "$100.00",
        f"tax_{token}": "$8.00",
        f"total_{token}": "$108.00",
    }
    state["document_signature"] = _document_signature(
        token, "Tulane", "Tulane", ["Labor", "Startup testing"], ["Painting"]
    )

    context = build_po_context(state, {"EPC_REQUESTER_NAME": "Evan Roden"})

    assert context is not None and context.ready
    assert context.fields["requester_name"] == "Evan Roden"
    assert context.fields["contract"] == "Tulane"
    assert context.fields["site"] == "Tulane"
    assert context.fields["cost_code"] == "TUL-REPAIR"
    assert context.fields["asset_id"] == "EEA-CWP-07"
    assert context.fields["contact_name"] == "Final Contact"
    assert "Inclusions:" in context.fields["scope_of_work"]
    assert "Painting" in context.fields["scope_of_work"]
    assert context.attachments[0] == ("vendor original.pdf", quote_bytes)
    assert context.attachments[1][0].startswith("Tulane Tulane")
    assert context.attachments[1][1] == b"docx bytes"
    assert context.attachments[2][1] == b"pdf bytes"
    assert len(context.context_id) == 20


def test_pasted_text_does_not_attach_a_previous_uploaded_file():
    pasted = "new pasted quote"
    token = _token(pasted)
    state = {
        "analysis": _analysis(),
        "analysis_token": token,
        "epo_mode": True,
        "quote_text": pasted,
        "extracted_text": "old uploaded quote",
        "uploaded_file_name": "old.pdf",
        "uploaded_file_bytes": b"old bytes",
        "extract_hash": hashlib.sha256(b"old bytes").hexdigest(),
        f"contract_{token}": RRH_CONTRACT,
        f"site_{token}": "UMMC",
        f"cat_{token}_united_memorial": "Building Automation",
        f"total_{token}": "$108.00",
    }

    context = build_po_context(state, {})
    assert context is not None
    assert context.attachments == (("Vendor Quote.txt", pasted.encode()),)


def test_rrh_equipment_only_context_omits_asset_field_and_uses_david():
    quote_text = "equipment quote"
    quote_bytes = b"equipment bytes"
    token = _token(quote_text)
    state = {
        "analysis": _analysis(
            facility_name="United Memorial Medical Center",
            facility_address="127 North St, Batavia, NY 14020",
        ),
        "analysis_token": token,
        "epo_mode": True,
        "quote_text": quote_text,
        "extracted_text": quote_text,
        "uploaded_file_name": "equipment.pdf",
        "uploaded_file_bytes": quote_bytes,
        "extract_hash": hashlib.sha256(quote_bytes).hexdigest(),
        f"contract_{token}": RRH_CONTRACT,
        f"site_{token}": "UMMC",
        f"cat_{token}_united_memorial": "Building Automation",
        f"total_{token}": "$108.00",
    }

    context = build_po_context(state, {})
    assert context is not None and context.ready
    assert context.fields["order_type"] == "Equipment-only PO"
    assert context.fields["site"] == "UMMC"
    assert context.fields["cost_code"] == "01CEABA"
    assert context.fields["administrator_email"] == DAVID_EMAIL
    assert context.fields["asset_id"] == ""
    assert context.attachments == (("equipment.pdf", quote_bytes),)


def test_stale_document_signature_is_excluded_and_blocks_submission(tmp_path):
    quote_text = "quote"
    token = _token(quote_text)
    docx = tmp_path / "stale.docx"
    docx.write_bytes(b"stale")
    state = {
        "analysis": _analysis(),
        "analysis_token": token,
        "quote_text": quote_text,
        "epo_mode": False,
        "docx_path": docx,
        "document_signature": "wrong",
        f"contract_{token}": "Tulane",
        f"gsite_{token}_Tulane": "Tulane",
        f"gcost_{token}_Tulane": "TUL-REPAIR",
        f"total_{token}": "$108.00",
    }

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert not any(name.endswith(".docx") for name, _ in context.attachments)
    assert any("no longer matches" in warning for warning in context.warnings)


def test_context_reports_missing_and_mismatched_requirements():
    quote_text = "old quote"
    state = {
        "analysis": _analysis(total_amount=None),
        "analysis_token": "wrong-token",
        "quote_text": quote_text,
        "epo_mode": False,
        "uploaded_file_name": "new.pdf",
        "uploaded_file_bytes": b"new bytes",
        "extract_hash": hashlib.sha256(b"new bytes").hexdigest(),
        "extracted_text": "",
    }

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert "Select the contract in Email Process Control." in context.warnings
    assert "Confirm the total amount before submission." in context.warnings
    assert any("prior analysis" in warning for warning in context.warnings)
    assert any("fingerprint" in warning for warning in context.warnings)
    assert any("Regenerate" in warning for warning in context.warnings)
