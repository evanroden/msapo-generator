import hashlib
from datetime import date
from types import SimpleNamespace

import pytest

from app import po_context, smartsheet
from app.po_context import (
    _safe_basename,
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
        "scope_pdf_generated_on": "2026-11-18",
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
        "MSAPO_TULANE_Final-Pump-Repair_2026-11-18.pdf",
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
    assert context.attachments[1][0] == "MSAPO_TULANE_Final-Pump-Repair_2026-11-18.pdf"


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


@pytest.mark.parametrize(
    "stale_source",
    (
        "changed_bytes",
        "changed_extracted_text",
        "missing_source_digest",
        "missing_original_bytes",
        "missing_original_name",
        "missing_extracted_text",
    ),
)
def test_explicit_uploaded_quote_cannot_silently_become_text_attachment(stale_source):
    """An uploaded quote must retain provable original bytes to submit."""
    state = _state(route=EQUIPMENT_PURCHASE, uploaded=True)
    if stale_source == "changed_bytes":
        state["uploaded_file_bytes"] = b"changed quote after analysis"
    elif stale_source == "changed_extracted_text":
        state["extracted_text"] = "a different quote"
    elif stale_source == "missing_source_digest":
        state.pop("extract_hash")
    elif stale_source == "missing_original_bytes":
        state.pop("uploaded_file_bytes")
    elif stale_source == "missing_original_name":
        state.pop("uploaded_file_name")
    else:
        state["extracted_text"] = ""

    context = build_po_context(state, {})

    assert context is not None
    assert context.ready is False
    assert any("re-upload" in issue.lower() for issue in context.warnings)
    # A diagnostic text representation is allowed only while its warning
    # prevents handoff. It must never make the original look verified.
    assert context.attachments[0] == ("Vendor Quote.txt", b"quote text")


def test_explicit_source_switch_to_paste_recovers_from_stale_upload():
    state = _state(route=EQUIPMENT_PURCHASE, uploaded=True)
    state["uploaded_file_bytes"] = b"stale file no longer matching review"
    assert not build_po_context(state, {}).ready

    state["quote_source"] = "paste"
    pasted = build_po_context(state, {})

    assert pasted is not None and pasted.ready
    assert pasted.attachments[0] == ("Vendor Quote.txt", b"quote text")
    assert not any("re-upload" in issue.lower() for issue in pasted.warnings)


def test_download_names_use_the_same_stem_from_context_or_direct_construction():
    state = _state(route=ONSITE_LABOR)
    context = build_po_context(state, {})
    assert context is not None and context.ready
    stem = "TULANE_Final-Pump-Repair_2026-11-18"
    assert context.attachment_base == stem
    assert _safe_basename(
        "Other", "Tulane", "Ignored long project description", False,
        short_description="Final Pump Repair", generated_on="2026-11-18",
    ) == stem

    from_context = smartsheet.download_names(context.attachments, context.attachment_base)
    from_direct = smartsheet.download_names(
        [("quote.txt", b"quote"), ("generated.pdf", b"%PDF-test")], stem
    )
    assert [name for _, name, _ in from_context] == [
        f"Quote_{stem}.pdf", f"MSAPO_{stem}.pdf"
    ]
    assert [name for _, name, _ in from_direct] == [
        f"Quote_{stem}.txt", f"MSAPO_{stem}.pdf"
    ]
    assert [data for _, _, data in from_context] == [
        state["uploaded_file_bytes"], state["scope_pdf_bytes"]
    ]


def test_short_description_ascii_punctuation_windows_safety_and_fallback_words():
    name = _safe_basename(
        "Other", 'HQ:<East>/West?*', "Very long ignored project description",
        False, short_description="Répair: Valve / Pump!", generated_on="2026-11-18",
    )
    assert name == "HQ-EAST-WEST_Repair-Valve-Pump_2026-11-18"
    assert name.isascii()
    assert not any(character in name for character in '<>:"/\\|?*')
    assert smartsheet._safe_filename(f"Quote_{name}.pdf") == f"Quote_{name}.pdf"
    assert smartsheet._safe_filename(smartsheet._safe_filename(f"MSAPO_{name}.pdf")) == f"MSAPO_{name}.pdf"

    fallback = _safe_basename(
        "Other", "CON", "Replace the enormous cooling pump assembly!", False,
        generated_on="2026-11-18",
    )
    assert fallback == "CON_Replace-the-enormous_2026-11-18"
    assert smartsheet._safe_filename(f"Quote_{fallback}.pdf") == f"Quote_{fallback}.pdf"


def test_package_generation_date_survives_a_next_day_resume_with_stable_fingerprints(monkeypatch):
    state = _state(route=ONSITE_LABOR)
    first = build_po_context(state, {})
    assert first is not None and first.ready
    first_names = smartsheet.download_names(first.attachments, first.attachment_base)
    first_key = smartsheet.submission_fingerprint(first.fields, first.attachments)
    first_attachment_ids = [
        smartsheet._attachment_fingerprint(name, data)
        for name, data in first.attachments
    ]
    first_remote_names = [
        smartsheet._api_attachment_name(name, data)
        for name, data in first.attachments
    ]

    class NextDay(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 19)

    monkeypatch.setattr(po_context, "date", NextDay)
    resumed = build_po_context(dict(state), {})
    assert resumed is not None and resumed.ready
    assert resumed.attachment_base == first.attachment_base
    assert resumed.attachments == first.attachments
    assert smartsheet.download_names(resumed.attachments, resumed.attachment_base) == first_names
    assert smartsheet.submission_fingerprint(resumed.fields, resumed.attachments) == first_key
    assert [
        smartsheet._attachment_fingerprint(name, data)
        for name, data in resumed.attachments
    ] == first_attachment_ids
    assert [
        smartsheet._api_attachment_name(name, data)
        for name, data in resumed.attachments
    ] == first_remote_names
