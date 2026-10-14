"""Opt-in hash-only production shared-fixture check on two *served* code revisions.

This CLI never uploads files, starts imported reports, resets any workspace,
saves source bytes to artifacts, invokes paid readers or changes Render settings.
A temporary isolated QA view is used only for the existing running-code marker;
it is not an authentic report or durable fixture acceptance. Use a deliberately
synthetic witness fixture whenever possible. Two verified distinct served SHAs
are required for a valid before/after comparison.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlparse

ORIGIN = "https://msapo-generator.onrender.com"
FIXTURE_ROUTE = "/?workflow=monthly&monthly_qa=fixtures"
BUILD_ROUTE = "/?workflow=monthly&monthly_qa=isolated"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_ID_PREFIX = re.compile(r"[0-9a-f]{8}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
KIND = "enfra-shared-fixture-redeploy-readonly-v1"
MAX_ORIGINAL = 25 * 1024 * 1024


def _valid_id(value: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Pass the exact 32-character opaque shared fixture ID.")
    return value


def _selector_id(value: str) -> str:
    """Use the eight-character ID displayed in the UI, or its full identity."""
    if not isinstance(value, str) or not (_ID.fullmatch(value) or _ID_PREFIX.fullmatch(value)):
        raise ValueError("Provide the displayed eight-hex ID prefix or its full 32-hex ID.")
    return value


def _valid_hash(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError("Pass the exact 64-character original SHA-256 digest.")
    return value


def _valid_commit(value: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError("Pass the full 40-character deployed commit SHA.")
    return value


def _validate_manifest(value: dict, phase: str) -> dict:
    if not isinstance(value, dict) or value.get("schema") != 1 or value.get("kind") != KIND:
        raise ValueError("Not a recognized hash-only fixture verification receipt.")
    if value.get("phase") != phase or value.get("endpoint") != ORIGIN:
        raise ValueError("Wrong phase or shared production endpoint.")
    _valid_id(value.get("fixture_id"))
    _valid_hash(value.get("original_sha256"))
    _valid_commit(value.get("served_commit"))
    size = value.get("original_size")
    if type(size) is not int or not 1 <= size <= MAX_ORIGINAL:
        raise ValueError("Original length is outside the shared fixture limit.")
    if value.get("read_only_checks") != ["exact_served_commit", "selected_original_identity", "original_download_sha256"]:
        raise ValueError("The three mandatory read-only checks did not complete.")
    try:
        moment = datetime.fromisoformat(value["verified_at_utc"].replace("Z", "+00:00"))
        if moment.utcoffset() is None or moment.utcoffset().total_seconds() != 0:
            raise ValueError
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Invalid UTC verification timestamp.") from exc
    return value


def compare(before: dict, after: dict) -> dict:
    """A selected original survived two different observed served builds."""
    before = _validate_manifest(before, "before")
    after = _validate_manifest(after, "after")
    if before["fixture_id"] != after["fixture_id"]:
        raise ValueError("The two passes selected different original fixture IDs.")
    if before["original_sha256"] != after["original_sha256"]:
        raise ValueError("The stored original changed between builds.")
    if before["original_size"] != after["original_size"]:
        raise ValueError("The original size changed between builds.")
    if before["served_commit"] == after["served_commit"]:
        raise ValueError("Identical served builds do NOT establish redeploy persistence.")
    start = datetime.fromisoformat(before["verified_at_utc"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(after["verified_at_utc"].replace("Z", "+00:00"))
    if end <= start:
        raise ValueError("The after observation must follow the before observation.")
    return {
        "schema": 1, "kind": "enfra-shared-fixture-redeploy-comparison-v1",
        "endpoint": ORIGIN, "fixture_id": before["fixture_id"],
        "original_sha256": before["original_sha256"],
        "original_size": before["original_size"],
        "before_commit": before["served_commit"],
        "after_commit": after["served_commit"],
        "hash_identical_across_distinct_served_builds": True,
        "limits": "Browser hash check only; not an authentic report or Microsoft Word/Adobe review.",
    }


def _browser_route(route, refused: list[str]) -> None:
    parsed = urlparse(route.request.url)
    if parsed.scheme in {"blob", "data"}:
        route.continue_()
        return
    if parsed.scheme == "https" and parsed.netloc == "msapo-generator.onrender.com":
        route.continue_()
        return
    refused.append((parsed.scheme or "?") + ":" + (parsed.hostname or "?"))
    route.abort()


def _served_commit(page, expected: str) -> None:
    """Use the existing QA build marker; don't assume GitHub merge = deploy."""
    from playwright.sync_api import expect
    last = "none"
    deadline = time.monotonic() + 8 * 60
    while time.monotonic() < deadline:
        try:
            page.goto(ORIGIN + BUILD_ROUTE, wait_until="domcontentloaded", timeout=65000)
            marker = page.get_by_text(re.compile(r"^Running code: [0-9a-f]{40}$")).first
            expect(marker).to_be_visible(timeout=16000)
            last = (marker.text_content() or "").strip()
            if last == "Running code: " + expected:
                return
        except Exception as exc:
            last = type(exc).__name__
        print("Waiting for exact served build; last status " + last[:110], flush=True)
        time.sleep(12)
    raise AssertionError("Expected commit not yet served (last observation: " + last[:120] + ").")


