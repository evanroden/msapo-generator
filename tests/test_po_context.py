import hashlib
from types import SimpleNamespace

import pytest

from app.po_context import (
    _document_signature,
    account_manager_memory_context_id,
    build_po_context,
    vendor_contact_memory_context_id,
)
from app.po_rules import (
    EQUIPMENT_ACCOUNT,
    EQUIPMENT_PO,
    EQUIPMENT_PURCHASE,
    MATERIALS_ACCOUNT,
    MATERIALS_PURCHASE,
    ONSITE_LABOR,
    ONSITE_RENTAL,
    OUTSIDE_RENTALS_ACCOUNT,
    RENTAL_AGREEMENT,
    SERVICE_AGREEMENT,
    STANDARD_PO_OVER_25K,
    STANDARD_PO_UNDER_25K,
    SUBCONTRACTOR_ACCOUNT,
)


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
        "request_type_guess": "PO",
        "original_po_number": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _token(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _state(
    *,
    route: str,
    total: str = "$108.00",
    uploaded: bool = True,
    asset: str = "None Applicable",
    request_type: str = "PO",
    original_po: str = "",
):
    quote_text = "quote text"
    quote_bytes = b"original quote bytes"
    token = _token(quote_text)
    state = {
        "analysis": _analysis(total_amount=total),
        "analysis_token": token,
        "quote_text": quote_text,
        f"purchase_route_{token}": route,
        f"contract_{token}": "Tulane",
        f"gsite_{token}_Tulane": "Tulane",
        f"gcat_{token}_Tulane": "Repairs",
        f"gcost_{token}_Tulane": "TUL-REPAIR",
        f"asset_{token}_Tulane_Tulane": asset,
        f"request_type_{token}": request_type,
        f"original_po_{token}": original_po,
        f"requester_{token}_Tulane": "Final Requester",
        f"job_number_{token}_Tulane": "TULANE-695000028-ES JOB CCJ",
        f"vendor_{token}": "Corrected Vendor Co",
        f"contact_{token}": "Final Contact",
        f"cemail_{token}": "final@example.com",
        f"desc_{token}": "Final Pump Repair",
        f"scope_{token}": "Repair the chilled water pump and test operation.",
        f"total_{token}": total,
        f"instructions_{token}": "Escort required",
        "scope_pdf_bytes": b"%PDF-1.7\nsynthetic scope pdf",
        "scope_pdf_signature": _document_signature(
            token,
            "Tulane",
            "Tulane",
            ["Labor", "Startup testing"],
            ["Painting"],
            vendor="Corrected Vendor Co",
            scope="Repair the chilled water pump and test operation.",
        ),
        "quote_source": "upload" if uploaded else "paste",
    }
    if uploaded:
        state.update(
            {
                "extracted_text": quote_text,
                "uploaded_file_name": "vendor original.pdf",
                "uploaded_file_bytes": quote_bytes,
                "extract_hash": hashlib.sha256(quote_bytes).hexdigest(),
            }
        )
    return state


@pytest.mark.parametrize(
    ("route", "total", "expected_account", "expected_agreement"),
    [
        (ONSITE_LABOR, "$108.00", SUBCONTRACTOR_ACCOUNT, SERVICE_AGREEMENT),
        (ONSITE_RENTAL, "$108.00", OUTSIDE_RENTALS_ACCOUNT, RENTAL_AGREEMENT),
        (EQUIPMENT_PURCHASE, "$108.00", EQUIPMENT_ACCOUNT, EQUIPMENT_PO),
        (
            MATERIALS_PURCHASE,
            "$24,999.99",
            MATERIALS_ACCOUNT,
            STANDARD_PO_UNDER_25K,
        ),
        (
            MATERIALS_PURCHASE,
            "$25,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
    ],
)
def test_context_applies_approved_classification_matrix(
    route, total, expected_account, expected_agreement
):
    context = build_po_context(
        _state(route=route, total=total),
        {"EPC_REQUESTER_NAME": "must not become the requester"},
    )

    assert context is not None
    assert context.fields["requester_name"] == "Final Requester"
    assert context.fields["request_type"] == "PO"
    assert context.fields["object_account"] == expected_account
    assert context.fields["agreement_type"] == expected_agreement
    assert context.fields["dispatch_service_center"] == "NA"
    assert context.fields["total"] == total
    assert context.fields["leave_request_completed"] == ""
    assert context.fields["po_number"] == ""
    assert context.fields["work_order_number"] == ""
    assert context.fields["original_po_number"] == ""
    assert context.fields["vendor"] == "Corrected Vendor Co"
    assert context.fields["instructions"] == "Escort required"
    assert [name for name, _ in context.attachments] == [
        "vendor original.pdf",
        "Tulane Tulane Repair chilled water pump MSAPO.pdf",
    ]


def test_full_asset_code_reaches_smartsheet_unchanged():
    context = build_po_context(
        _state(route=ONSITE_LABOR, asset="EEA-CWP-07"),
        {},
    )
    assert context is not None and context.ready
    assert context.fields["asset_id"] == "EEA-CWP-07"


def test_description_of_work_is_hard_capped_at_twenty_characters():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"desc_{token}"] = "Replace cooling tower fan assembly"

    context = build_po_context(state, {})

    assert context is not None
    assert context.fields["description_of_work"] == "Replace cooling towe"
    assert len(context.fields["description_of_work"]) == 20
    assert "Repair the chilled water pump" in context.fields["scope_of_work"]


def test_edited_scope_is_exported_and_invalidates_the_previous_pdf():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"scope_{token}"] = (
        "Replace the pump and verify operation with Facilities."
    )

    stale = build_po_context(state, {})

    assert stale is not None and not stale.ready
    assert stale.fields["scope_of_work"].startswith(
        "Replace the pump and verify operation with Facilities."
    )
    assert any("Regenerate" in warning for warning in stale.warnings)

    state["scope_pdf_signature"] = _document_signature(
        token,
        "Tulane",
        "Tulane",
        ["Labor", "Startup testing"],
        ["Painting"],
        vendor="Corrected Vendor Co",
        scope=state[f"scope_{token}"],
    )
    refreshed = build_po_context(state, {})

    assert refreshed is not None and refreshed.ready
    assert refreshed.fields["scope_of_work"].startswith(
        "Replace the pump and verify operation with Facilities."
    )


