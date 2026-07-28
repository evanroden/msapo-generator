import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.smartsheet import (
    SmartsheetConfigurationError,
    api_readiness,
    build_prefilled_form_url,
    download_names,
    handoff_rows,
    load_config,
    manual_enabled,
    preflight_attachments,
    prefill_enabled,
    submission_fingerprint,
    validate_submission_fields,
)


def _specs() -> str:
    return json.dumps(
        {
            "site": {"id": 456, "title": "Site", "type": "TEXT_NUMBER"},
            "total": {"id": 789, "title": "Amount", "type": "TEXT_NUMBER"},
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
                        "site": {"id": 1, "title": "Site", "type": "TEXT_NUMBER"},
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
    label = "Service Branch or O&M Site Requesting Workorder"
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": (
                "https://app.smartsheet.com/b/form/example?source=epc&"
                "Service+Branch+or+O%26M+Site+Requesting+Workorder=OLD"
            ),
            "SMARTSHEET_URL_PREFILL_ENABLED": "true",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(
                {
                    "site": label,
                    "description": "Description of Work or Issue Needing Repair",
                }
            ),
        }
    )
    result = build_prefilled_form_url(
        {"site": "RRH UMMC", "description": "Pump #7 repair", "instructions": "skip"},
        config,
    )
    query = parse_qs(urlsplit(result.url).query)

    assert query["source"] == ["epc"]
    assert query[label] == ["RRH UMMC"]
    assert query["Description of Work or Issue Needing Repair"] == ["Pump #7 repair"]
    assert result.included == ("site", "description")
    assert any(item.startswith("instructions:") for item in result.skipped)


def test_prefill_value_translation_required_fields_and_length_limit():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_URL_PREFILL_ENABLED": "yes",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(
                {
                    "related_to_om": "O&M Agreement?",
                    "scope_of_work": "Description",
                }
            ),
            "SMARTSHEET_FORM_VALUE_MAP_JSON": json.dumps(
                {"related_to_om": {"true": "Yes", "false": "No"}}
            ),
            "SMARTSHEET_FORM_REQUIRED_FIELDS": "site,related_to_om",
            "SMARTSHEET_PREFILL_MAX_URL_LENGTH": "1000",
        }
    )
    result = build_prefilled_form_url(
        {"related_to_om": "TRUE", "scope_of_work": "x" * 1500}, config
    )
    query = parse_qs(urlsplit(result.url).query)

    assert query["O&M Agreement?"] == ["Yes"]
    assert result.missing_required == ("site",)
    assert any("URL length limit" in item for item in result.skipped)


def test_manual_rows_follow_configured_order_and_skip_empty_values():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_FORM_ORDER": "vendor,site,total",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": '{"vendor": "Supplier"}',
        }
    )
    rows = handoff_rows(
        {"site": "UMMC", "vendor": "Vendor Co", "total": "", "cost_code": "01CEABA"},
        config,
    )
    assert rows == [
        ("vendor", "Supplier", "Vendor Co"),
        ("site", "Site Location", "UMMC"),
        ("cost_code", "Job Cost Code", "01CEABA"),
    ]


def test_live_api_requires_exact_specs_submission_key_and_required_fields():
    legacy_only = load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_MAP_JSON": '{"site": 456, "submission_key": 999}',
            "SMARTSHEET_REQUIRED_FIELDS": "site",
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
            "SMARTSHEET_REQUIRED_FIELDS": "site,total",
        }
    )
    assert api_readiness(complete).ready


def test_field_and_attachment_preflight_rejects_silent_corruption():
    problems = validate_submission_fields(
        {
            "contact_email": "not-an-email",
            "estimated_start_date": "July 4th",
            "total": "$1,234.56",
            "scope_of_work": "x" * 4001,
        }
    )
    assert any("valid email" in item for item in problems)
    assert any("MM/DD/YYYY" in item for item in problems)
    assert any("4,000-character" in item for item in problems)

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
    fields_a = {"site": "UMMC", "total": "$100.00"}
    fields_b = {"total": "$100.00", "site": "UMMC"}
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
