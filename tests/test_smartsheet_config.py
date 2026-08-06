import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.smartsheet import (
    AGREEMENT_TYPE_OPTIONS,
    DEFAULT_FORM_ORDER,
    DEFAULT_FORM_REQUIRED_FIELDS,
    OBJECT_ACCOUNT_OPTIONS,
    RRH_JOB_NUMBERS,
    SmartsheetConfigurationError,
    api_readiness,
    build_prefilled_form_url,
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    prefill_enabled,
    preflight_attachments,
    submission_fingerprint,
    validate_submission_fields,
)


def _specs() -> str:
    return json.dumps(
        {
            "site_location": {
                "id": 456,
                "title": "SITE NUMBER / LOCATION",
                "type": "TEXT_NUMBER",
            },
            "total": {
                "id": 789,
                "title": "PO/CO AMOUNT",
                "type": "TEXT_NUMBER",
            },
            "submission_key": {
                "id": 999,
                "title": "Email Process Control Submission Key",
                "type": "TEXT_NUMBER",
            },
        }
    )


def test_default_configuration_is_inert():
    config = load_config({})
    assert not manual_enabled(config)
    assert not prefill_enabled(config)
    assert config.api_mode == "disabled"
    assert not api_readiness(config).ready


def test_live_form_schema_and_rrh_choices_are_exact():
    assert DEFAULT_FORM_ORDER == (
        "request_type",
        "requester_name",
        "job_number",
        "site_location",
        "cost_code",
        "object_account",
        "agreement_type",
        "original_po_number",
        "total",
        "vendor",
        "contact_name",
        "contact_email",
        "description_of_work",
        "asset_id",
        "dispatch_service_center",
        "instructions",
    )
    assert DEFAULT_FORM_REQUIRED_FIELDS == (
        "request_type",
        "requester_name",
        "job_number",
        "site_location",
        "cost_code",
        "object_account",
        "agreement_type",
        "total",
        "description_of_work",
        "dispatch_service_center",
    )
    assert RRH_JOB_NUMBERS == (
        "RRH-695400022-O&M",
        "RRH-695400023-START UP",
        "RRH-695400030-ISDC",
        "RRH-695400034-ES JOB CCJ",
    )
    assert "5511-SUBCONTRACTOR" in OBJECT_ACCOUNT_OPTIONS
    assert "5302-EQUIPMENT" in OBJECT_ACCOUNT_OPTIONS
    assert "03 - MSAPO (SERVICE)" in AGREEMENT_TYPE_OPTIONS
    assert "OR - EQUIPMENT PO" in AGREEMENT_TYPE_OPTIONS


def test_invalid_or_unsafe_configuration_is_rejected():
    with pytest.raises(SmartsheetConfigurationError, match="invalid JSON"):
        load_config({"SMARTSHEET_COLUMN_SPECS_JSON": "{"})
    with pytest.raises(SmartsheetConfigurationError, match="disabled, dry_run, or live"):
        load_config({"SMARTSHEET_API_MODE": "automatic"})
    with pytest.raises(SmartsheetConfigurationError, match="unknown logical field"):
        load_config({"SMARTSHEET_FORM_FIELD_MAP_JSON": '{"typo_field":"Site"}'})
    with pytest.raises(SmartsheetConfigurationError, match="same Smartsheet column ID"):
        load_config(
            {
                "SMARTSHEET_COLUMN_SPECS_JSON": json.dumps(
                    {
                        "site_location": {
                            "id": 1,
                            "title": "SITE NUMBER / LOCATION",
                            "type": "TEXT_NUMBER",
                        },
                        "total": {"id": 1, "title": "Amount", "type": "TEXT_NUMBER"},
                    }
                )
            }
        )
    with pytest.raises(SmartsheetConfigurationError, match="Smartsheet domain"):
        load_config({"SMARTSHEET_FORM_URL": "https://example.invalid/form"})
    with pytest.raises(SmartsheetConfigurationError, match="api.smartsheet.com"):
        load_config(
            {
                "SMARTSHEET_API_MODE": "live",
                "SMARTSHEET_API_BASE_URL": "https://attacker.invalid/2.0",
            }
        )


