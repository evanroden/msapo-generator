"""Synthetic App Service exports. They contain no real identities or secrets."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import appservice_config_check as check

SECRET = 'synthetic-secret-DO-NOT-LEAK'
TENANT = '00000000-0000-0000-0000-000000000000'


def candidate():
    site = {'type': 'Microsoft.Web/sites', 'kind': 'app,linux,container', 'properties': {
        'httpsOnly': True, 'publicNetworkAccess': 'Disabled'}}
    cfg = {'properties': {
        'alwaysOn': True, 'healthCheckPath': '/_stcore/health',
        'linuxFxVersion': 'DOCKER|example.azurecr.io/msapo-generator@sha256:' + 'f' * 64,
        'acrUseManagedIdentityCreds': True, 'acrUserManagedIdentityID': 'synthetic-client-id',
        'ftpsState': 'Disabled', 'minTlsVersion': '1.2', 'scmIpSecurityRestrictionsUseMain': True}}
    settings = {'WEBSITES_PORT': '8501', 'WEBSITES_ENABLE_APP_SERVICE_STORAGE': 'false',
                'EPC_DATA_DIR': '/mounts/msapo', 'PDF_BACKEND': 'libreoffice',
                'ANTHROPIC_MODEL': 'synthetic-model',
                'SMARTSHEET_FORM_FIELD_MAP_JSON': '{}'}
    settings.update(check.FIXED)
    for name in check.REQUIRED_SECRETS:
        settings[name] = f'@Microsoft.KeyVault(SecretUri=https://fake.vault.azure.net/secrets/{name.lower()})'
    auth = {'properties': {
        'platform': {'enabled': True},
        'globalValidation': {'requireAuthentication': True, 'unauthenticatedClientAction': 'RedirectToLoginPage',
                             'excludedPaths': []},
        'identityProviders': {'azureActiveDirectory': {'registration': {
            'clientId': TENANT, 'openIdIssuer': f'https://login.microsoftonline.com/{TENANT}/v2.0'},
            'validation': {'defaultAuthorizationPolicy': {'allowedPrincipals': {'groups': [TENANT]}}}}},
        'httpSettings': {'requireHttps': True}}}
    storage = {'msapo': {'type': 'AzureFiles', 'shareName': 'synthetic', 'mountPath': '/mounts/msapo'}}
    plan = {'kind': 'linux', 'sku': {'tier': 'PremiumV3', 'capacity': 1}, 'properties': {'reserved': True}}
    return [site, cfg, settings, auth, storage, plan]


def test_candidate_passes_but_warns_storage_qualification(capsys):
    rc = check.run(*candidate())
    out = capsys.readouterr().out
    assert rc == 0, out
    assert 'mount existence cannot prove POSIX locks' in out
    assert 'classic DOCKER|' in out


@pytest.mark.parametrize('index,key,value', [
    (0, 'properties', {'httpsOnly': False, 'publicNetworkAccess': 'Enabled'}),
    (1, 'properties', {'linuxFxVersion': 'sitecontainers'}),
    (2, 'WEBSITES_PORT', '80'),
    (2, 'EPC_DATA_DIR', '/test1'),
    (2, 'ANTHROPIC_API_KEY', SECRET),
    (2, 'EPC_SQLITE_JOURNAL_MODE', 'wal'),
    (2, 'APP_GIT_COMMIT', SECRET),
    (3, 'properties', {'platform': {'enabled': False}}),
    (4, 'msapo', {'type': 'AzureBlob', 'mountPath': '/mounts/msapo'}),
    (5, 'sku', {'tier': 'PremiumV3', 'capacity': 2}),
])
def test_misconfigurations_fail_without_secret_disclosure(capsys, index, key, value):
    args = candidate()
    args[index][key] = value
    code = check.run(*args)
    out = capsys.readouterr().out
    assert code == 1, out
    assert SECRET not in out


def test_rejects_container_apps_export(tmp_path, capsys):
    args = candidate()
    args[0] = {'type': 'Microsoft.App/containerApps', 'properties': {'template': {}}}
    paths = []
    for i, value in enumerate(args):
        p = tmp_path / f'{i}.json'
        p.write_text(json.dumps(value))
        paths.append(str(p))
    argv = [paths[0], '--config', paths[1], '--settings', paths[2], '--auth', paths[3],
            '--storage', paths[4], '--plan', paths[5]]
    assert check.main(argv) == 2
    assert 'not Microsoft.Web/sites' in capsys.readouterr().err


def test_invalid_json_is_exit_2(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('not json')
    assert check.main([str(p), *sum(([f'--{arg}', str(p)] for arg in ('config', 'settings', 'auth', 'storage', 'plan')), [])]) == 2
