import json

import pytest

from app.analysis_schema import AnalysisResponseError, normalize_analysis_response


def _response(**overrides) -> str:
    values = {
        "vendor_name": "Vendor",
        "project_description": "Replace pump",
        "scope_of_work": "Replace pump and commission it.",
        "inclusions": [],
        "exclusions": [],
        "tax_status": "included",
        "ai_assumptions": [],
        "short_description": "Replace pump and test operation",
        "work_category": "repairs",
        "asset_reference": "CWP-7",
        "purchase_route_guess": "onsite_labor",
        "request_type_guess": "CHANGE ORDER",
        "original_po_number": "4500123456",
    }
    values.update(overrides)
    return json.dumps(values)


def test_analysis_accepts_route_asset_and_change_order_guesses():
    result = normalize_analysis_response(_response())
    assert result["purchase_route_guess"] == "onsite_labor"
    assert result["asset_reference"] == "CWP-7"
    assert result["request_type_guess"] == "CHANGE ORDER"
    assert result["original_po_number"] == "4500123456"
    assert result["short_description"] == "Replace pump and tes"
    assert len(result["short_description"]) == 20


def test_new_po_discards_a_model_hallucinated_original_po_number():
    result = normalize_analysis_response(
        _response(request_type_guess="PO", original_po_number="invented")
    )
    assert result["original_po_number"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purchase_route_guess", "vendor_delivery"),
        ("request_type_guess", "BOTH PO&WO"),
    ],
)
def test_unsupported_guesses_degrade_instead_of_sinking_the_analysis(field, value):
    """These two fields are *guesses* with deterministic fallbacks downstream.

    Previously an unsupported value raised, so a complete and otherwise usable
    extraction was thrown away and the operator saw "The quote could not be
    analyzed" -- for a field the UI was about to re-derive anyway (web_ui calls
    infer_purchase_route when the route is absent, and an absent request type
    means a plain PO). Degrading to None keeps the rest of the extraction while
    still refusing to act on a value the schema does not recognize.
    """
    result = normalize_analysis_response(_response(**{field: value}))

    assert result[field] is None
    # The rest of the extraction survives intact.
    assert result["vendor_name"] == "Vendor"
    assert result["asset_reference"] == "CWP-7"


def test_degraded_request_type_does_not_leak_an_original_po_number():
    """Safety property preserved: only a CONFIRMED change order keeps the PO."""
    result = normalize_analysis_response(
        _response(request_type_guess="BOTH PO&WO", original_po_number="4500123456")
    )

    assert result["request_type_guess"] is None
    assert result["original_po_number"] is None
