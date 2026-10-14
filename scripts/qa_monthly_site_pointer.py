"""Fresh ordinary Monthly first-site pointer acceptance on an isolated local server.

This is the real run_web entry and catalog, not the preselected synthetic QA
fixture. Each action uses native Playwright input once. No client reports,
third-party readers, report generation or standing-data writes are permitted.
Browser emulation is NOT a physical touchscreen or Safari hardware test.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "monthly-first-site"
BASE_URL = "http://127.0.0.1:8526/?workflow=monthly"
CONTRACT = "Rochester Regional Health"
FIRST = "United Memorial Medical Center"
SECOND = "Rochester General Hospital"
results = {"synthetic_isolated_storage": True, "actual_user_pointer": True,
           "physical_device": False, "checks": [], "failures": []}


def visit(browser, engine, method):
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    page = context.new_page()
    events = []
    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in ("blob", "data") or parsed.hostname == "127.0.0.1" and parsed.port == 8526:
            request.continue_()
        else:
            request.abort()
            events.append({"unexpected_external_request": parsed.hostname})
    page.route("**/*", route)
    record = {"engine": engine, "path": method}
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.get_by_role("button", name=CONTRACT, exact=True).click()
        box = page.get_by_role("checkbox", name=FIRST, exact=True)
        label = box.locator("xpath=ancestor::label[1]")
        label.scroll_into_view_if_needed()
        expect(box).not_to_be_checked()
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible()
        # Capture a small DOM/hit-test receipt BEFORE the one native action.
        record["before"] = box.evaluate("""node => {
            const label=node.closest('label'), rect=label.getBoundingClientRect();
            const hit=document.elementFromPoint(rect.left+Math.min(18,rect.width/2),rect.top+rect.height/2);
            return {checked:node.checked,disabled:node.disabled,control:node.getBoundingClientRect().toJSON(),
                label:rect.toJSON(),squareHitOwned:!!hit&&label.contains(hit),
                scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')};
        }""")
        if method == "square":
            r = label.bounding_box()
            label.click(position={"x": min(18, r["width"] / 3), "y": r["height"] / 2})
        elif method == "text":
            label.get_by_text(FIRST, exact=True).click()
        elif method == "row":
            r = label.bounding_box()
            label.click(position={"x": max(1, r["width"] - 12), "y": r["height"] / 2})
        elif method == "keyboard":
            box.focus()
            box.press("Space")
        else:
            raise AssertionError("Unknown input mode")
        expect(box).to_be_checked(timeout=45000)
        expect(page.get_by_text("Sites selected (1): " + FIRST, exact=True)).to_be_visible(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_have_count(0)
        expect(page.get_by_text("Starting report", exact=True)).to_be_visible(timeout=45000)
        # Distinct second site and recovery from zero. These must not silently
        # promote the first failure: it already had an independent assertion.
        second = page.get_by_role("checkbox", name=SECOND, exact=True)
        second_label = second.locator("xpath=ancestor::label[1]")
        second_label.scroll_into_view_if_needed()
        second_label.click()
        expect(second).to_be_checked(timeout=45000)
        expect(box).to_be_checked(timeout=45000)
        box.locator("xpath=ancestor::label[1]").click()
        expect(box).not_to_be_checked(timeout=45000)
        second.locator("xpath=ancestor::label[1]").click()
        expect(second).not_to_be_checked(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible(timeout=45000)
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("checkbox", name=FIRST, exact=True)).not_to_be_checked(timeout=45000)
        record["result"] = "pass"
        if events:
            raise AssertionError("A synthetic browser requested an external URL")
        results["checks"].append(record)
    except Exception as exc:
        record["result"] = "fail"
        record["error_type"] = type(exc).__name__
        record["message"] = str(exc)[:1000]
        try:
            record["after"] = page.get_by_role("checkbox", name=FIRST, exact=True).evaluate(
                "node => ({checked:node.checked,disabled:node.disabled})")
            page.screenshot(path=str(OUT / f"{engine}-{method}-first-failure.png"))
        except Exception:
            pass
        results["failures"].append(record)
    finally:
        context.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="monthly-native-pointer-") as directory:
        env = {**os.environ, "EPC_DATA_DIR": directory, "SMARTSHEET_API_MODE": "disabled",
               "ANTHROPIC_API_KEY": "test-key-not-used"}
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "run_web.py",
                "--server.address", "127.0.0.1", "--server.port", "8526",
                "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for attempt in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Isolated ordinary Monthly server stopped")
                    try:
                        with urlopen("http://127.0.0.1:8526/_stcore/health", timeout=1) as status:
                            if status.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Isolated Monthly server did not start")
                with sync_playwright() as playwright:
                    for name, browser_type in (("chromium", playwright.chromium),
                                               ("playwright-webkit", playwright.webkit)):
                        browser = browser_type.launch(headless=True)
                        try:
                            for mode in ("square", "text", "row", "keyboard"):
                                visit(browser, name, mode)
                        finally:
                            browser.close()
            finally:
                process.terminate()
                process.wait(timeout=15)
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    if results["failures"]:
        raise AssertionError("Fresh ordinary Monthly pointer failure: " +
                             "; ".join(f["engine"] + "/" + f["path"] + ": " +
                                       f["error_type"] for f in results["failures"]))
    print("PASS eight genuine zero-selection native-input journeys; no QA prefill")


if __name__ == "__main__":
    main()
