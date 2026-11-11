"""Read-only App Service classic Linux container configuration audit.

Usage:
  python scripts/appservice_config_check.py site.json --config config.json \
    --settings settings.json --auth auth.json --storage storage.json --plan plan.json

Exports: az resource show --ids <site-id>; az webapp config show;
  az webapp config appsettings list; az webapp auth show;
  az webapp config storage-account list; az appservice plan show.
Never export/commit appsettings, auth or storage JSON to a public repository.
For Container Apps use scripts/azure_config_check.py --platform containerapps.
This is a structural check, not a storage, identity or runtime acceptance test.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

PORT = '8501'
HEALTH = '/_stcore/health'
FIXED = {
    'PDF_BACKEND': 'libreoffice',
    'SMARTSHEET_URL_PREFILL_ENABLED': 'true',
    'SMARTSHEET_API_MODE': 'disabled',
    'SMARTSHEET_ALLOW_CUSTOM_API_BASE': 'false',
    'SMARTSHEET_PREFILL_MAX_URL_LENGTH': '7000',
}
REQUIRED_SECRETS = ('ANTHROPIC_API_KEY', 'EXPENSE_ACCOUNT_DIRECTORS_JSON', 'SMARTSHEET_FORM_URL')
OPTIONAL_SECRETS = ('SMARTSHEET_API_TOKEN', 'SMARTSHEET_SHEET_ID')
FORBIDDEN_CA = ('configuration', 'template', 'latestRevisionName', 'latestReadyRevisionName')


def read_json(path: str):
    try:
        data = json.loads(sys.stdin.read() if path == '-' else Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError(f'cannot read JSON {path}: {type(exc).__name__}') from None
    if not isinstance(data, (dict, list)):
        raise ValueError(f'{path}: expected JSON object or array')
    return data


def props(data):
    return data.get('properties', data) if isinstance(data, dict) else data


class Audit:
    def __init__(self):
        self.fails = 0
        self.warns = 0

    def check(self, condition, message, *, warning=False):
        label = 'PASS' if condition else ('WARN' if warning else 'FAIL')
        self.fails += int(not condition and not warning)
        self.warns += int(not condition and warning)
        print(f'{label:<5} {message}')


def _names(items):
    if isinstance(items, list):
        return {x.get('name'): x.get('value') for x in items if isinstance(x, dict) and isinstance(x.get('name'), str)}
    if isinstance(items, dict):
        return items
    raise ValueError('app settings must be a list or object')


def _kv(value):
    return isinstance(value, str) and value.startswith('@Microsoft.KeyVault(') and value.endswith(')')


def run(site, config, settings, auth, storage, plan):
    audit = Audit()
    site_properties = props(site)
    config = props(config)
    auth = props(auth)
    plan_properties = props(plan)
    if not isinstance(site, dict) or not isinstance(config, dict) or not isinstance(auth, dict):
        raise ValueError('site, config and auth must be JSON objects')
    if any(k in site_properties for k in FORBIDDEN_CA) or site_properties.get('managedEnvironmentId'):
        raise ValueError('Container Apps export rejected; use --platform containerapps')
    if isinstance(storage, dict):
        storage = props(storage)
    if not isinstance(storage, dict):
        raise ValueError('storage must be an App Service mount mapping')
    site_type = str(site.get('kind') or '')
    audit.check('linux' in site_type.lower() and 'container' in site_type.lower(), 'Linux container App Service')
    audit.check(bool(site_properties.get('httpsOnly')), 'HTTPS only')
    audit.check(str(site_properties.get('publicNetworkAccess') or '').lower() == 'disabled',
                'private inbound networking (public access disabled)', warning=True)
    audit.check(int(plan_properties.get('numberOfWorkers') or (plan.get('sku') or {}).get('capacity') or 0) == 1, 'exactly one App Service plan worker')
    audit.check(str(plan.get('kind') or '').lower() in ('linux', 'elastic') or bool(plan_properties.get('reserved')),
                'Linux App Service plan')
    sku = plan.get('sku') or {}
    audit.check(sku.get('tier') in ('PremiumV3', 'PremiumV4', 'IsolatedV2'),
                'conversion-capable plan tier (benchmark, not capacity proof)', warning=True)
    audit.check(not site_properties.get('slotSwapStatus'), 'no active slot swap', warning=True)
    audit.check(bool(config.get('alwaysOn')), 'Always On')
    audit.check(config.get('healthCheckPath') == HEALTH, f'health check {HEALTH}')
    fx = str(config.get('linuxFxVersion') or '')
    audit.check(fx.startswith('DOCKER|') and 'sitecontainers' not in fx.lower(),
                'classic DOCKER| App Service model (not sidecar)')
    audit.check(bool(re.search(r'@sha256:[a-fA-F0-9]{64}$', fx)), 'image pinned to digest')
    audit.check(bool(config.get('acrUseManagedIdentityCreds')) and bool(config.get('acrUserManagedIdentityID')),
                'ACR pull via managed identity')
    audit.check(str(config.get('ftpsState') or '').lower() == 'disabled', 'FTPS disabled')
    audit.check(str(config.get('minTlsVersion') or '') in ('1.2', '1.3'), 'minimum TLS 1.2')
    audit.check(not config.get('scmIpSecurityRestrictionsUseMain') is False,
                'SCM access inherits main restrictions', warning=True)
    # Linux custom containers support WebSockets natively; webSocketsEnabled is Windows-only.
    print('INFO  Linux WebSockets require an authenticated browser handshake test; webSocketsEnabled is not a Linux gate')
    settings = _names(settings)
    audit.check(settings.get('WEBSITES_PORT') == PORT, f'classic container port {PORT}')
    audit.check(settings.get('WEBSITES_ENABLE_APP_SERVICE_STORAGE') == 'false',
                'no implicit /home persistence; explicit approved data mount required')
    data_dir = settings.get('EPC_DATA_DIR')
    audit.check(data_dir == '/mounts/msapo', 'data directory uses explicit /mounts/msapo path')
    audit.check(settings.get('PDF_BACKEND') == 'libreoffice', 'LibreOffice selected')
    for name, value in FIXED.items():
        audit.check(settings.get(name) == value, f'{name} matches baseline')
    audit.check(bool(settings.get('SMARTSHEET_FORM_FIELD_MAP_JSON')), 'Smartsheet field map provided')
    audit.check(bool(settings.get('ANTHROPIC_MODEL')), 'AI model is configured (A05 approval pending)', warning=True)
    for name in REQUIRED_SECRETS:
        audit.check(_kv(settings.get(name)), f'{name} from Key Vault reference')
    for name in OPTIONAL_SECRETS:
        if name in settings:
            audit.check(_kv(settings[name]), f'optional {name} from Key Vault reference')
    audit.check('EPC_SQLITE_JOURNAL_MODE' not in settings or
                settings.get('EPC_SQLITE_JOURNAL_MODE') != 'wal',
                'network-mounted SQLite WAL not forced')
    audit.check('RENDER_GIT_COMMIT' not in settings and 'APP_GIT_COMMIT' not in settings,
                'build SHA belongs in image, not runtime settings')
    audit.check(all(not str(k).startswith(('CONTAINER_APP_', 'ACA_')) for k in settings),
                'no Container Apps settings')
    mounts = [v for v in storage.values() if isinstance(v, dict) and v.get('mountPath') == data_dir]
    audit.check(len(mounts) == 1 and mounts[0].get('type') == 'AzureFiles' and
                bool(mounts[0].get('shareName')), 'one declared approved Azure Files mount at data directory')
    if mounts:
        print('WARN  mount existence cannot prove POSIX locks, ACLs, SQLite safety or backup: A03 host qualification required')
        audit.warns += 1
    audit.check(str(auth.get('platform', {}).get('enabled')).lower() == 'true', 'App Service authentication enabled')
    global_validation = auth.get('globalValidation') or {}
    audit.check(global_validation.get('requireAuthentication') is True,
                'authentication required on all requests')
    audit.check(global_validation.get('unauthenticatedClientAction') in
                ('RedirectToLoginPage', 'Return401', 'Return403'), 'unauthenticated access denied')
    audit.check(not global_validation.get('excludedPaths'), 'no unauthenticated route exclusions')
    providers = auth.get('identityProviders') or {}
    entra = providers.get('azureActiveDirectory') or {}
    registration = entra.get('registration') or {}
    issuer = str(registration.get('openIdIssuer') or '')
    tenant = urlparse(issuer).path.strip('/').split('/')[0].lower()
    audit.check(bool(registration.get('clientId')) and bool(tenant) and
                tenant not in ('common', 'consumers', 'organizations'), 'single-tenant Entra issuer')
    policy = (entra.get('validation') or {}).get('defaultAuthorizationPolicy') or {}
    principals = policy.get('allowedPrincipals') or {}
    audit.check(bool(principals.get('groups') or principals.get('identities')),
                'explicit Entra group/user authorization')
    audit.check(not any(k != 'azureActiveDirectory' and v for k, v in providers.items()),
                'no other identity providers')
    audit.check(bool((auth.get('httpSettings') or {}).get('requireHttps', True)), 'auth requires HTTPS')
    print(f'\n{audit.fails} failure(s), {audit.warns} warning(s).')
    return 1 if audit.fails else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('site', help='az resource show export of Microsoft.Web/sites')
    for field in ('config', 'settings', 'auth', 'storage', 'plan'):
        parser.add_argument(f'--{field}', required=True)
    args = parser.parse_args(argv)
    try:
        site = read_json(args.site)
        if isinstance(site, dict) and site.get('type') not in ('Microsoft.Web/sites', 'microsoft.web/sites'):
            raise ValueError('not Microsoft.Web/sites; Container Apps exports are unsupported')
        return run(site, read_json(args.config), read_json(args.settings), read_json(args.auth),
                   read_json(args.storage), read_json(args.plan))
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
