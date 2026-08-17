import json

import pytest

from app import quote_analyzer
from app.analysis_schema import AnalysisResponseError, normalize_analysis_response


def _payload(**overrides) -> dict:
    values = {
        "vendor_name": "Vendor",
        "project_description": "Pump repair",
        "facility_name": None,
        "facility_address": None,
        "scope_of_work": "Repair the pump.",
        "inclusions": ["Labor"],
        "exclusions": ["Painting"],
        "tax_status": "included",
        "tax_warning": None,
        "tax_note": None,
        "ai_assumptions": [
            {"text": "After-hours work", "section": "exclusion"}
        ],
        "contact_name": None,
        "contact_email": None,
        "subtotal_amount": "$100.00",
        "tax_amount": "$8.00",
        "total_amount": "$108.00",
        "short_description": "Pump repair",
        "work_category": "repairs",
        "asset_reference": "P-1",
        "purchase_route_guess": "onsite_labor",
        "request_type_guess": "PO",
    }
    values.update(overrides)
    return values


def test_valid_fenced_response_is_normalized():
    raw = "```json\n" + json.dumps(_payload()) + "\n```"
    result = normalize_analysis_response(raw)

    assert result["vendor_name"] == "Vendor"
    assert result["tax_status"] == "included"
    assert result["ai_assumptions"] == [
        {"text": "After-hours work", "section": "exclusion"}
    ]


def test_missing_optional_fields_receive_safe_defaults():
    result = normalize_analysis_response(
        json.dumps(
            {
                "vendor_name": "Vendor",
                "project_description": "",
                "scope_of_work": "",
                "tax_status": "unclear",
            }
        )
    )

    assert result["inclusions"] == []
    assert result["exclusions"] == []
    assert result["contact_email"] is None
    assert result["ai_assumptions"] == []


def test_invalid_list_item_is_rejected():
    payload = _payload()
    payload["inclusions"] = ["Labor", {"unexpected": "object"}]

    with pytest.raises(AnalysisResponseError, match="item 2"):
        normalize_analysis_response(json.dumps(payload))


def test_unsupported_tax_value_degrades_to_unclear():
    result = normalize_analysis_response(json.dumps(_payload(tax_status="maybe")))

    assert result["tax_status"] == "unclear"


def test_non_object_json_is_rejected():
    with pytest.raises(AnalysisResponseError, match="JSON object"):
        normalize_analysis_response('["not", "an", "object"]')


def test_short_description_is_bounded():
    result = normalize_analysis_response(
        json.dumps(_payload(short_description="A description that is too long"))
    )

    assert len(result["short_description"]) == 20


@pytest.mark.parametrize("tax_value", ["Included", " included "])
def test_tax_status_is_normalized(tax_value):
    result = normalize_analysis_response(json.dumps(_payload(tax_status=tax_value)))

    assert result["tax_status"] == "included"


@pytest.mark.parametrize(
    ("category", "expected"),
    [("hvac", None), ("Repairs", "repairs")],
)
def test_work_category_is_a_normalized_soft_hint(category, expected):
    result = normalize_analysis_response(
        json.dumps(_payload(work_category=category))
    )

    assert result["work_category"] == expected


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("exclusions", "exclusion"),
        ("nonsense", "exclusion"),
        # An unrecognized value must not be coerced to the OPPOSITE meaning.
        # These strings are rendered verbatim as bullets on the PO scope PDF, so
        # mapping "included"/"inclusions" onto "exclusion" told the vendor they
        # were excluding work the model meant to include.
        ("included", "inclusion"),
        ("inclusions", "inclusion"),
        ("Inclusion ", "inclusion"),
        ("including", "inclusion"),
        ("excluded", "exclusion"),
        ("Scope", "scope"),
        ("scopes", "scope"),
        (None, "exclusion"),
        (123, "exclusion"),
    ],
)
def test_assumption_section_uses_a_conservative_fallback(section, expected):
    result = normalize_analysis_response(
        json.dumps(
            _payload(
                ai_assumptions=[
                    {"text": "Unquoted restoration", "section": section}
                ]
            )
        )
    )

    assert result["ai_assumptions"][0]["section"] == expected


