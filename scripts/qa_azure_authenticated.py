"""A10 read-only authenticated staging probe; never loosens Easy Auth or writes reports.

Requires a pre-created, least-privilege Playwright storage-state file on an
ENFRA-restricted runner and independently checked staging resource identities.
"""
from __future__ import annotations

import argparse
import base64
import http.client
import secrets
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse, urljoin

SHA = re.compile(r"[0-9a-f]{40}$")


def isolated(record: dict) -> bool:
    """A fail-closed guard; still requires independent Azure IAM verification."""
    if record.get("environment") not in ("test", "staging"):
        return False
    if record.get("smartsheet_api_mode") != "disabled":
        return False
    if record.get("production_write_access") is not False:
        return False
    for name in ("database", "files", "smartsheet"):
        target, prod = record.get(name + "_target"), record.get(name + "_production")
        if not target or not prod or target == prod:
            return False
    return True


def check_origin(origin: str, production_origin: str) -> bool:
    def parse(value):
        if not isinstance(value, str) or any(c.isspace() for c in value):
            return None
        try:
            parsed = urlparse(value)
            port = parsed.port  # Validate even when a port is not used below.
        except ValueError:
            return None
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.hostname.endswith(".") or parsed.username is not None
                or parsed.password is not None or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or port == 0):
            return None
        return parsed

    a, b = parse(origin), parse(production_origin)
    return bool(a and b and a.hostname != b.hostname)


def _same_https_authority(url: str, origin: str) -> bool:
    try:
        a, b = urlparse(url), urlparse(origin)
        return bool(a.scheme == b.scheme == "https" and a.hostname == b.hostname
                    and (a.port or 443) == (b.port or 443)
                    and a.username is None and a.password is None)
    except ValueError:
        return False


def _login_challenge(url: str, origin: str) -> bool:
    try:
        page = urlparse(url)
        trusted_provider = (page.scheme == "https" and (page.port or 443) == 443
                            and page.username is None and page.password is None
                            and page.hostname in ("login.microsoftonline.com", "login.microsoftonline.us"))
        return bool(trusted_provider or (_same_https_authority(url, origin)
                    and page.path.startswith("/.auth/login/")))
    except ValueError:
        return False


def signed_out_denial(status: int | None, final_url: str, app_origin: str, *,
                      served_marker: bool, websocket_opened: bool) -> bool:
    """An actual authentication challenge or explicit denial, never an empty UI."""
    challenge = ((status in (401, 403) and _same_https_authority(final_url, app_origin))
                 or _login_challenge(final_url, app_origin))
    return bool(challenge and not served_marker and not websocket_opened)


def unauthenticated_websocket_handshake(origin: str) -> tuple[int, str]:
    """Probe real HTTP Upgrade without cookies; a browser CSP denial is not proof.

    No application message is sent. An authorized service must deny or challenge
    before accepting a Streamlit WebSocket (HTTP 101).
    """
    parsed = urlparse(origin)
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=15)
    try:
        connection.request("GET", "/_stcore/stream", headers={
            "Host": parsed.netloc, "Upgrade": "websocket", "Connection": "Upgrade",
            "Sec-WebSocket-Key": key, "Sec-WebSocket-Version": "13",
            "Origin": origin,
        })
        response = connection.getresponse()
        return response.status, urljoin(origin, response.getheader("Location") or "")
    finally:
        connection.close()


def websocket_handshake_denied(status: int, location: str, origin: str) -> bool:
    """Fail if anonymous gets HTTP 101 or any ambiguous non-auth error."""
    if status in (401, 403):
        return True
    if status not in (302, 303, 307, 308):
        return False
    return _login_challenge(location, origin)


def track_stream_frames(page, origin: str) -> list[bool]:
    """Record only receipt of frames, never their contents or a mere socket attempt."""
    observations: list[bool] = []

    def observe(socket):
        try:
            candidate, expected = urlparse(socket.url), urlparse(origin)
            matches = (candidate.scheme == "wss" and candidate.hostname == expected.hostname
                       and (candidate.port or 443) == (expected.port or 443)
                       and candidate.path == "/_stcore/stream"
                       and candidate.username is None and candidate.password is None)
        except ValueError:
            matches = False
        if not matches:
            return
        index = len(observations)
        observations.append(False)

        def received(_payload):
            observations[index] = True

        socket.on("framereceived", received)

    page.on("websocket", observe)
    return observations


