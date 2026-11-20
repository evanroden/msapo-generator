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

@pytest.mark.parametrize(
    "line",
    [
        "Sales tax $8.00", "Tax: 8%", "Freight: $12.00",
        "Shipping charge $6.00", "Handling fee $2.00",
        "Fuel surcharge $3.00", "Subtotal: $120.00",
        "Total $135.00", "Grand total: $135.00",
        "Deposit required: $30.00", "Payment terms: net 30",
        "Delivery charge: $5.00", "Processing fees", "2. Sales tax $8.00",
    ],
)
def test_model_cost_only_items_never_become_scope_lines(line):
    from app.quote_analyzer import _clean_scope_item

    assert _clean_scope_item(line) == ""


def test_model_scope_cost_lines_are_removed_without_losing_work_or_totals(monkeypatch):
    import re
    import app.quote_analyzer as quote_analyzer

    class Client:
        def close(self):
            pass

    response = _response(
        scope_of_work=(
            "Remove failed pump and install replacement for $120.00.\n"
            "Sales tax: $8.00\n"
            "Shipping charge: $4.00\n"
            "Test and commission the replacement.\n"
            "Grand total $132.00"
        ),
        inclusions=[
            "Sales tax $8.00", "Freight charge $4.00",
            "Deliver and install the pump", "Replace gasket $120.00",
            "Shipping and installation of replacement pump",
        ],
        exclusions=[
            "Handling fee", "Payment terms: net 30", "Work on other equipment",
        ],
        ai_assumptions=[
            {"text": "Processing fee $4.00", "section": "inclusion"},
            {"text": "Test equipment", "section": "inclusion"},
            {"text": "Subtotal $120.00", "section": "exclusion"},
        ],
        subtotal_amount="$120.00",
        tax_amount="$8.00",
        total_amount="$132.00",
    )
    monkeypatch.setattr(quote_analyzer, "make_client", lambda *a, **kw: Client())
    monkeypatch.setattr(
        quote_analyzer, "_call_api_with_retry", lambda *a, **kw: response
    )
    result = quote_analyzer.analyze_quote("Synthetic pump quote")

    assert result.inclusions == [
        "Deliver and install the pump",
        "Replace gasket",
        "Shipping and installation of replacement pump",
    ]
    assert result.exclusions == ["Work on other equipment"]
    assert [a.text for a in result.ai_assumptions] == ["Test equipment"]
    assert result.scope_of_work.splitlines() == [
        "Remove failed pump and install replacement.",
        "Test and commission the replacement.",
    ]
    scope_lines = [
        *result.scope_of_work.splitlines(), *result.inclusions, *result.exclusions,
        *(a.text for a in result.ai_assumptions),
    ]
    assert all(not re.search(r"\$\s*\d", line) for line in scope_lines)
    assert all(
        not re.match(r"^\s*(?:sales tax|tax|subtotal|grand total|total)\b", line, re.I)
        for line in scope_lines
    )
    assert (result.subtotal_amount, result.tax_amount, result.total_amount) == (
        "$120.00", "$8.00", "$132.00"
    )
