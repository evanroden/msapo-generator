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
def test_analysis_rejects_unsupported_guesses(field, value):
    with pytest.raises(AnalysisResponseError):
        normalize_analysis_response(_response(**{field: value}))
