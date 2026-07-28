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
    prefill_enabled,
    submission_fingerprint,
)


def test_default_configuration_is_inert():
    config = load_config({})

    assert not manual_enabled(config)
    assert not prefill_enabled(config)
    assert config.api_mode == "disabled"
    assert not api_readiness(config).ready


def test_invalid_configuration_is_rejected():
    with pytest.raises(SmartsheetConfigurationError, match="invalid JSON"):
        load_config({"SMARTSHEET_COLUMN_MAP_JSON": "{"})

    with pytest.raises(SmartsheetConfigurationError, match="disabled, dry_run, or live"):
        load_config({"SMARTSHEET_API_MODE": "automatic"})

    with pytest.raises(SmartsheetConfigurationError, match="numeric"):
        load_config({"SMARTSHEET_COLUMN_MAP_JSON": '{"site": "not-an-id"}'})


def test_prefill_uses_exact_configured_labels_and_preserves_existing_query():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example?source=epc",
            "SMARTSHEET_URL_PREFILL_ENABLED": "true",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": json.dumps(
                {
                    "site": "Service Branch or O&M Site Requesting Workorder",
                    "description": "Description of Work or Issue Needing Repair",
                }
            ),
        }
    )

    result = build_prefilled_form_url(
        {"site": "RRH UMMC", "description": "Pump #7 repair", "unmapped": "skip"},
        config,
    )
    query = parse_qs(urlsplit(result.url).query)

    assert query["source"] == ["epc"]
    assert query["Service Branch or O&M Site Requesting Workorder"] == ["RRH UMMC"]
    assert query["Description of Work or Issue Needing Repair"] == ["Pump #7 repair"]
    assert result.included == ("site", "description")
    assert result.skipped == ("unmapped",)


def test_prefill_can_translate_internal_values_to_form_options():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://app.smartsheet.com/b/form/example",
            "SMARTSHEET_URL_PREFILL_ENABLED": "yes",
            "SMARTSHEET_FORM_FIELD_MAP_JSON": '{"related_to_om": "O&M Agreement?"}',
            "SMARTSHEET_FORM_VALUE_MAP_JSON": json.dumps(
                {"related_to_om": {"true": "Yes", "false": "No"}}
            ),
        }
    )

    result = build_prefilled_form_url({"related_to_om": "TRUE"}, config)
    query = parse_qs(urlsplit(result.url).query)

    assert query["O&M Agreement?"] == ["Yes"]


def test_manual_rows_follow_configured_form_order_and_skip_empty_values():
    config = load_config(
        {
            "SMARTSHEET_FORM_URL": "https://example.invalid/form",
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


def test_api_requires_token_sheet_explicit_columns_and_confirmed_required_fields():
    incomplete = load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_MAP_JSON": '{"site": 456}',
        }
    )
    readiness = api_readiness(incomplete)

    assert not readiness.ready
    assert any("SMARTSHEET_REQUIRED_FIELDS" in problem for problem in readiness.problems)

    complete = load_config(
        {
            "SMARTSHEET_API_MODE": "live",
            "SMARTSHEET_API_TOKEN": "token",
            "SMARTSHEET_SHEET_ID": "123",
            "SMARTSHEET_COLUMN_MAP_JSON": '{"site": 456, "total": 789}',
            "SMARTSHEET_REQUIRED_FIELDS": "site,total",
        }
    )

    assert api_readiness(complete).ready


def test_submission_fingerprint_is_stable_and_attachment_sensitive():
    fields_a = {"site": "UMMC", "total": "$100.00"}
    fields_b = {"total": "$100.00", "site": "UMMC"}

    first = submission_fingerprint(fields_a, [("quote.pdf", b"one")])
    same = submission_fingerprint(fields_b, [("quote.pdf", b"one")])
    changed = submission_fingerprint(fields_b, [("quote.pdf", b"two")])

    assert first == same
    assert first != changed


def test_download_names_keep_files_adjacent_without_changing_data():
    files = [("original quote.pdf", b"quote"), ("scope.docx", b"doc")]

    result = download_names(files, "RRH UMMC Pump MSAPO")

    assert result[0][1] == "RRH UMMC Pump 1 Quote.pdf"
    assert result[1][1] == "RRH UMMC Pump 2 MSAPO.docx"
    assert result[0][2] == b"quote"
    assert result[1][2] == b"doc"
