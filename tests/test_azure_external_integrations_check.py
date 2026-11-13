"""Synthetic offline migration preflight; no real provider or network access."""
import json
from pathlib import Path
from scripts.azure_external_integrations_check import audit, load_settings, main


def _base():
    return {
        'SMARTSHEET_API_MODE': 'disabled',
        'SMARTSHEET_FORM_URL': 'https://app.smartsheet.com/b/form/00000000000000000000000000000000',
        'SMARTSHEET_URL_PREFILL_ENABLED': 'true',
        'SMARTSHEET_FORM_FIELD_MAP_JSON': '{"vendor":"VENDOR NAME"}',
        'SMARTSHEET_ALLOW_CUSTOM_API_BASE': 'false',
        'EXPENSE_ACCOUNT_DIRECTORS_JSON': '{"Synthetic Account":{"name":"Test Director","email":"director@example.invalid"}}',
        'PDF_BACKEND': 'libreoffice',
    }


def _fail(settings, *, scope='staging'):
    return {item.name for item in audit(settings, scope=scope) if item.level == 'FAIL'}


def test_disabled_and_dry_run_do_not_raise_a_mode_failure():
    settings = _base()
    assert 'SMARTSHEET_API_MODE' not in _fail(settings)
    settings['SMARTSHEET_API_MODE'] = 'dry_run'
    assert 'SMARTSHEET_API_MODE' not in _fail(settings)


def test_live_mode_fails_closed_even_with_a_token_and_fake_sheet():
    settings = _base()
    settings.update(SMARTSHEET_API_MODE='live', SMARTSHEET_API_TOKEN='synthetic-token', SMARTSHEET_SHEET_ID='1234567890123456')
    assert 'SMARTSHEET_API_MODE' in _fail(settings)


def test_custom_api_base_is_limited_to_isolated_nonprod_fake():
    settings = _base()
    settings.update(SMARTSHEET_API_MODE='dry_run', SMARTSHEET_ALLOW_CUSTOM_API_BASE='true', SMARTSHEET_API_BASE_URL='https://fake.example.invalid/2.0')
    assert 'SMARTSHEET_API_BASE_URL' not in _fail(settings)
    assert 'SMARTSHEET_ALLOW_CUSTOM_API_BASE' in _fail(settings, scope='production')
    settings['SMARTSHEET_API_MODE'] = 'live'
    assert 'SMARTSHEET_API_BASE_URL' in _fail(settings)


def test_form_redirect_and_missing_mapping_fail_without_exposing_values():
    settings = _base()
    settings['SMARTSHEET_FORM_URL'] = 'https://app.smartsheet.com.evil.invalid/form'
    assert 'SMARTSHEET_FORM_URL' in _fail(settings)
    settings['SMARTSHEET_FORM_URL'] = _base()['SMARTSHEET_FORM_URL']
    settings['SMARTSHEET_FORM_FIELD_MAP_JSON'] = '{}'
    assert 'SMARTSHEET_URL_PREFILL_ENABLED' in _fail(settings)


def test_invalid_director_map_and_network_pdf_are_rejected():
    settings = _base()
    settings['EXPENSE_ACCOUNT_DIRECTORS_JSON'] = '{"Account":{"name":"A","email":"not-an-email"}}'
    settings['PDF_BACKEND'] = 'gotenberg'
    assert {'EXPENSE_ACCOUNT_DIRECTORS_JSON', 'PDF_BACKEND'} <= _fail(settings)


def test_no_server_mail_and_no_secret_values_in_output(tmp_path, capsys):
    settings = _base()
    settings.update(SMARTSHEET_API_MODE='live', SMARTSHEET_API_TOKEN='TOP_SECRET_ABC', SMTP_HOST='private.mail.invalid')
    path = tmp_path / 'synthetic.json'
    path.write_text(json.dumps(settings), encoding='utf-8')
    assert main([str(path), '--scope', 'production']) == 1
    output = capsys.readouterr().out
    assert 'TOP_SECRET_ABC' not in output
    assert 'private.mail.invalid' not in output
    assert 'SMTP_HOST' in output


def test_read_azure_appsettings_list_and_refuse_duplicate_names(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps([{'name': 'SMARTSHEET_API_MODE', 'value': 'disabled'}]), encoding='utf-8')
    assert load_settings(path) == {'SMARTSHEET_API_MODE': 'disabled'}
    path.write_text(json.dumps([{'name': 'X', 'value': 'a'}, {'name': 'X', 'value': 'b'}]), encoding='utf-8')
    try:
        load_settings(path)
        assert False, 'duplicate names should fail'
    except ValueError:
        pass


def test_production_missing_browser_form_is_blocked():
    assert 'SMARTSHEET_FORM_URL' in _fail({'SMARTSHEET_API_MODE':'disabled'}, scope='production')