def test_change_order_requires_and_exports_the_original_po_number():
    missing = build_po_context(
        _state(route=ONSITE_LABOR, request_type="CHANGE ORDER"), {}
    )
    assert missing is not None and not missing.ready
    assert any("original PO number" in warning for warning in missing.warnings)

    complete = build_po_context(
        _state(
            route=ONSITE_LABOR,
            request_type="CHANGE ORDER",
            original_po="4500123456",
        ),
        {},
    )
    assert complete is not None and complete.ready
    assert complete.fields["original_po_number"] == "4500123456"


def test_new_po_forces_original_po_blank_even_if_stale_state_has_a_value():
    context = build_po_context(
        _state(route=ONSITE_LABOR, request_type="PO", original_po="stale"), {}
    )
    assert context is not None
    assert context.fields["original_po_number"] == ""


def test_additional_information_never_inherits_the_tax_note():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"instructions_{token}"] = ""
    context = build_po_context(state, {})
    assert context is not None
    assert context.fields["instructions"] == ""
    assert context.fields["tax_status"] == "included"


def test_requester_memory_identity_stays_stable_while_correcting_the_name():
    first_state = _state(route=ONSITE_LABOR)
    second_state = _state(route=ONSITE_LABOR)
    token = first_state["analysis_token"]
    second_state[f"requester_{token}_Tulane"] = "Corrected Requester"

    first = build_po_context(first_state, {})
    second = build_po_context(second_state, {})

    assert first is not None and second is not None
    assert first.context_id != second.context_id
    assert account_manager_memory_context_id(first) == account_manager_memory_context_id(second)


def test_vendor_contact_memory_identity_stays_stable_while_correcting_contact():
    first_state = _state(route=ONSITE_LABOR)
    second_state = _state(route=ONSITE_LABOR)
    token = first_state["analysis_token"]
    second_state[f"vendor_{token}"] = "Corrected Vendor Name"
    second_state[f"contact_{token}"] = "Corrected Representative"
    second_state[f"cemail_{token}"] = "corrected@example.com"
    second_state["scope_pdf_signature"] = _document_signature(
        token,
        "Tulane",
        "Tulane",
        ["Labor", "Startup testing"],
        ["Painting"],
        vendor="Corrected Vendor Name",
        scope="Repair the chilled water pump and test operation.",
    )

    first = build_po_context(first_state, {})
    second = build_po_context(second_state, {})

    assert first is not None and second is not None
    assert first.context_id != second.context_id
    assert vendor_contact_memory_context_id(
        first
    ) == vendor_contact_memory_context_id(second)


def test_vendor_representative_name_and_email_are_required():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"contact_{token}"] = ""
    state[f"cemail_{token}"] = ""

    context = build_po_context(state, {})

    assert context is not None and not context.ready
    assert any("representative name" in warning for warning in context.warnings)
    assert any("representative email" in warning for warning in context.warnings)


def test_pasted_quote_becomes_the_original_text_attachment():
    state = _state(route=EQUIPMENT_PURCHASE, uploaded=False)
    context = build_po_context(state, {})
    assert context is not None and context.ready
    assert context.attachments[0] == ("Vendor Quote.txt", b"quote text")
    assert context.attachments[1][0].endswith("MSAPO.pdf")


def test_explicit_paste_source_never_reuses_a_stale_upload_with_identical_text():
    state = _state(route=EQUIPMENT_PURCHASE, uploaded=True)
    state["quote_source"] = "paste"

    context = build_po_context(state, {})

    assert context is not None and context.ready
    assert context.attachments[0] == ("Vendor Quote.txt", b"quote text")


def test_vendor_change_invalidates_the_vendor_bearing_scope_pdf():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"vendor_{token}"] = "Different Vendor"

    context = build_po_context(state, {})

    assert context is not None and not context.ready
    assert any("Regenerate" in warning for warning in context.warnings)


def test_stale_scope_pdf_is_excluded_and_blocks_submission():
    state = _state(route=ONSITE_LABOR)
    state["scope_pdf_signature"] = "wrong"

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert len(context.attachments) == 1
    assert any("no longer matches" in warning for warning in context.warnings)
    assert any("must contain the original quote" in warning for warning in context.warnings)


def test_no_tax_confirmation_state_is_required():
    state = _state(route=MATERIALS_PURCHASE)
    assert not any("total_confirmed" in key for key in state)
    context = build_po_context(state, {})
    assert context is not None and context.ready


def test_missing_route_is_blocked_instead_of_guessing_during_export():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"purchase_route_{token}"] = ""

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert context.fields["object_account"] == ""
    assert context.fields["agreement_type"] == ""
    assert any("Choose how the vendor" in warning for warning in context.warnings)