def test_prefill_replaces_existing_field_value_and_preserves_unrelated_query():
    label = "SITE NUMBER / LOCATION"
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": (
                "https://app.smartsheet.com/b/form/example?source=epc&"
                "SITE+NUMBER+%2F+LOCATION=OLD"
            ),
            "SMARTSHEET_URL_PREFILL_ENABLED": "true",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(
                {
                    "site_location": label,
                    "description_of_work": "DESCRIPTION OF WORK",
                }
            ),
        }
    )
    result = build_prefilled_form_url(
        {
            "site_location": "UMMC",
            "description_of_work": "Pump #7 repair",
            "instructions": "skip",
        },
        config,
    )
    raw_query = urlsplit(result.url).query
    query = parse_qs(raw_query)

    # Smartsheet's live form requires documented percent escapes for spaces.
    # parse_qs normalizes both "+" and "%20", so raw-wire assertions are
    # necessary to catch an encoder that is semantically valid but rejected by
    # the receiving form.
    assert "+" not in raw_query
    assert "SITE%20NUMBER%20%2F%20LOCATION=UMMC" in raw_query
    assert "DESCRIPTION%20OF%20WORK=Pump%20%237%20repair" in raw_query
    assert query["source"] == ["epc"]
    assert query[label] == ["UMMC"]
    assert query["DESCRIPTION OF WORK"] == ["Pump #7 repair"]
    assert result.included == ("site_location", "description_of_work")
    assert any(item.startswith("instructions:") for item in result.skipped)


def test_prefill_value_translation_required_fields_and_length_limit():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_URL_PREFILL_ENABLED": "yes",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(
                {
                    "request_type": "REQUEST TYPE",
                    "description_of_work": "DESCRIPTION OF WORK",
                }
            ),
            "SMARTSHEET_FORM_VALUE_MAP_JSON": json.dumps(
                {"request_type": {"PO": "Purchase Order"}}
            ),
            "SMARTSHEET_FORM_REQUIRED_FIELDS": "site_location,request_type",
            "SMARTSHEET_PREFILL_MAX_URL_LENGTH": "1000",
        }
    )
    result = build_prefilled_form_url(
        {"request_type": "PO", "description_of_work": "x" * 1500}, config
    )
    query = parse_qs(urlsplit(result.url).query)

    assert query["REQUEST TYPE"] == ["Purchase Order"]
    assert result.missing_required == ("site_location",)
    assert any("URL length limit" in item for item in result.skipped)


def test_custom_url_prefills_every_populated_live_po_field_under_exact_labels():
    field_map = {
        "request_type": "REQUEST TYPE",
        "requester_name": "REQUESTER",
        "job_number": "JOB NUMBER",
        "site_location": "SITE NUMBER / LOCATION",
        "cost_code": "COST CODE",
        "object_account": "OBJECT ACCOUNT",
        "agreement_type": "AGREEMENT TYPE FOR PO",
        "original_po_number": "ORIGIONAL PO NUMBER",
        "total": "PO/CO AMOUNT",
        "vendor": "VENDOR NAME",
        "contact_name": "VENDOR CONTACT NAME",
        "contact_email": "VENDOR CONTACT EMAIL",
        "description_of_work": "DESCRIPTION OF WORK",
        "asset_id": "ASSET ID",
        "dispatch_service_center": "DISPATCH WO TO SERVICE CENTER?",
        "instructions": "ADDITIONAL INFORMATION IF NEEDED",
    }
    fields = {
        "request_type": "PO",
        "requester_name": "Test Requester",
        "job_number": "RRH-695400022-O&M",
        "site_location": "123 - Test Hospital",
        "cost_code": "01CEABA",
        "object_account": "5511-SUBCONTRACTOR",
        "agreement_type": "03 - MSAPO (SERVICE)",
        "original_po_number": "",
        "total": "$1,234.56",
        "vendor": "Example & Sons",
        "contact_name": "Pat O'Brien",
        "contact_email": "pat@example.invalid",
        "description_of_work": "Repair pump #7 & verify operation.",
        "asset_id": "RRH-0007",
        "dispatch_service_center": "NA",
        "instructions": "Synthetic test only; do not submit.",
    }
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_URL_PREFILL_ENABLED": "true",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(field_map),
        }
    )

    result = build_prefilled_form_url(fields, config)
    raw_query = urlsplit(result.url).query
    query = parse_qs(raw_query)

    assert "+" not in raw_query
    assert "REQUEST%20TYPE=PO" in raw_query
    assert "JOB%20NUMBER=RRH-695400022-O%26M" in raw_query
    assert (
        "SITE%20NUMBER%20%2F%20LOCATION=123%20-%20Test%20Hospital"
        in raw_query
    )
    assert "VENDOR%20NAME=Example%20%26%20Sons" in raw_query
    assert (
        "DESCRIPTION%20OF%20WORK="
        "Repair%20pump%20%237%20%26%20verify%20operation."
        in raw_query
    )
    assert "DISPATCH%20WO%20TO%20SERVICE%20CENTER%3F=NA" in raw_query
    assert result.missing_required == ()
    assert result.skipped == ()
    assert result.included == tuple(
        field for field in DEFAULT_FORM_ORDER if fields.get(field)
    )
    assert query == {
        label: [str(fields[field]).strip()]
        for field, label in field_map.items()
        if fields.get(field)
    }
    assert "attachments" not in result.url.lower()

