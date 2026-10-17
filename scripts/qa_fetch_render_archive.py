"""Retrieve a stored Render QA archive from its existing no-login test interface.

Run from any machine with Python + Playwright, including non-ChatGPT agents.
This never uploads, extracts, edits or logs source contents. It downloads only
the selected archive, verifies every downloaded byte against an independently
provided checksum/length, and creates the output without overwriting files.
The Render service version is observed before and after the download.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from scripts import qa_render_archive_redeploy_readonly as audit

_CAPTION = re.compile(
    r"^(?:Six originals|\d+ evidence artifacts) · ([\d,]+) ZIP bytes · "
    r"SHA-256: ([0-9a-f]{64})$")
_CHUNK = 256 * 1024
_EMPTY = {
    "originals": "No external-agent source archive is stored on Render yet.",
    "synthetic": "No synthetic evidence ZIP is stored on Render yet.",
}


def _read_caption(text: str):
    match = _CAPTION.fullmatch(text.strip())
    return (int(match[1].replace(",", "")), match[2]) if match else None


def _prefixes(options, kind: str):
    prefix = audit.SHELVES[kind]["option"]
    pattern = re.compile("^" + re.escape(prefix) + r"([0-9a-f]{12})$")
    return tuple(dict.fromkeys(
        match[1] for value in options
        if isinstance(value, str) and (match := pattern.fullmatch(value.strip()))
    ))


def _served_commit(page):
    """Observe Streamlit's actual running-code marker, not GitHub's latest SHA."""
    from playwright.sync_api import expect

    page.goto(audit.ORIGIN + audit.BUILD_ROUTE, wait_until="domcontentloaded", timeout=65000)
    from scripts.qa_public_build import running_code_marker
    marker = running_code_marker(page, timeout=45000)
    expect(marker).to_be_visible(timeout=45000)
    value = (marker.text_content() or "").strip()
    commit = value.removeprefix("Running code: ")
    if not audit.COMMIT.fullmatch(commit):
        raise AssertionError("The served code marker is unavailable or invalid.")
    return commit


def _write_verified(download: Path, destination: Path, *, digest: str, size: int,
                    max_size: int) -> None:
    """No overwrite or completed-path claim until the entire archive verifies."""
    if destination.suffix.casefold() != ".zip":
        raise ValueError("Choose a .zip output path.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(destination, flags, 0o600)
    complete = False
    try:
        checked, hasher = 0, sha256()
        with os.fdopen(fd, "wb") as output, download.open("rb") as source:
            while chunk := source.read(_CHUNK):
                checked += len(chunk)
                if checked > max_size:
                    raise ValueError("The downloaded archive exceeded the shelf limit.")
                output.write(chunk)
                hasher.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if checked != size or hasher.hexdigest() != digest:
            raise ValueError("Downloaded bytes differ from the independently expected archive.")
        complete = True
    finally:
        if not complete:
            destination.unlink(missing_ok=True)


def _select_expected(page, *, kind: str, expected_sha: str, expected_size: int,
                     requested_prefix: str | None):
    from playwright.sync_api import expect

    settings = audit.SHELVES[kind]
    page.get_by_text(settings["expander"], exact=True).click()
    if page.get_by_text(_EMPTY[kind], exact=True).count():
        raise FileNotFoundError("The Render " + kind + " shelf is empty. The owner upload is still required.")
    select = page.get_by_role("combobox", name=settings["selection"], exact=True)
    expect(select).to_be_visible(timeout=45000)
    select.click()
    prefixes = _prefixes(page.get_by_role("option").all_text_contents(), kind)
    if requested_prefix:
        requested_prefix = requested_prefix[:12]
        prefixes = tuple(p for p in prefixes if p == requested_prefix)
    if not prefixes:
        raise FileNotFoundError("No matching stored archive is listed in the Render " + kind + " shelf.")
    for index, prefix in enumerate(prefixes):
        if index:
            select.click()
        page.get_by_role("option", name=settings["option"] + prefix, exact=True).click()
        page.wait_for_function(
            """() => document.querySelector('[data-testid="stApp"]')
              ?.getAttribute('data-test-script-state') === 'notRunning'""",
            timeout=45000,
        )
        captions = page.get_by_text(re.compile(r"ZIP bytes · SHA-256: [0-9a-f]{64}$")).all_text_contents()
        if (expected_size, expected_sha) in filter(None, map(_read_caption, captions)):
            return prefix
    raise FileNotFoundError("No stored Render archive matches the independently expected size and checksum.")


def fetch_archive(*, kind: str, expected_sha: str, expected_size: int,
                  destination: Path, requested_prefix: str | None = None) -> dict:
    # Invalid caller identity must fail without requiring browser dependencies,
    # touching disk or making any external request.
    audit._valid_inputs(
        kind, requested_prefix or "0" * 12, expected_sha, expected_size,
        "0" * 40, "before",
    )
    if requested_prefix and not (
        audit.ID.fullmatch(requested_prefix) or audit.ID_PREFIX.fullmatch(requested_prefix)
    ):
        raise ValueError("Use a 12-hex archive prefix or full 32-hex ID.")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("The output already exists and must not be overwritten.")
    from playwright.sync_api import sync_playwright, expect

    settings = audit.SHELVES[kind]
    refused, errors = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True
            )
            context.route("**/*", lambda route: audit._browser_route(route, refused))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.set_default_timeout(25000)
            served = _served_commit(page)
            page.goto(audit.ORIGIN + audit.SHELF_ROUTE,
                      wait_until="domcontentloaded", timeout=65000)
            expect(page.get_by_role("heading", name="Shared report testing", exact=True)
                   ).to_be_visible(timeout=60000)
            prefix = _select_expected(
                page, kind=kind, expected_sha=expected_sha,
                expected_size=expected_size, requested_prefix=requested_prefix
            )
            page.get_by_role("button", name=settings["prepare"], exact=True).click()
            expect(page.get_by_role("button", name=settings["download"], exact=True)
                   ).to_be_visible(timeout=90000)
            classes = page.locator(
                '[class*="st-key-' + settings["key_prefix"] + '"]'
            ).evaluate_all(
                "(nodes) => nodes.map(n => n.className)"
                '.filter(v => typeof v === "string")'
            )
            full_id = audit._native_archive_id(
                classes, settings["key_prefix"], prefix, expected_sha
            )
            if requested_prefix and len(requested_prefix) == 32 and full_id != requested_prefix:
                raise AssertionError("Full requested archive ID differs from the download action.")
            expect(page.locator(
                ".st-key-" + settings["key_prefix"] + full_id + "_" + expected_sha[:16]
            )).to_be_visible(timeout=45000)
            with page.expect_download(timeout=240000) as action:
                page.get_by_role("button", name=settings["download"], exact=True).click()
            source = action.value.path()
            if source is None:
                raise OSError("The Render source download did not finish.")
            if _served_commit(page) != served:
                raise AssertionError("Render changed served revisions during the download.")
            if refused or errors:
                raise AssertionError("Unexpected network request or browser script error.")
            _write_verified(
                Path(source), destination, digest=expected_sha,
                size=expected_size, max_size=settings["max_size"]
            )
        finally:
            browser.close()
    return {
        "schema": 1, "kind": "enfra-external-render-archive-fetch-v1",
        "archive_kind": kind, "bundle_id": full_id,
        "archive_sha256": expected_sha, "archive_size": expected_size,
        "served_commit": served, "endpoint": audit.ORIGIN,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "destination": str(destination),
        "note": "Exact downloaded bytes verified; not a report import or design acceptance.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-kind", choices=tuple(audit.SHELVES), required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--archive-size", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle-prefix",
                        help="Optional displayed 12-hex prefix or full 32-hex ID")
    args = parser.parse_args(argv)
    receipt = fetch_archive(
        kind=args.archive_kind, expected_sha=args.archive_sha256,
        expected_size=args.archive_size, destination=args.output,
        requested_prefix=args.bundle_prefix
    )
    # Report metadata only. ZIP bytes are never written into logs or artifacts.
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