def test_valid_json_with_trailing_remark_is_accepted():
    raw = json.dumps(_payload()) + "\nNote: done."

    assert normalize_analysis_response(raw)["vendor_name"] == "Vendor"


def test_fenced_json_with_trailing_remark_is_accepted():
    raw = "```json\n" + json.dumps(_payload()) + "\n```\nAnalysis complete."

    assert normalize_analysis_response(raw)["vendor_name"] == "Vendor"


def test_genuinely_broken_json_still_raises():
    with pytest.raises(AnalysisResponseError):
        normalize_analysis_response("{not json")


def test_analyzer_rerolls_one_malformed_response(monkeypatch):
    responses = iter(("{not json", json.dumps(_payload())))
    calls = []
    monkeypatch.setattr(
        quote_analyzer.anthropic,
        "Anthropic",
        lambda **_kwargs: object(),
    )

    def fake_call(_client, _quote_text):
        calls.append(True)
        return next(responses)

    monkeypatch.setattr(quote_analyzer, "_call_api_with_retry", fake_call)

    result = quote_analyzer.analyze_quote("quote")

    assert result.vendor_name == "Vendor"
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("onsite_labor", "onsite_labor"),
        ("onsite labor", "onsite_labor"),
        ("Onsite-Labor", "onsite_labor"),
        ("teleportation", None),
        ("", None),
    ],
)
def test_purchase_route_guess_degrades_instead_of_failing(raw, expected):
    """A guess with a deterministic UI fallback must never sink the analysis.

    web_ui re-derives the route via infer_purchase_route when it is absent, so
    raising here discarded a complete extraction and showed the operator "The
    quote could not be analyzed" over a space-versus-underscore deviation.
    """
    result = normalize_analysis_response(json.dumps(_payload(purchase_route_guess=raw)))

    assert result["purchase_route_guess"] == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PO", "PO"),
        ("po", "PO"),
        ("  change   order ", "CHANGE ORDER"),
        ("something else", None),
    ],
)
def test_request_type_guess_degrades_instead_of_failing(raw, expected):
    result = normalize_analysis_response(json.dumps(_payload(request_type_guess=raw)))

    assert result["request_type_guess"] == expected


def test_unrecognized_request_type_still_clears_the_original_po_number():
    """Degrading must not weaken the change-order safety property.

    original_po_number may only survive for a CONFIRMED change order; an
    unrecognized guess is treated as "not a change order", which is the
    conservative direction.
    """
    result = normalize_analysis_response(
        json.dumps(
            _payload(request_type_guess="gibberish", original_po_number="PO-12345")
        )
    )

    assert result["request_type_guess"] is None
    assert result["original_po_number"] is None


# --- The schema's enums must not drift from their sources of truth ----------


def test_allowed_work_categories_match_the_config_source_of_truth():
    """analysis_schema keeps its own copy of two enums that live elsewhere, and
    a copy that drifts fails SILENTLY in the damaging direction: an unrecognised
    value degrades to None rather than raising, so adding a work category to
    app/config.py alone would make the model's correct answer for it get
    discarded, with the operator simply seeing an unset dropdown.

    This is the same shape as the transparency-flatten duplication, which had
    already drifted and was turning receipts black. Pin the copies together.
    """
    from app.analysis_schema import _ALLOWED_WORK_CATEGORIES
    from app.config import WORK_CATEGORY_DISPLAY, WORK_CATEGORY_SUFFIXES

    assert _ALLOWED_WORK_CATEGORIES == set(WORK_CATEGORY_SUFFIXES)
    # The display map is what the UI labels them with; a missing entry renders a
    # blank option rather than raising.
    assert set(WORK_CATEGORY_SUFFIXES) == set(WORK_CATEGORY_DISPLAY)


def test_allowed_purchase_routes_match_po_rules():
    """po_rules.PURCHASE_ROUTES is authoritative -- classify_po raises on
    anything outside it. A route the schema accepts but po_rules does not would
    reach classification and fail there instead of at the boundary."""
    from app.analysis_schema import _ALLOWED_PURCHASE_ROUTES
    from app.po_rules import PURCHASE_ROUTES

    assert _ALLOWED_PURCHASE_ROUTES == set(PURCHASE_ROUTES)