def run_probe(origin: str, storage_state: Path, expected_sha: str) -> dict:
    from playwright.sync_api import sync_playwright
    from scripts.qa_public_build import running_code_marker
    events = {"signed_out_page_denied": "NOT_RUN", "signed_out_socket_denied": "NOT_RUN",
              "authenticated_page": "NOT_RUN", "served_sha": "NOT_RUN",
              "websocket_initial": "NOT_RUN", "websocket_reconnect": "NOT_RUN"}
    with sync_playwright() as client:
        browser = client.chromium.launch(headless=True)
        try:
            # Independent context, with no stored cookies or sign-in state.
            anonymous = browser.new_context(accept_downloads=False)
            unauth_page = anonymous.new_page()
            unauth_page.goto(origin + "/?workflow=monthly", wait_until="domcontentloaded", timeout=45000)
            unauth_page.wait_for_timeout(1500)
            response = unauth_page.request.get(origin + "/?workflow=monthly", max_redirects=0)
            ws_status, ws_location = unauthenticated_websocket_handshake(origin)
            socket_denied = websocket_handshake_denied(ws_status, ws_location, origin)
            challenge = signed_out_denial(response.status, unauth_page.url, origin,
                                          served_marker=bool(unauth_page.get_by_text(re.compile(r"^Running code:")).count()),
                                          websocket_opened=not socket_denied)
            events["signed_out_page_denied"] = "PASS" if challenge else "FAIL"
            events["signed_out_socket_denied"] = "PASS" if socket_denied else "FAIL"
            anonymous.close()
            context = browser.new_context(storage_state=str(storage_state), accept_downloads=False)
            page = context.new_page()
            stream_frames = track_stream_frames(page, origin)
            page.goto(origin + "/?workflow=monthly", wait_until="domcontentloaded", timeout=45000)
            label = (running_code_marker(page, timeout=25000).text_content() or "").strip()
            events["authenticated_page"] = "PASS"
            events["served_sha"] = "PASS" if label == "Running code: " + expected_sha else "FAIL"
            page.wait_for_timeout(2500)
            events["websocket_initial"] = "PASS" if any(stream_frames) else "FAIL"
            prior = len(stream_frames)
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            events["websocket_reconnect"] = "PASS" if any(stream_frames[prior:]) else "FAIL"
            context.close()
        finally:
            browser.close()
    return events


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--production-origin", required=True)
    parser.add_argument("--storage-state", type=Path, required=True)
    parser.add_argument("--isolation-json", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = {"kind": "A10-readonly-authenticated", "at_utc": datetime.now(timezone.utc).isoformat(),
              "synthetic_only": True, "checks": {}, "limitations": [
                  "Does not test wrong-tenant, role separation or token expiration.",
                  "Does not establish native Word, physical Safari, or two-user isolation."]}
    safe = False
    try:
        safe = (bool(SHA.fullmatch(args.sha)) and check_origin(args.origin, args.production_origin)
                and args.storage_state.is_file() and isolated(json.loads(args.isolation_json.read_text())))
    except (ValueError, OSError, json.JSONDecodeError):
        pass
    if not safe:
        result["status"] = "BLOCKED"
        result["checks"]["isolation_preflight"] = "FAIL"
    else:
        result["checks"]["isolation_preflight"] = "PASS"
        try:
            result["checks"].update(run_probe(args.origin, args.storage_state, args.sha))
            result["status"] = "PASS" if all(v == "PASS" for v in result["checks"].values()) else "FAIL"
        except Exception as error:
            result["status"] = "NOT_RUN"
            result["checks"]["browser_probe"] = type(error).__name__  # never include tokens/URLs
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print("A10 authenticated probe: " + result["status"])
    return {"PASS": 0, "FAIL": 2, "NOT_RUN": 3, "BLOCKED": 4}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
