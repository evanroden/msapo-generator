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


def test_origin_comparison_rejects_dns_alias_spelling_and_invalid_origins():
    prod = "https://production.example.invalid"
    for candidate in ("https://production.example.invalid.",
                      "https://production.example.invalid.:443",
                      "https://stage.example.invalid:99999",
                      "https://stage.example.invalid/not-an-origin"):
        assert not check_origin(candidate, prod)
    assert not check_origin("https://stage.example.invalid", prod + "/path")


def test_socket_must_receive_a_frame_from_a_new_same_origin_stream():
    from scripts.qa_azure_authenticated import track_stream_frames

    class Socket:
        def __init__(self, url):
            self.url, self.handlers = url, {}

        def on(self, name, handler):
            self.handlers[name] = handler

        def receive(self):
            self.handlers["framereceived"]("private data must not be recorded")

    class Page:
        def on(self, name, handler):
            assert name == "websocket"
            self.handler = handler

    page = Page()
    observations = track_stream_frames(page, "https://stage.example.invalid")
    initial = Socket("wss://stage.example.invalid/_stcore/stream")
    page.handler(initial)
    assert len(observations) == 1 and not observations[0]
    initial.receive()
    assert observations == [True]
    before_reload = len(observations)
    unrelated = Socket("wss://other.example.invalid/_stcore/stream")
    page.handler(unrelated)
    initial.receive()  # An old connection is not proof of reconnection.
    assert not any(observations[before_reload:])
    replacement = Socket("wss://stage.example.invalid/_stcore/stream")
    page.handler(replacement)
    assert not any(observations[before_reload:])
    replacement.receive()
    assert any(observations[before_reload:])


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
        (200, "http://login.microsoftonline.com/tenant/oauth", False, False),
        (200, "https://login.microsoftonline.com:444/tenant/oauth", False, False),
        (403, "https://stage.example.invalid:444/", False, False),
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
                             (302, "http://login.microsoftonline.com/tenant/oauth2"),
                             (302, "https://login.microsoftonline.com:444/tenant/oauth2"),
                             (302, "https://stage.example.invalid:444/.auth/login/aad"),
                             (302, origin + "/other")):
        assert not websocket_handshake_denied(status, redirect, origin)
