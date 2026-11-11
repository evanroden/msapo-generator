"""Observe the current served build, then require exact read-only bracketing.

Durability is not tied to a particular feature release. Other workers can deploy
between preparation and execution. Discover the build once, then use the existing
verifier unchanged; a cutover during the actual check must still fail. The public
configuration's preparation-time expected commit is replaced only in a temporary
copy; the baseline is supplied explicitly and may never equal the observed build.
"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory


def checked_build(text: str, baseline: str) -> str:
    match = re.fullmatch(r"Running code: ([0-9a-f]{40})", text.strip())
    if not match or not re.fullmatch(r"[0-9a-f]{40}", baseline):
        raise ValueError("No exact native build identity.")
    if match[1] == baseline:
        raise ValueError("Same-build observations do not prove redeploy durability.")
    return match[1]


def observe_current(baseline: str) -> str:
    from playwright.sync_api import sync_playwright
    from scripts import qa_shared_fixture_redeploy_readonly as existing
    from scripts.qa_public_build import running_code_marker
    refused, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(service_workers="block")
            context.route("**/*", lambda route: existing._browser_route(route, refused))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.goto(existing.ORIGIN + existing.BUILD_ROUTE,
                      wait_until="domcontentloaded", timeout=65000)
            marker = running_code_marker(page)
            result = checked_build(marker.text_content() or "", baseline)
            if refused or errors:
                raise ValueError("External request or browser error during build observation.")
            return result
        finally:
            browser.close()


def main(path: str, baseline: str) -> int:
    from scripts import qa_private_fixture_witness as witness
    config = json.loads(Path(path).read_text())
    witness.seal({"bootstrap": True}, config["public_key"])
    try:
        actual = observe_current(baseline)
        print("Observed exact native served build: " + actual, flush=True)
        config["expected_commit"] = actual
        with TemporaryDirectory(prefix="readonly-public-config-") as temporary:
            destination = Path(temporary) / "public-config.json"
            destination.write_text(json.dumps(config))
            return witness.main(str(destination))
    except Exception as exc:
        # Only sealed metadata/error diagnostics may survive a failed observation.
        report = {"accepted": False, "stage": "observe-current-build",
                  "workflow_run": os.environ.get("GITHUB_RUN_ID", ""),
                  "verifier_commit": os.environ.get("GITHUB_SHA", ""),
                  "error_type": type(exc).__name__, "private_error": str(exc)[:10000],
                  "finished_at_utc": datetime.now(timezone.utc).isoformat()}
        destination = Path("test-artifacts/private-fixture-witness/receipt.encrypted.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Never replace a completed delegated receipt.
        if not destination.exists():
            with destination.open("xb") as output:
                output.write(witness.seal(report, config["public_key"]))
        print("FAIL current-build observation; diagnostics encrypted", flush=True)
        return 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        assert checked_build("Running code: " + "a" * 40, "b" * 40) == "a" * 40
        for text in ("Running code: " + "b" * 40, "Running code: abcd", "unknown"):
            try:
                checked_build(text, "b" * 40)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid or same-build observation was accepted.")
        print("PASS exact observed-build and distinct-baseline controls")
    elif len(sys.argv) == 3:
        raise SystemExit(main(sys.argv[1], sys.argv[2]))
    else:
        raise SystemExit("Pass a public configuration path and baseline commit, or --self-test.")
