"""Synthetic, keyboard-only PO/expense completion and receipt-byte boundary.

No browser mouse actions, active network reads, submission, or production data.
The size probe uses a file-input API; keyboard journeys use Tab/Space/Enter.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse

import pymupdf as fitz
from dotenv import dotenv_values
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "review-keyboard-u14"
MIB = 1024 * 1024
RESULTS: dict[str, object] = {"synthetic_only": True, "checks": [], "failures": []}


def record(name: str) -> None:
    RESULTS["checks"].append(name)


@contextmanager
def served(fixture: str, prefix: str, port: int):
    with tempfile.TemporaryDirectory(prefix=prefix) as storage:
        if "expense_app.py" in fixture:
            (Path(storage) / ".synthetic-expense-fixture").write_text("synthetic-only")
        env = dict(os.environ)
        env.update({key: value for key, value in dotenv_values(ROOT / ".env.example").items()
                    if value is not None})
        env.update(EPC_DATA_DIR=storage, ANTHROPIC_API_KEY="test-key-not-used",
                   SMARTSHEET_API_MODE="disabled", PDF_BACKEND="libreoffice")
        with (OUT / f"server-{port}.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", fixture,
                 "--server.address", "127.0.0.1", "--server.port", str(port),
                 "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                url = f"http://127.0.0.1:{port}"
                for attempt in range(240):
                    if process.poll() is not None:
                        raise RuntimeError(f"Synthetic fixture ended: {fixture}")
                    try:
                        with urllib.request.urlopen(url + "/_stcore/health", timeout=1) as reply:
                            if reply.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(0.125)
                else:
                    raise RuntimeError(f"Synthetic fixture not healthy: {fixture}")
                yield url
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def new_page(browser, port: int):
    page = browser.new_page(viewport={"width": 1366, "height": 900}, accept_downloads=True)
    errors = []
    external = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    def route_request(route):
        url = urlparse(route.request.url)
        if url.scheme in {"blob", "data"} or (url.hostname == "127.0.0.1" and url.port == port):
            route.continue_()
        else:
            external.append(url.hostname or url.scheme)
            route.abort()

    page.route("**/*", route_request)
    return page, errors, external


def tab_to(page, target, *, max_tabs=450):
    """Find a native focus target without locator.click/focus or script injection."""
    expect(target).to_be_visible(timeout=45000)
    for index in range(max_tabs):
        if target.evaluate("node => node === document.activeElement || node.contains(document.activeElement)"):
            return index
        page.keyboard.press("Tab")
    raise AssertionError(f"Unreachable by {max_tabs} Tabs: {target}")


def purchase_keyboard(browser, url):
    page, errors, external = new_page(browser, 8528)
    try:
        page.goto(url, wait_until="domcontentloaded")
        generate = page.get_by_role("button", name="Generate both files and Smartsheet link", exact=True)
        expect(generate).to_be_disabled(timeout=60000)
        requester = page.get_by_role("textbox", name="Your name (Requester / Asset Manager) *", exact=True)
        tab_to(page, requester)
        page.keyboard.type("Synthetic Keyboard Reviewer")
        page.keyboard.press("Tab")
        expect(generate).to_be_enabled(timeout=60000)
        tab_to(page, generate)
        page.keyboard.press("Enter")
        expect(page.get_by_text("Synthetic generation count: 1", exact=True)).to_be_visible(timeout=150000)
        # CI renders the handoff more slowly than the default 5 s expect timeout.
        expect(page.get_by_role("link", name=re.compile("Open Smartsheet in a new tab"))).to_have_count(1, timeout=45000)
        assert page.get_by_role("button", name=re.compile(r"^Download ")).count() == 2
        assert not errors and not external, (errors, external)
        page.screenshot(path=str(OUT / "po-keyboard-generated.png"), full_page=True)
        record("PO: Tab reaches requester and generation, Enter generates real PDF package")
    finally:
        if errors or external:
            RESULTS["failures"].append({"journey": "po", "page_errors": errors, "external": external})
        page.close()


def expense_keyboard(browser, url):
    page, errors, external = new_page(browser, 8529)
    try:
        page.goto(url, wait_until="domcontentloaded")
        receipt_amount = page.get_by_role("textbox", name="Reimbursable amount *", exact=True).first
        tab_to(page, receipt_amount)
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.type("24.50")
        page.keyboard.press("Tab")
        confirmation = page.get_by_role("checkbox", name=re.compile(r"^I confirm this generated signature represents me"))
        tab_to(page, confirmation)
        page.keyboard.press("Space")
        expect(confirmation).to_be_checked(timeout=60000)
        generate = page.get_by_role("button", name="Generate expense report and email draft", exact=True)
        expect(generate).to_be_enabled(timeout=60000)
        tab_to(page, generate)
        page.keyboard.press("Enter")
        expect(page.get_by_text("Synthetic expense generation count: 1", exact=True)).to_be_visible(timeout=150000)
        expect(page.get_by_role("button", name="Open approval email in Outlook", exact=True)).to_be_visible(timeout=45000)
        assert not errors and not external, (errors, external)
        page.screenshot(path=str(OUT / "expense-keyboard-generated.png"), full_page=True)
        record("Expense: Tab edits receipt, Space confirms signature, Enter generates Excel/PDF/EML")
    finally:
        if errors or external:
            RESULTS["failures"].append({"journey": "expense", "page_errors": errors, "external": external})
        page.close()


def receipt_limit(browser, url):
    """Check the native 15 MB receipt uploader limit at its exact byte boundary.

    Streamlit's browser check counts a megabyte as 1024 * 1024 bytes only on
    Windows (navigator.platform) and as 1,000,000 bytes elsewhere, so the
    boundary is 15,728,640 bytes on Windows and 15,000,000 bytes on macOS,
    iOS, Android and Linux. The app's own server-side cap (15 MiB) is never
    smaller, so the browser's limit is the one a person meets.
    """
    page, errors, external = new_page(browser, 8529)
    try:
        page.goto(url, wait_until="domcontentloaded")
        uploader = page.locator('input[type="file"]').first
        expect(uploader).to_have_count(1, timeout=45000)
        with fitz.open() as document:
            document.new_page().insert_text((60, 60), "Synthetic receipt byte boundary")
            pdf = document.tobytes()
        unit = 1024 if page.evaluate("() => /^Win/i.test(navigator.platform)") else 1000
        limit = 15 * unit * unit
        RESULTS.setdefault("receipt_limit_bytes", limit)
        for delta, accepted in ((-1, True), (1, False)):
            payload = pdf + (b" " * ((limit + delta) - len(pdf)))
            uploader.set_input_files({"name": f"synthetic-{abs(delta)}-{'under' if accepted else 'over'}.pdf",
                                      "mimeType": "application/pdf", "buffer": payload})
            if accepted:
                expect(page.get_by_text(re.compile(r"3 unique receipts ready for review"))).to_be_visible(timeout=90000)
                record(f"Receipt: native limit minus one byte ({limit - 1:,} bytes) accepted in actual browser uploader")
            else:
                # The native error is produced by Streamlit before the app receives bytes.
                # Streamlit's message, e.g. "File must be 15.0MB or smaller." (no inline
                # (?i): Playwright passes the pattern to JavaScript, which rejects it).
                error = page.get_by_text(re.compile(r"File must be 15(\.0)?\s*MB or smaller", re.IGNORECASE))
                expect(error.first).to_be_visible(timeout=45000)
                expect(page.get_by_text(re.compile(r"3 unique receipts ready for review"))).to_be_visible()
                record(f"Receipt: native limit plus one byte ({limit + 1:,} bytes) rejected with visible native size error")
            page.screenshot(path=str(OUT / ("receipt-under-limit.png" if accepted else "receipt-over-limit.png")), full_page=False)
        assert not errors and not external, (errors, external)
    finally:
        if errors or external:
            RESULTS["failures"].append({"journey": "receipt-limit", "page_errors": errors, "external": external})
        page.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if not (shutil.which("libreoffice") or shutil.which("soffice")):
        raise RuntimeError("Genuine output browser checks need LibreOffice")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                with served("tests/fixtures/workspaces/po_app.py", "po-adaptive-synthetic-u14-", 8528) as url:
                    purchase_keyboard(browser, url)
                with served("tests/fixtures/workspaces/expense_app.py", "expense-adaptive-synthetic-u14-", 8529) as url:
                    expense_keyboard(browser, url)
                    receipt_limit(browser, url)
            finally:
                browser.close()
    except Exception as exc:
        RESULTS["failures"].append({"error": str(exc)[:1200]})
        raise
    finally:
        (OUT / "results.json").write_text(json.dumps(RESULTS, indent=2))


if __name__ == "__main__":
    main()
