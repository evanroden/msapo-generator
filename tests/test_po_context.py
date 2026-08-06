import hashlib
from types import SimpleNamespace

import pytest

from app.po_context import _document_signature, build_po_context
from app.po_rules import (
    EQUIPMENT_ACCOUNT,
    EQUIPMENT_PO,
    MATERIALS_ACCOUNT,
    ONSITE_LABOR,
    ONSITE_RENTAL,
    OUTSIDE_RENTALS_ACCOUNT,
    RENTAL_AGREEMENT,
    SERVICE_AGREEMENT,
    STANDARD_PO_OVER_25K,
    STANDARD_PO_UNDER_25K,
    SUBCONTRACTOR_ACCOUNT,
    THIRD_PARTY_SHIPPING,
    VENDOR_DELIVERY,
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
        f"noasset_{token}_Tulane_Tulane": asset == "None Applicable",
        f"asset_{token}_Tulane_Tulane": asset,
        f"contact_{token}": "Final Contact",
        f"cemail_{token}": "final@example.com",
        f"desc_{token}": "Final Pump Repair",
        f"total_{token}": total,
        f"total_confirmed_{token}": True,
        "scope_pdf_bytes": b"%PDF-1.7\nsynthetic scope pdf",
        "scope_pdf_signature": _document_signature(
            token,
            "Tulane",
            "Tulane",
            ["Labor", "Startup testing"],
            ["Painting"],
        ),
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
        (THIRD_PARTY_SHIPPING, "$108.00", EQUIPMENT_ACCOUNT, EQUIPMENT_PO),
        (
            VENDOR_DELIVERY,
            "$24,999.99",
            MATERIALS_ACCOUNT,
            STANDARD_PO_UNDER_25K,
        ),
        (
            VENDOR_DELIVERY,
            "$25,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
    ],
)
def test_context_applies_the_canonical_classification(
    route, total, expected_account, expected_agreement
):
    context = build_po_context(
        _state(route=route, total=total),
        {"EPC_REQUESTER_NAME": "must not become the requester"},
    )

    assert context is not None
    assert context.fields["requester_name"] == ""
    assert context.fields["request_type"] == "PO"
    assert context.fields["object_account"] == expected_account
    assert context.fields["agreement_type"] == expected_agreement
    assert context.fields["dispatch_service_center"] == "NA"
    assert context.fields["total"] == total
    assert context.fields["leave_request_completed"] == ""
    assert context.fields["po_number"] == ""
    assert context.fields["work_order_number"] == ""
    assert context.fields["original_po_number"] == ""
    assert [name for name, _ in context.attachments] == [
        "vendor original.pdf",
        "Tulane Tulane Repair chilled water pump Scope.pdf",
    ]
    assert context.attachments[0][1] == b"original quote bytes"
    assert context.attachments[1][1].startswith(b"%PDF-")
    assert not any("Choose how the vendor" in warning for warning in context.warnings)


def test_asset_prefix_is_removed_and_only_number_reaches_smartsheet():
    context = build_po_context(
        _state(route=ONSITE_LABOR, asset="EEA-CWP-07"),
        {},
    )
    assert context is not None and context.ready
    assert context.fields["asset_id"] == "07"


def test_pasted_quote_becomes_the_original_text_attachment():
    state = _state(route=THIRD_PARTY_SHIPPING, uploaded=False)
    context = build_po_context(state, {})
    assert context is not None and context.ready
    assert context.attachments[0] == ("Vendor Quote.txt", b"quote text")
    assert context.attachments[1][0].endswith("Scope.pdf")


def test_stale_scope_pdf_is_excluded_and_blocks_submission():
    state = _state(route=ONSITE_LABOR)
    state["scope_pdf_signature"] = "wrong"

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert len(context.attachments) == 1
    assert any("no longer matches" in warning for warning in context.warnings)
    assert any("must contain the original quote" in warning for warning in context.warnings)


def test_total_must_be_all_in_and_explicitly_confirmed():
    state = _state(route=VENDOR_DELIVERY)
    token = state["analysis_token"]
    state[f"total_confirmed_{token}"] = False

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert "Confirm the PO/CO amount includes all fees and taxes." in context.warnings


def test_missing_route_is_blocked_instead_of_falling_back_to_legacy_epo_logic():
    state = _state(route=ONSITE_LABOR)
    token = state["analysis_token"]
    state[f"purchase_route_{token}"] = ""

    context = build_po_context(state, {})
    assert context is not None and not context.ready
    assert context.fields["object_account"] == ""
    assert context.fields["agreement_type"] == ""
    assert any("Choose how the vendor" in warning for warning in context.warnings)
