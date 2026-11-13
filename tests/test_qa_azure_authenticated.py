"""Stage isolation and access guards are pure local tests; no live identity calls."""
import json

from scripts.qa_azure_authenticated import check_origin, isolated, main


GOOD = {"environment": "staging", "smartsheet_api_mode": "disabled", "production_write_access": False,
        "database_target": "stg-db", "database_production": "prod-db",
        "files_target": "stg-files", "files_production": "prod-files",
        "smartsheet_target": "dry-run", "smartsheet_production": "production"}


def test_staging_requires_three_distinct_external_resources_and_no_prod_writes():
    assert isolated(GOOD)
    for key, value in (("environment", "production"), ("smartsheet_api_mode", "live"),
                       ("production_write_access", True), ("database_target", "prod-db"),
                       ("files_target", "prod-files"), ("smartsheet_target", "production")):
        invalid = {**GOOD, key: value}
        assert not isolated(invalid), key
    assert not isolated({**GOOD, "database_target": ""})


def test_https_exact_origin_and_separate_host_are_required():
    assert check_origin("https://stage.example.invalid", "https://production.example.invalid")
    for candidate in ("http://stage.example.invalid", "https://production.example.invalid",
                      "https://stage.example.invalid/hidden", "https://user:pass@stage.example.invalid",
                      "https://stage.example.invalid?bypass=1"):
        assert not check_origin(candidate, "https://production.example.invalid")


def test_preflight_blocks_before_network_access(tmp_path):
    state = tmp_path / "auth.json"
    state.write_text("{}")
    identity = tmp_path / "isolation.json"
    identity.write_text(json.dumps({**GOOD, "production_write_access": True}))
    out = tmp_path / "result.json"
    rc = main(["--origin", "https://stage.example.invalid",
               "--production-origin", "https://production.example.invalid",
               "--sha", "a"*40, "--storage-state", str(state),
               "--isolation-json", str(identity), "--output", str(out)])
    assert rc == 4
    assert json.loads(out.read_text())["status"] == "BLOCKED"


def test_signed_out_requires_actual_denial_not_blank_ui():
    from scripts.qa_azure_authenticated import signed_out_denial
    base = "https://stage.example.invalid"
    assert signed_out_denial(401, base + "/?workflow=monthly", base, served_marker=False, websocket_opened=False)
    assert signed_out_denial(200, "https://login.microsoftonline.com/tenant/oauth", base,
                             served_marker=False, websocket_opened=False)
    for status, url, marker, socket in (
        (200, base + "/?workflow=monthly", False, False),
        (200, base + "/?workflow=monthly", True, True),
        (200, "https://unrelated.example.invalid/login", False, False),
        (403, base + "/?workflow=monthly", True, False),
        (401, base + "/?workflow=monthly", False, True),
    ):
        assert not signed_out_denial(status, url, base, served_marker=marker, websocket_opened=socket)


def test_upgrade_probe_needs_an_auth_challenge_not_network_or_csp_failure():
    from scripts.qa_azure_authenticated import websocket_handshake_denied
    origin = "https://stage.example.invalid"
    assert websocket_handshake_denied(401, origin, origin)
    assert websocket_handshake_denied(403, origin, origin)
    assert websocket_handshake_denied(302, origin + "/.auth/login/aad", origin)
    assert websocket_handshake_denied(302, "https://login.microsoftonline.com/tenant/oauth2", origin)
    for status, redirect in ((101, ""), (400, ""), (200, ""),
                             (302, "https://unrelated.example.invalid/login"),
                             (302, origin + "/other")):
        assert not websocket_handshake_denied(status, redirect, origin)
