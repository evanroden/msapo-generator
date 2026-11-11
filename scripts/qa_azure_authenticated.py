"""A10 read-only authenticated staging probe; never loosens Easy Auth or writes reports.

Requires a pre-created, least-privilege Playwright storage-state file on an
ENFRA-restricted runner and independently checked staging resource identities.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlparse

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
    a, b = urlparse(origin), urlparse(production_origin)
    return (a.scheme == b.scheme == "https" and a.hostname and b.hostname
            and a.hostname != b.hostname and not a.username and not a.password
            and not a.query and not a.fragment and not a.path.strip("/"))


def run_probe(origin: str, storage_state: Path, expected_sha: str) -> dict:
    from playwright.sync_api import sync_playwright
    from scripts.qa_public_build import running_code_marker
    events = {"authenticated_page": "NOT_RUN", "served_sha": "NOT_RUN",
              "websocket_initial": "NOT_RUN", "websocket_reconnect": "NOT_RUN"}
    with sync_playwright() as client:
        browser = client.chromium.launch(headless=True)
        try:
            context = browser.new_context(storage_state=str(storage_state), accept_downloads=False)
            page = context.new_page()
            ws_urls = []
            page.on("websocket", lambda ws: ws_urls.append(ws.url))
            page.goto(origin + "/?workflow=monthly", wait_until="domcontentloaded", timeout=45000)
            label = (running_code_marker(page, timeout=25000).text_content() or "").strip()
            events["authenticated_page"] = "PASS"
            events["served_sha"] = "PASS" if label == "Running code: " + expected_sha else "FAIL"
            page.wait_for_timeout(2500)
            events["websocket_initial"] = ("PASS" if any("/_stcore/stream" in url for url in ws_urls)
                                           else "FAIL")
            prior = len(ws_urls)
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            events["websocket_reconnect"] = ("PASS" if any("/_stcore/stream" in url for url in ws_urls[prior:])
                                             else "FAIL")
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