def test_manual_rows_follow_configured_order_and_skip_empty_values():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_FORM_ORDER": "vendor,site_location,total",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": '{"vendor": "Supplier"}',
        }
    )
    rows = handoff_rows(
        {
            "site_location": "UMMC",
            "vendor": "Vendor Co",
            "total": "",
            "cost_code": "01CEABA",
        },
        config,
    )
    assert rows == [
        ("vendor", "Supplier", "Vendor Co"),
        ("site_location", "SITE NUMBER / LOCATION", "UMMC"),
        ("cost_code", "COST CODE", "01CEABA"),
    ]


def test_live_api_requires_exact_specs_submission_key_and_required_fields():
    legacy_only = load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_MAP_JSON": (
                '{"site_location": 456, "submission_key": 999}'
            ),
            "SMARTSHEET_REQUIRED_FIELDS": "site_location",
        }
    )
    assert not api_readiness(legacy_only).ready
    assert any("exact title and type" in item for item in api_readiness(legacy_only).problems)

    complete = load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_SPECS_JSON": _specs(),
            "SMARTSHEET_REQUIRED_FIELDS": "site_location,total",
        }
    )
    assert api_readiness(complete).ready


def test_field_and_attachment_preflight_rejects_silent_corruption():
    problems = validate_submission_fields(
        {
            "contact_email": "not-an-email",
            "total": "$1,234.56",
            "description_of_work": "x" * 4001,
            "request_type": "WO",
            "dispatch_service_center": "DALLAS",
        }
    )
    assert any("valid email" in item for item in problems)
    assert any("4,000-character" in item for item in problems)
    assert any("REQUEST TYPE" in item and "PO" in item for item in problems)
    assert any("DISPATCH WO" in item and "NA" in item for item in problems)

    attachment_problems = preflight_attachments(
        [
            ("quote.pdf", b"first"),
            ("quote.pdf", b"second"),
            ("empty.pdf", b""),
        ]
    )
    assert any("empty" in item for item in attachment_problems)
    assert any("duplicated" in item for item in attachment_problems)


def test_submission_fingerprint_is_stable_and_attachment_sensitive():
    fields_a = {"site_location": "UMMC", "total": "$100.00"}
    fields_b = {"total": "$100.00", "site_location": "UMMC"}
    first = submission_fingerprint(fields_a, [("quote.pdf", b"one")])
    same = submission_fingerprint(fields_b, [("quote.pdf", b"one")])
    changed = submission_fingerprint(fields_b, [("quote.pdf", b"two")])
    assert first == same
    assert first != changed


def test_download_names_sanitize_untrusted_names_without_changing_data():
    files = [("../original\nquote.pdf", b"quote"), ("scope.docx", b"doc")]
    result = download_names(files, "RRH UMMC Pump MSAPO")
    assert result[0][1] == "RRH UMMC Pump 1 Quote.pdf"
    assert result[1][1] == "RRH UMMC Pump 2 MSAPO.docx"
    assert result[0][2] == b"quote"
    assert result[1][2] == b"doc"
