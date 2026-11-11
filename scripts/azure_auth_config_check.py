#!/usr/bin/env python3
"""Redacted read-only App Service authsettingsV2 check; never print input values.

Usage: az webapp auth show -g <group> -n <app> -o json > restricted-auth.json
       python scripts/azure_auth_config_check.py restricted-auth.json

This does NOT check enterprise-app assignment, app roles, storage grants or
actual proxy/WebSocket behavior. Keep input out of public artifacts.
"""
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

_GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\Z")


def _obj(value):
    return value if isinstance(value, dict) else {}


def check(data: object) -> list[str]:
    if not isinstance(data, dict):
        return ["authsettingsV2 input must be an object"]
    p = _obj(data.get("properties", data))
    errors = []
    platform = _obj(p.get("platform"))
    validation = _obj(p.get("globalValidation"))
    http = _obj(p.get("httpSettings"))
    providers = _obj(p.get("identityProviders"))
    aad = _obj(providers.get("azureActiveDirectory"))
    reg = _obj(aad.get("registration"))
    aad_validation = _obj(aad.get("validation"))
    if platform.get("enabled") is not True:
        errors.append("platform.enabled must be true")
    if validation.get("requireAuthentication") is not True:
        errors.append("requireAuthentication must be true")
    if validation.get("unauthenticatedClientAction") not in ("RedirectToLoginPage", "Return401"):
        errors.append("anonymous access must redirect or return 401")
    if validation.get("excludedPaths", []) != []:
        errors.append("excludedPaths must be empty")
    if http.get("requireHttps") is not True:
        errors.append("httpSettings.requireHttps must be true")
    if aad.get("enabled") is not True:
        errors.append("single-tenant Entra provider must be enabled")
    for name in ("apple", "facebook", "gitHub", "google", "legacyMicrosoftAccount",
                 "twitter", "azureStaticWebApps"):
        if _obj(providers.get(name)).get("enabled") is True:
            errors.append("non-Entra provider must be disabled")
    if providers.get("customOpenIdConnectProviders"):
        errors.append("custom OIDC provider must be disabled")
    client = str(reg.get("clientId") or "")
    if not _GUID.fullmatch(client):
        errors.append("Entra client ID must be a GUID")
    issuer = str(reg.get("openIdIssuer") or "")
    prefix, suffix = "https://login.microsoftonline.com/", "/v2.0"
    if not issuer.startswith(prefix) or not issuer.endswith(suffix):
        errors.append("Entra issuer must be tenant-specific v2")
    elif not _GUID.fullmatch(issuer[len(prefix):-len(suffix)]):
        errors.append("Entra issuer cannot use a generic tenant")
    if not reg.get("clientSecretSettingName"):
        errors.append("Easy Auth client credential setting name is missing")
    audiences = aad_validation.get("allowedAudiences")
    if not isinstance(audiences, list) or not client or client not in audiences:
        errors.append("allowed audiences must include the intended client ID")
    return errors


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: azure_auth_config_check.py <authsettingsV2.json>", file=sys.stderr)
        return 2
    try:
        config = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        print("FAIL unreadable authentication configuration (content suppressed)")
        return 2
    errors = check(config)
    for error in errors:
        print("FAIL", error)
    if errors:
        return 1
    print("PASS App Service auth structure; enterprise assignment and runtime QA remain unverified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
