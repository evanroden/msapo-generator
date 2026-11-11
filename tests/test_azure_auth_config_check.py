"""Synthetic App Service authsettingsV2 safety checks; no ENFRA IDs or tokens."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from scripts.azure_auth_config_check import check

APP = "33333333-3333-4333-8333-333333333333"
TENANT = "11111111-1111-4111-8111-111111111111"


def good():
    return {"properties": {
        "platform": {"enabled": True},
        "globalValidation": {
            "requireAuthentication": True, "excludedPaths": [],
            "unauthenticatedClientAction": "RedirectToLoginPage",
            "redirectToProvider": "azureActiveDirectory"},
        "httpSettings": {"requireHttps": True},
        "identityProviders": {"azureActiveDirectory": {
            "enabled": True,
            "registration": {"clientId": APP,
                "clientSecretSettingName": "ENFRA_ENTRA_CLIENT_SECRET",
                "openIdIssuer": f"https://login.microsoftonline.com/{TENANT}/v2.0"},
            "validation": {"allowedAudiences": [APP]}}},
    }}


def test_safe_configuration_passes_without_live_tenant():
    assert check(good()) == []


def test_enabled_and_anonymous_conditions_fail_closed():
    cases = [
        ("platform", "enabled", False),
        ("globalValidation", "requireAuthentication", False),
        ("globalValidation", "unauthenticatedClientAction", "AllowAnonymous"),
        ("globalValidation", "excludedPaths", ["/_stcore/health"]),
        ("httpSettings", "requireHttps", False),
    ]
    for section, key, bad in cases:
        c = good()
        c["properties"][section][key] = bad
        assert check(c), (section, key)


def test_provider_tenant_audience_and_secret_reference_downgrade():
    def mutate(*keys, value):
        c = good()
        node = c
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
        return c

    for c in [
        mutate("properties", "identityProviders", "azureActiveDirectory", "enabled", value=False),
        mutate("properties", "identityProviders", "google", value={"enabled": True}),
        mutate("properties", "identityProviders", "customOpenIdConnectProviders",
               value={"myprovider": {"enabled": True}}),
        mutate("properties", "identityProviders", "azureActiveDirectory", "registration",
               "openIdIssuer", value="https://login.microsoftonline.com/common/v2.0"),
        mutate("properties", "identityProviders", "azureActiveDirectory", "registration",
               "clientId", value=""),
        mutate("properties", "identityProviders", "azureActiveDirectory", "registration",
               "clientSecretSettingName", value=""),
        mutate("properties", "identityProviders", "azureActiveDirectory", "validation",
               "allowedAudiences", value=[]),
    ]:
        assert check(c), "unsafe control-plane auth configuration passed"


def test_invalid_shape_no_exception_and_no_values_printed(tmp_path, capsys):
    assert check(None)
    assert check({"properties": {"globalValidation": "invalid"}})
    # Checker prints only field names and generic failure text.
    unsafe = good()
    unsafe["properties"]["identityProviders"]["google"] = {"enabled": True,
                                                               "clientSecret": "DO-NOT-ECHO"}
    path = tmp_path / "auth.json"
    path.write_text(json.dumps(unsafe))
    proc = subprocess.run([sys.executable, "scripts/azure_auth_config_check.py", str(path)],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    assert "DO-NOT-ECHO" not in proc.stdout + proc.stderr
    assert APP not in proc.stdout + proc.stderr
    assert TENANT not in proc.stdout + proc.stderr


def test_bicep_template_wont_exempt_streamlit_routes():
    text = Path("infra/azure/a04-appservice-auth.bicep").read_text()
    assert "excludedPaths: []" in text
    assert "requireAuthentication: true" in text
    assert "httpSettings" in text and "requireHttps: true" in text
    assert "ENTRA_TENANT_ID" not in text  # interpolation present, not a stub
    assert "authsettingsV2" in text
    assert "AllowAnonymous" not in text
