import json

import pytest

from app.analysis_schema import AnalysisResponseError, normalize_analysis_response


def _valid_payload() -> dict:
    return {
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
        "ai_assumptions": [{"text": "After-hours work", "section": "exclusion"}],
        "contact_name": None,
        "contact_email": None,
        "subtotal_amount": "$100.00",
        "tax_amount": "$8.00",
        "total_amount": "$108.00",
        "short_description": "Pump repair",
        "work_category": "repairs",
        "asset_reference": "P-1",
    }


def test_valid_fenced_response_is_normalized():
    raw = "```json\n" + json.dumps(_valid_payload()) + "\n```"
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
    payload = _valid_payload()
    payload["inclusions"] = ["Labor", {"unexpected": "object"}]

    with pytest.raises(AnalysisResponseError, match="item 2"):
        normalize_analysis_response(json.dumps(payload))


def test_invalid_enum_is_rejected():
    payload = _valid_payload()
    payload["tax_status"] = "maybe"

    with pytest.raises(AnalysisResponseError, match="tax_status"):
        normalize_analysis_response(json.dumps(payload))


def test_extra_text_after_json_is_rejected():
    raw = json.dumps(_valid_payload()) + " This is an explanation."

    with pytest.raises(AnalysisResponseError, match="extra text"):
        normalize_analysis_response(raw)


def test_non_object_json_is_rejected():
    with pytest.raises(AnalysisResponseError, match="JSON object"):
        normalize_analysis_response('["not", "an", "object"]')


def test_short_description_is_bounded():
    payload = _valid_payload()
    payload["short_description"] = "A description that is too long"

    result = normalize_analysis_response(json.dumps(payload))

    assert len(result["short_description"]) == 20
