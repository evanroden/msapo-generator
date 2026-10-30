"""Native issue-page choices through the existing isolated Monthly QA route.

Real source uploads, issue controls and reload; no injected draft/session state,
replacement save handler, live service, private source or paid reader.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

import pymupdf
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ALPHA = "synthetic-alpha-equipment.pdf"
BETA = "synthetic-beta-equipment.pdf"
ISSUES = ".st-key-epc_pair_monthly_issues"


def source_pdf(label, pages):
    with pymupdf.open() as document:
        for number in range(1, pages + 1):
            page = document.new_page()
            page.insert_text((45, 65), "TEST ONLY - ALL RECORDS INVENTED")
            page.insert_text((45, 100), f"Synthetic {label} equipment inspection page {number}.")
            page.insert_text((45, 135), "September 2026; Demo North; follow-up remains open.")
        return document.tobytes()


def choose(page, control, value):
    control.click()
    page.get_by_role("option", name=value, exact=True).click()


def open_gallery(issue):
    evidence = issue.get_by_text("Evidence", exact=True)
    if evidence.locator("xpath=ancestor::details[1]").get_attribute("open") is None:
        evidence.click()
    summary = issue.get_by_text("Choose supporting pages by preview", exact=True)
    details = summary.locator("xpath=ancestor::details[1]")
    if details.get_attribute("open") is None:
        summary.click()
    expect(issue.get_by_role("combobox", name="Source file to inspect", exact=True)).to_be_visible()


def checkbox(issue, filename, number):
    return issue.get_by_role("checkbox", name=f"Include {filename} · page {number} as issue evidence", exact=True)


def tags(issue):
    # Read the existing canonical multiselect, not the gallery's UI mirrors.
    selected = issue.get_by_test_id("stMultiSelect").filter(has_text="Supporting source pages")
    return selected.locator("[data-tag]").all_text_contents()


def assert_tags(issue, expected):
    selected = issue.get_by_test_id("stMultiSelect").filter(has_text="Supporting source pages")
    expect(selected.locator("[data-tag]")).to_have_text(expected)


def browser_task(browser_type, name):
    from scripts import qa_monthly_adaptive as qa
    options = {"headless": True}
    if name == "playwright-webkit" and os.environ.get("EPC_QA_WEBKIT_EXECUTABLE"):
        options["executable_path"] = os.environ["EPC_QA_WEBKIT_EXECUTABLE"]
    browser = browser_type.launch(**options)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": qa.URL}])
    external, errors = [], []

    def route(request):
        address = urlparse(request.request.url)
        if address.scheme in {"data", "blob"} or (address.hostname == "127.0.0.1" and address.port == urlparse(qa.URL).port):
            request.continue_()
        else:
            external.append(address.hostname)
            request.abort()

    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(30000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    output = qa.OUT / name
    output.mkdir(parents=True, exist_ok=True)
    alpha, beta = source_pdf("alpha", 5), source_pdf("beta", 2)
    record = {"synthetic_only": True, "actual_route": "Monthly QA prefill, native file upload and issue editor",
              "inputs": {ALPHA: sha256(alpha).hexdigest(), BETA: sha256(beta).hexdigest()},
              "steps": [], "external": external, "errors": errors,
              "limits": ["No physical-device or production acceptance", "This journey does not approve or embed evidence pages"]}
    try:
        page.goto(qa.URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
        expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_be_visible(timeout=45000)
        opener = page.get_by_role("button", name="Manage source files", exact=True)
        if opener.count():
            opener.click()
        upload = page.get_by_test_id("stFileUploader").filter(has_text="Add source files")
        upload.locator('input[type="file"]').set_input_files([
            {"name": ALPHA, "mimeType": "application/pdf", "buffer": alpha},
            {"name": BETA, "mimeType": "application/pdf", "buffer": beta},
        ])
        expect(page.get_by_role("combobox", name="File to review", exact=True)).to_be_visible(timeout=45000)
        page.get_by_role("button", name="Done with source files", exact=True).click()
        issue = page.locator(ISSUES)
        qa.scroll_pair(page, ISSUES)
        open_gallery(issue)
        assert_tags(issue, [])

        # One visible-label pointer gesture; no force-click or second attempt.
        qa.set_checkbox(issue, f"Include {ALPHA} · page 1 as issue evidence", True, name)
        assert_tags(issue, [f"{ALPHA} · page 1"])
        # The semantic input is visually hidden but keyboard-focusable. Space
        # must deliver exactly one change to the same canonical multiselect.
        second = checkbox(issue, ALPHA, 2)
        second.focus()
        second.press("Space")
        expect(second).to_be_checked()
        assert_tags(issue, [f"{ALPHA} · page 1", f"{ALPHA} · page 2"])
        record["steps"].append({"stage": "pointer-and-keyboard", "selected": tags(issue)})

        choose(page, issue.get_by_role("combobox", name="Source file to inspect", exact=True), BETA)
        expect(checkbox(issue, BETA, 1)).not_to_be_checked()
        qa.set_checkbox(issue, f"Include {BETA} · page 1 as issue evidence", True, name)
        assert_tags(issue, [f"{ALPHA} · page 1", f"{ALPHA} · page 2", f"{BETA} · page 1"])
        choose(page, issue.get_by_role("combobox", name="Source file to inspect", exact=True), ALPHA)
        qa.set_checkbox(issue, f"Include {ALPHA} · page 1 as issue evidence", False, name)
        assert_tags(issue, [f"{ALPHA} · page 2", f"{BETA} · page 1"])
        choose(page, issue.get_by_role("combobox", name="Pages to review", exact=True), "Pages 5–5 of 5")
        qa.set_checkbox(issue, f"Include {ALPHA} · page 5 as issue evidence", True, name)
        expected = [f"{ALPHA} · page 2", f"{ALPHA} · page 5", f"{BETA} · page 1"]
        assert_tags(issue, expected)
        issue.get_by_role("button", name=f"Preview {ALPHA} · page 5", exact=True).click()
        expect(issue.get_by_text(f"{ALPHA} · page 5 · Preview only; original and issue links are unchanged.", exact=True)).to_be_visible()
        expect(issue.get_by_test_id("stImage").locator("img")).to_be_visible()
        record["steps"].append({"stage": "file-identity-page-five-preview", "selected": tags(issue)})

        # Use the actual shared-history action, not a fixture save wrapper.
        history = page.get_by_test_id("stExpander").filter(
            has=page.locator("summary").get_by_text("Shared report history", exact=True))
        history.locator("summary").click()
        expect(history.get_by_role("button", name="Save shared version", exact=True)).to_be_enabled()
        history.get_by_role("button", name="Save shared version", exact=True).click()
        expect(history.get_by_role("table", name="Saved report versions").get_by_role("row")).to_have_count(3)
        record["steps"].append({"stage": "shared-version-two-saved", "selected": tags(issue)})

        # Reload the real product session; its existing snapshot/recovery path
        # must restore the exact selected associations, without test injection.
        page.reload(wait_until="domcontentloaded")
        issue = page.locator(ISSUES)
        assert_tags(issue, expected)
        qa.scroll_pair(page, ISSUES)
        open_gallery(issue)
        expect(checkbox(issue, ALPHA, 1)).not_to_be_checked()
        expect(checkbox(issue, ALPHA, 2)).to_be_checked()
        page.set_viewport_size({"width": 545, "height": 757})
        choose(page, issue.get_by_role("combobox", name="Source file to inspect", exact=True), BETA)
        expect(checkbox(issue, BETA, 1)).to_be_checked()
        expect(checkbox(issue, BETA, 2)).not_to_be_checked()
        assert_tags(issue, expected)
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2")
        record["steps"].append({"stage": "durable-reload-narrow", "selected": tags(issue)})
        page.screenshot(path=str(output / "reloaded-narrow.png"))
        assert not external and not errors
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        record["result"] = "passed"
        qa.check(name, "Issue page native pointer/Space/file distinction/preview/reload", True)
    except Exception as exc:
        record["result"] = "failed"
        record["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            page.screenshot(path=str(output / "first-failure.png"))
        except Exception as screenshot_error:
            record["screenshot_error"] = str(screenshot_error)[:300]
        raise
    finally:
        (output / "journey.json").write_text(json.dumps(record, indent=2) + "\n")
        context.close()
        browser.close()


def main():
    from scripts import qa_monthly_adaptive as qa
    # An independently allocated loopback port prevents a concurrent QA run
    # from being mistaken for this worktree's server. Keep every attempt.
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        port = port_probe.getsockname()[1]
    qa.URL = f"http://127.0.0.1:{port}"
    qa.OUT = ROOT / "test-artifacts" / "issue-page-gallery" / secrets.token_hex(6)
    qa.OUT.mkdir(parents=True)
    qa.REPORT = {"synthetic_only": True, "physical_device": False, "browsers": {}, "checks": []}
    failures = []
    completed = False
    with tempfile.TemporaryDirectory(prefix="monthly-dom-synthetic-") as temp:
        (Path(temp) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1",
                   ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        with (qa.OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/monthly_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(port), "--server.headless", "true",
                "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Own isolated Monthly fixture stopped during startup")
                    try:
                        with urllib.request.urlopen(qa.URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Own isolated Monthly fixture did not become ready")
                with sync_playwright() as playwright:
                    for browser_type, name in ((playwright.chromium, "chromium"),
                                               (playwright.webkit, "playwright-webkit")):
                        try:
                            browser_task(browser_type, name)
                        except Exception as exc:
                            failures.append({"browser": name, "type": type(exc).__name__, "message": str(exc)[:2000]})
                completed = True
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                qa.REPORT["failures"] = failures
                qa.REPORT["result"] = "passed" if completed and not failures else "failed"
                (qa.OUT / "results.json").write_text(json.dumps(qa.REPORT, indent=2) + "\n")
    if failures:
        raise AssertionError("Native issue gallery failures: " + json.dumps(failures))


if __name__ == "__main__":
    main()
