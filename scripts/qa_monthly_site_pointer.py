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
from qa_fresh_native_error_checks import capture_native_window_errors, require_no_native_window_errors
from qa_workflow_route_observations import WorkflowRouteObservations, workflow_route

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "monthly-first-site"
BASE_URL = "http://127.0.0.1:8526/?workflow=monthly"
CONTRACT = "Rochester Regional Health"
FIRST = "United Memorial Medical Center"
SECOND = "Rochester General Hospital"
results = {"synthetic_isolated_storage": True, "actual_user_pointer": True,
           "physical_device": False, "touch_emulated": True, "checks": [], "failures": []}


def visit(browser, engine, method):
    touch = method == "touch"
    context = browser.new_context(viewport={"width": 390 if touch else 1365, "height": 844 if touch else 900},
                                  has_touch=touch)
    page = context.new_page()
    events, browser_errors = [], []
    page.on("pageerror", lambda error: browser_errors.append(str(error)[:1000]))
    page.add_init_script((ROOT / "scripts/qa_fresh_native_errors.js").read_text().replace(
        'http://127.0.0.1:8529', 'http://127.0.0.1:8526'))
    wire = WorkflowRouteObservations()
    wire.attach(page)
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
        record["phase"] = "choose fresh contract"
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.get_by_role("button", name=CONTRACT, exact=True).click()
        record["phase"] = "verify zero-selection baseline"
        box = page.get_by_role("checkbox", name=FIRST, exact=True)
        label = box.locator("xpath=ancestor::label[1]")
        label.scroll_into_view_if_needed()
        expect(box).not_to_be_checked()
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible()
        # Capture a small DOM/hit-test receipt BEFORE the one native action.
        record["before"] = box.evaluate("""node => {
            const label=node.closest('label'), rect=label.getBoundingClientRect();
            const row=node.closest('[data-testid="stCheckbox"]'), rowRect=row?.getBoundingClientRect();
            const hit=document.elementFromPoint(rect.left+Math.min(18,rect.width/2),rect.top+rect.height/2);
            const rowEndHit=rowRect&&document.elementFromPoint(rowRect.right-24,rowRect.top+rowRect.height/2);
            return {checked:node.checked,disabled:node.disabled,control:node.getBoundingClientRect().toJSON(),
                label:rect.toJSON(),row:rowRect?.toJSON(),squareHitOwned:!!hit&&label.contains(hit),
                rowEndHitTag:rowEndHit?.tagName,rowEndHitOwned:!!rowEndHit&&label.contains(rowEndHit),
                scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')};
        }""")
        record["phase"] = "single native " + method + " activation"
        if method == "square":
            r = label.bounding_box()
            label.click(position={"x": min(18, r["width"] / 3), "y": r["height"] / 2})
        elif method == "text":
            label.get_by_text(FIRST, exact=True).click()
        elif method == "row":
            geom = record["before"]
            # The native row is materially wider than the text label. Prove
            # the right-hand row surface itself hits its owning semantic label.
            # Earlier tests only hit the narrow label's trailing 12 pixels.
            assert geom["row"] and geom["label"]["width"] >= 340, geom
            assert geom["label"]["right"] >= geom["row"]["right"] - 32, geom
            assert geom["rowEndHitOwned"], geom
            r = geom["row"]
            page.mouse.click(r["right"] - 24, r["top"] + r["height"] / 2)
        elif method == "touch":
            label.tap()
        elif method == "keyboard":
            box.focus()
            box.press("Space")
        else:
            raise AssertionError("Unknown input mode")
        record["phase"] = "verify one native site selected and work enabled"
        expect(box).to_be_checked(timeout=45000)
        expect(page.get_by_text("Sites selected (1): " + FIRST, exact=True)).to_be_visible(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_have_count(0)
        expect(page.get_by_text("Starting report", exact=True)).to_be_visible(timeout=45000)
        record["phase"] = "second site and return to zero"
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
        record["phase"] = "reload zero-site result with normal contract re-entry"
        capture_native_window_errors(page, record, "before-reload")
        page.reload(wait_until="domcontentloaded")
        # Before a draft has actually been created, a clean report has not
        # saved its contract. A normal reload may rightly return to the
        # contract selector. Use the ordinary user click to reach the same
        # selector; do not pretend an absent checkbox is a selection failure.
        # A fresh zero-site report does not persist the contract yet. Reload
        # legitimately returns to the contract cards; await that real page
        # before the one ordinary contract click used to resume navigation.
        contract_card = page.get_by_role("button", name=CONTRACT, exact=True)
        expect(contract_card).to_be_visible(timeout=15000)
        contract_card.click()
        expect(page.get_by_text("Sites in this report", exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role("checkbox", name=FIRST, exact=True)).not_to_be_checked(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible(timeout=45000)
        capture_native_window_errors(page, record, "final")
        require_no_native_window_errors(record.get("native_window_errors"), origin="http://127.0.0.1:8526")
        assert not browser_errors, {"browser_errors": browser_errors}
        if events:
            raise AssertionError("A synthetic browser requested an external URL")
        record["result"] = "pass"
        results["checks"].append(record)
    except Exception as exc:
        # Save screenshot BEFORE any further locator could fail (the checked
        # element may have moved, e.g. after reload). Keep the first failure.
        try:
            page.screenshot(path=str(OUT / f"{engine}-{method}-first-failure.png"))
        except Exception:
            pass
        record["result"] = "fail"
        record["error_type"] = type(exc).__name__
        record["message"] = str(exc)[:1000]
        record["workflow_route_after"] = workflow_route(page.url)
        if not record.get("native_window_errors") or record["native_window_errors"][-1].get("stage") != "final":
            capture_native_window_errors(page, record, "final")
        try:
            record["workflow_controls_after"] = page.locator('.st-key-workflow_mode').evaluate(
                "node => Array.from(node.querySelectorAll('[role=radio]')).map(r => "
                "({label:r.textContent.trim(),selected:r.getAttribute('aria-checked')}))")
        except Exception:
            pass
        try:
            record["after"] = page.get_by_role("checkbox", name=FIRST, exact=True).evaluate(
                "node => ({checked:node.checked,disabled:node.disabled})")
        except Exception:
            pass
        results["failures"].append(record)
    finally:
        record["workflow_wire"] = wire.snapshot()
        record["browser_errors"] = browser_errors
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
                            for mode in ("square", "text", "row", "keyboard", "touch"):
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
    print("PASS ten genuinely fresh zero-site mouse/keyboard/emulated-touch journeys; no QA prefill")


if __name__ == "__main__":
    main()