def verify_one(fixture_id: str, original_hash: str, served_commit: str,
               phase: str) -> dict:
    """Read only one explicitly specified original; never enumerate its contents."""
    requested = _selector_id(fixture_id)
    original_hash = _valid_hash(original_hash)
    served_commit = _valid_commit(served_commit)
    if phase not in ("before", "after"):
        raise ValueError("Phase must be before or after.")
    from playwright.sync_api import sync_playwright, expect
    rejected: list[str] = []
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000},
                accept_downloads=True,
            )
            context.route("**/*", lambda route: _browser_route(route, rejected))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.set_default_timeout(25000)
            _served_commit(page, served_commit)
            page.goto(ORIGIN + FIXTURE_ROUTE, wait_until="domcontentloaded", timeout=65000)
            expect(page.get_by_role("heading", name="Shared report testing", exact=True)).to_be_visible(timeout=60000)
            selector = page.get_by_role("combobox", name="Shared fixture", exact=True)
            expect(selector).to_be_visible(timeout=45000)
            selector.click()
            # A prefix-only match is not a valid fixture identity. Require ONE
            # option, then the full 32-character fixture ID + original SHA
            # encoded by the current native download widget.
            options = page.get_by_role(
                "option", name=re.compile(r" · " + requested[:8] + r"$"))
            expect(options).to_have_count(1, timeout=20000)
            options.first.click()
            page.get_by_text("Confirmed source, target and expected results", exact=True).click()
            expect(page.get_by_text("Original SHA256: " + original_hash, exact=True)).to_be_visible(timeout=45000)
            # Source-specific native action classes expose the FULL opaque
            # ID; a displayed eight-character prefix alone is not proof of
            # which stored original is actually wired for download.
            token = re.compile(r"st-key-_shared_fixture_download_([0-9a-f]{32})_" +
                               original_hash[:16] + r"\Z")
            page.wait_for_function(
                """() => document.querySelector('[data-testid="stApp"]')
                  ?.getAttribute('data-test-script-state') === 'notRunning'""",
                timeout=45000,
            )
            expect(page.locator('[class*="st-key-_shared_fixture_download_"]').first).to_be_visible(timeout=45000)
            classes = page.locator('[class*="st-key-_shared_fixture_download_"]').evaluate_all(
                "(nodes) => nodes.map(node => node.className).filter(value => typeof value === 'string')")
            identities = {match[1] for name in classes for candidate in name.split()
                          if (match := token.fullmatch(candidate))}
            if len(identities) != 1:
                raise AssertionError("No unique full source-bound native download control is mounted.")
            fixture_id = next(iter(identities))
            if fixture_id[:8] != requested[:8] or (len(requested) == 32 and fixture_id != requested):
                raise AssertionError("The native download is wired to the wrong shared original.")
            scope = fixture_id + "_" + original_hash[:16]
            download_widget = page.locator(".st-key-_shared_fixture_download_" + scope)
            expect(download_widget).to_be_visible(timeout=45000)
            page.wait_for_function(
                """() => document.querySelector('[data-testid="stApp"]')
                  ?.getAttribute('data-test-script-state') === 'notRunning'""",
                timeout=45000,
            )
            with page.expect_download(timeout=60000) as action:
                page.get_by_role("button", name="Download unchanged original", exact=True).click()
            download = action.value
            path = download.path()
            if path is None:
                raise AssertionError("Download did not yield an original file.")
            size = 0
            digest = sha256()
            with Path(path).open("rb") as stream:
                while chunk := stream.read(256 * 1024):
                    size += len(chunk)
                    if size > MAX_ORIGINAL:
                        raise AssertionError("Downloaded original exceeded the fixture limit.")
                    digest.update(chunk)
            if digest.hexdigest() != original_hash or not 1 <= size <= MAX_ORIGINAL:
                raise AssertionError("The downloaded original bytes do not match the known hash.")
            if rejected or errors:
                raise AssertionError("Browser blocked external requests or raised a script error.")
        finally:
            browser.close()
    return {
        "schema": 1, "kind": KIND, "phase": phase, "endpoint": ORIGIN,
        "fixture_id": fixture_id, "original_sha256": original_hash,
        "original_size": size, "served_commit": served_commit,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "read_only_checks": [
            "exact_served_commit", "selected_original_identity", "original_download_sha256",
        ],
    }


def _save_new(path: Path, report: dict) -> None:
    """Do not overwrite an earlier acceptance receipt, even by mistake."""
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    verify = sub.add_parser("verify", help="One hash-only browser check on the exact served build")
    verify.add_argument("--fixture-id", required=True)
    verify.add_argument("--original-sha256", required=True)
    verify.add_argument("--expected-commit", required=True)
    verify.add_argument("--phase", choices=("before", "after"), required=True)
    verify.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("compare", help="Validate distinct before/after served-build receipts")
    check.add_argument("--before", type=Path, required=True)
    check.add_argument("--after", type=Path, required=True)
    check.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "verify":
        report = verify_one(args.fixture_id, args.original_sha256,
                            args.expected_commit, args.phase)
        _validate_manifest(report, args.phase)
    else:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        report = compare(before, after)
    _save_new(args.output, report)
    print(json.dumps({
        "accepted": True, "kind": report["kind"], "fixture_id": report["fixture_id"],
        "original_sha256": report["original_sha256"],
        "bytes": report["original_size"], "output": str(args.output),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
