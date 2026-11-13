"""Offline, redacted MSAPO Azure external-integration configuration preflight.

This is a *migration preparation* gate: it intentionally rejects Smartsheet
live API writes, new server-side mail or network-PDF backends. It does not
validate ENFRA provider approvals, identity claims or actual connectivity.

Usage:
  python scripts/azure_external_integrations_check.py settings.json --scope production
  python scripts/azure_external_integrations_check.py --from-environment --scope staging

Settings JSON may be a mapping of setting names to values or an Azure App
Service appsettings-list array of {"name": ..., "value": ...} objects. Keep
real exported settings outside source control; the checker NEVER echoes values.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Finding:
    level: str
    name: str
    message: str


def _check_bool(settings: Mapping[str, str], name: str, default: bool, findings: list[Finding]) -> bool:
    raw = str(settings.get(name, '') or '').strip().casefold()
    if not raw:
        return default
    if raw not in {'true', 'false'}:
        findings.append(Finding('FAIL', name, 'must be explicitly true or false'))
        return False
    return raw == 'true'


def _domain(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
            return '', ''
        return parsed.scheme.lower(), (parsed.hostname or '').lower()
    except ValueError:
        return '', ''


def _parse_json_object(settings: Mapping[str, str], name: str, findings: list[Finding]) -> dict:
    raw = settings.get(name, '')
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        findings.append(Finding('FAIL', name, 'must be a JSON object'))
        return {}
    if not isinstance(data, dict):
        findings.append(Finding('FAIL', name, 'must be a JSON object'))
        return {}
    return data


def audit(settings: Mapping[str, str], *, scope: str = 'staging') -> list[Finding]:
    """Report only *setting names*, categorical results and generic remedies."""
    if scope not in {'development', 'staging', 'production'}:
        raise ValueError('scope must be development, staging or production')
    out: list[Finding] = []
    mode = str(settings.get('SMARTSHEET_API_MODE', 'disabled') or 'disabled').strip().lower()
    if mode not in {'disabled', 'dry_run', 'live'}:
        out.append(Finding('FAIL', 'SMARTSHEET_API_MODE', 'invalid mode'))
    elif mode == 'live':
        out.append(Finding('FAIL', 'SMARTSHEET_API_MODE', 'live API writes are not approved by migration preparation'))
    elif mode == 'dry_run':
        out.append(Finding('PASS', 'SMARTSHEET_API_MODE', 'API mode is dry_run; no row writes permitted'))
    else:
        out.append(Finding('PASS', 'SMARTSHEET_API_MODE', 'API mode is disabled'))

    form = str(settings.get('SMARTSHEET_FORM_URL', '') or '').strip()
    if form:
        scheme, host = _domain(form)
        if scheme != 'https' or not (host == 'smartsheet.com' or host.endswith('.smartsheet.com')):
            out.append(Finding('FAIL', 'SMARTSHEET_FORM_URL', 'must use HTTPS and an exact Smartsheet hostname; no userinfo or fragment'))
        else:
            out.append(Finding('PASS', 'SMARTSHEET_FORM_URL', 'HTTPS Smartsheet host; exact environment form ID still needs approval'))
    else:
        out.append(Finding('FAIL' if scope == 'production' else 'WARN', 'SMARTSHEET_FORM_URL', 'browser form handoff is not configured'))

    prefill = _check_bool(settings, 'SMARTSHEET_URL_PREFILL_ENABLED', False, out)
    form_map = _parse_json_object(settings, 'SMARTSHEET_FORM_FIELD_MAP_JSON', out)
    if form_map:
        labels = list(form_map.values())
        if not all(isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip() for k, v in form_map.items()) or len(set(labels)) != len(labels):
            out.append(Finding('FAIL', 'SMARTSHEET_FORM_FIELD_MAP_JSON', 'labels must be nonempty distinct strings'))
    if prefill and (not form or not form_map):
        out.append(Finding('FAIL', 'SMARTSHEET_URL_PREFILL_ENABLED', 'prefill requires a verified form URL and exact field map'))
    elif prefill:
        out.append(Finding('WARN', 'SMARTSHEET_URL_PREFILL_ENABLED', 'verify current form labels and URL length in each environment before use'))
    else:
        out.append(Finding('PASS', 'SMARTSHEET_URL_PREFILL_ENABLED', 'prefill disabled; manual URL requires configured form'))
    _parse_json_object(settings, 'SMARTSHEET_FORM_VALUE_MAP_JSON', out)
    try:
        limit = int(str(settings.get('SMARTSHEET_PREFILL_MAX_URL_LENGTH', '7000') or '7000'))
        if not 1000 <= limit <= 20000:
            raise ValueError
    except ValueError:
        out.append(Finding('FAIL', 'SMARTSHEET_PREFILL_MAX_URL_LENGTH', 'must be an integer between 1000 and 20000'))

    allow_custom = _check_bool(settings, 'SMARTSHEET_ALLOW_CUSTOM_API_BASE', False, out)
    base = str(settings.get('SMARTSHEET_API_BASE_URL', 'https://api.smartsheet.com/2.0') or '').strip()
    scheme, host = _domain(base)
    if scheme != 'https' or (host != 'api.smartsheet.com' and not (allow_custom and mode != 'live' and scope != 'production')):
        out.append(Finding('FAIL', 'SMARTSHEET_API_BASE_URL', 'must be HTTPS and the official API host unless isolated nonproduction fake is explicitly enabled'))
    if allow_custom and scope == 'production':
        out.append(Finding('FAIL', 'SMARTSHEET_ALLOW_CUSTOM_API_BASE', 'custom API bases are prohibited in production'))
    if settings.get('SMARTSHEET_API_TOKEN') and mode != 'live':
        out.append(Finding('WARN', 'SMARTSHEET_API_TOKEN', 'configured but not required for disabled/dry_run; protect and minimize exposure'))

    directors = _parse_json_object(settings, 'EXPENSE_ACCOUNT_DIRECTORS_JSON', out)
    if not directors:
        out.append(Finding('WARN', 'EXPENSE_ACCOUNT_DIRECTORS_JSON', 'no confirmed contract-director map; verify manual fallback and approval roster before cutover'))
    else:
        valid = all(
            isinstance(account, str) and account.strip() and isinstance(entry, dict)
            and isinstance(entry.get('name'), str) and bool(entry['name'].strip())
            and isinstance(entry.get('email'), str)
            and bool(re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', entry['email'].strip()))
            for account, entry in directors.items()
        )
        out.append(Finding('PASS' if valid else 'FAIL', 'EXPENSE_ACCOUNT_DIRECTORS_JSON',
                           'director map shape is valid; per-account authorization remains unverified' if valid
                           else 'each account requires a director name and email'))

    for legacy in ('RRH_APPROVER_NAME', 'RRH_APPROVER_EMAIL'):
        if legacy in settings:
            out.append(Finding('WARN', legacy, 'obsolete variable is ignored; remove during Azure configuration reconciliation'))
    backend = str(settings.get('PDF_BACKEND', 'libreoffice') or '').strip().lower()
    if backend != 'libreoffice':
        out.append(Finding('FAIL', 'PDF_BACKEND', 'migration must retain the current local LibreOffice renderer'))
    else:
        out.append(Finding('PASS', 'PDF_BACKEND', 'local LibreOffice renderer retained'))
    if settings.get('GOTENBERG_URL') and backend == 'libreoffice':
        out.append(Finding('WARN', 'GOTENBERG_URL', 'configured but unused with local renderer; verify no accidental backend switch'))

    for name in ('SMTP_HOST', 'SMTP_SERVER', 'EMAIL_SEND_ENABLED', 'MICROSOFT_GRAPH_MAIL_ENABLED'):
        if name in settings and str(settings[name]).strip():
            out.append(Finding('FAIL', name, 'new server-side mail route is outside migration scope'))
    out.append(Finding('WARN', 'EPC_DATA_DIR', 'verify durable submission-store migration and reopen under persistence acceptance; path alone is not evidence'))
    return out


def load_settings(path: Path) -> dict[str, str]:
    raw = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(raw, list):
        if not all(isinstance(item, dict) and isinstance(item.get('name'), str) for item in raw):
            raise ValueError('expected a list of App Service {name,value} items')
        names = [item['name'] for item in raw]
        if len(set(names)) != len(names):
            raise ValueError('duplicate setting names')
        return {item['name']: str(item.get('value', '') or '') for item in raw}
    if isinstance(raw, dict) and all(isinstance(key, str) for key in raw):
        return {key: str(value or '') for key, value in raw.items()}
    raise ValueError('expected mapping or App Service settings list')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('settings_file', nargs='?', type=Path)
    parser.add_argument('--from-environment', action='store_true')
    parser.add_argument('--scope', choices=['development', 'staging', 'production'], default='staging')
    args = parser.parse_args(argv)
    if args.from_environment == bool(args.settings_file):
        parser.error('choose one settings file or --from-environment')
    try:
        settings = dict(os.environ) if args.from_environment else load_settings(args.settings_file)
        findings = audit(settings, scope=args.scope)
    except (OSError, ValueError):
        print('FAIL settings input is unavailable or invalid (details withheld)')
        return 2
    for finding in findings:
        print(f'{finding.level} {finding.name}: {finding.message}')
    return 1 if any(item.level == 'FAIL' for item in findings) else 0


if __name__ == '__main__':
    raise SystemExit(main())
