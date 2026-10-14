"""Actual Prepared-by correction navigation, not a markup-presence assertion.

Uses the guarded existing synthetic Monthly app and disposable cookie scopes.
No real client draft, shared production write or outward action is reachable.
Chromium/WebKit widths are browser emulation, not physical phone acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "monthly-preparer-navigation"
PORT = 8528
URL = f"http://127.0.0.1:{PORT}"
REPORT = {"synthetic_only": True, "physical_device": False, "checks": [], "failures": [],
          "scope": "correction navigation after completed initial fixture mount; not early-startup typing stress"}


READY = """() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'"""


def exercise(browser, engine, width, method):
    context = browser.new_context(viewport={"width": width, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    unexpected, browser_errors = [], []

    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"data", "blob"} or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            unexpected.append(parsed.hostname)
            request.abort()

    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: browser_errors.append(str(error)[:500]))
    from workspace_wire_observations import WireObservations
    wire = WireObservations(PORT)
    wire.attach(page)
    record = {"engine": engine, "width": width, "activation": method}
    label = f"{engine}-{width}-{method}"
    try:
        record["phase"] = "real known-value fixture and completed initial mount"
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
        field = page.get_by_role("textbox", name="Prepared by", exact=True)
        activity = page.get_by_role("textbox", name="Activity summary", exact=True)
        expect(activity).to_be_visible(timeout=60000)
        # Fixture-state and an early textarea can arrive before the initial
        # full form has finished mounting. This is a navigation test, not a
        # race with initial hydration. Wait on its existing completion marker,
        # not a sleep/retry, then perform exactly one clear and native blur.
        page.wait_for_function(READY, timeout=20000)
        expect(field).not_to_have_value("")
        original = activity.input_value()
        assert original, "Initial Activity hydration is a prerequisite, not a blank oracle."
        record["before_clear"] = field.evaluate("""node => {
            window.__preparerEvents=[];
            for(const kind of ['input','change','blur']) node.addEventListener(kind,event=>{
                if(window.__preparerEvents.length<16) window.__preparerEvents.push({
                    kind:event.type,trusted:event.isTrusted,empty:node.value==='',
                    fullRender:document.querySelector('.epc-workspace')?.dataset.epcFullRender});
            });
            return {empty:node.value==='',fullRender:document.querySelector('.epc-workspace')?.dataset.epcFullRender,
                    scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')};
        }""")
        record["phase"] = "one preparer clear and acknowledged completed rerender"
        field.fill("")
        field.press("Tab")
        page.wait_for_function("""before => {
            const stamp=document.querySelector('.epc-workspace')?.dataset.epcFullRender;
            return stamp && stamp!==before && document.querySelector('[data-testid="stApp"]')
                ?.getAttribute('data-test-script-state')==='notRunning';
        }""", arg=record["before_clear"]["fullRender"], timeout=20000)
        # Compact reference panes intentionally start hidden. Count committed
        # DOM captions here, then open the actual pane and require its semantic
        # link to be visible/actionable below. Hidden controls are not a pass.
        links = page.locator('a[href="#report-prepared-by"]')
        expect(links).to_have_count(3, timeout=45000)
        expect(field).to_have_value("")
        organization = page.locator(".st-key-epc_pair_monthly_organization")
        if width < 600:
            organization.get_by_role("button", name="View preview", exact=True).click()
        link = organization.get_by_role("link", name="Enter Prepared by", exact=True)
        link.scroll_into_view_if_needed()
        expect(link).to_be_visible()
        record["phase"] = "one native correction-link activation"
        if method == "pointer":
            link.click()
        else:
            # Focus is test setup only. Native Shift+Tab/Tab proves local tab
            # reachability before native Enter, independently from the mouse.
            link.focus()
            page.keyboard.press("Shift+Tab")
            expect(link).not_to_be_focused()
            page.keyboard.press("Tab")
            expect(link).to_be_focused()
            page.keyboard.press("Enter")
        record["phase"] = "actual input focused and unobscured"
        expect(field).to_be_focused(timeout=5000)
        assert urlparse(page.url).fragment == "report-prepared-by"
        record["target"] = field.evaluate("""node => {
            const r=node.getBoundingClientRect(), h=document.querySelector('[data-testid="stHeader"]')?.getBoundingClientRect();
            const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return {rect:r.toJSON(),headerBottom:h?.bottom||0,focused:document.activeElement===node,
                    centerOwned:hit===node||node.contains(hit),viewportHeight:innerHeight};
        }""")
        target = record["target"]
        assert target["centerOwned"] and target["rect"]["top"] >= target["headerBottom"], target
        assert target["rect"]["bottom"] <= target["viewportHeight"], target
        page.screenshot(path=str(OUT / (label + "-focused.png")))
        # This types into the browser's current focus, not a locator injection.
        page.keyboard.type("Synthetic Navigation Reviewer")
        expect(field).to_have_value("Synthetic Navigation Reviewer")
        page.keyboard.press("Tab")
        expect(links).to_have_count(0, timeout=45000)
        expect(activity).to_have_value(original)
        record["events"] = page.evaluate("window.__preparerEvents||[]")
        record["phase"] = "ordinary reload preserves corrected field and Activity"
        page.reload(wait_until="domcontentloaded")
        expect(field).to_have_value("Synthetic Navigation Reviewer", timeout=45000)
        expect(activity).to_have_value(original, timeout=45000)
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        assert not unexpected
        record["result"] = "pass"
        REPORT["checks"].append(record)
        page.screenshot(path=str(OUT / (label + "-pass.png")))
    except Exception as exc:
        record.update(result="fail", error=type(exc).__name__, message=str(exc)[:2000])
        try:
            record["focus"] = page.evaluate("({tag:document.activeElement?.tagName,label:document.activeElement?.getAttribute('aria-label'),hash:location.hash})")
            record["events"] = page.evaluate("window.__preparerEvents||[]")
            record["after"] = page.evaluate("""() => ({
                preparerEmpty:document.querySelector('input[aria-label="Prepared by"]')?.value==='',
                fullRender:document.querySelector('.epc-workspace')?.dataset.epcFullRender,
                scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
                correctionLinks:document.querySelectorAll('a[href="#report-prepared-by"]').length})""")
            page.screenshot(path=str(OUT / (label + "-first-failure.png")))
        except Exception:
            pass
        REPORT["failures"].append(record)
    finally:
        record["browser_errors"] = browser_errors
        (OUT / (label + "-wire.json")).write_text(json.dumps(wire.snapshot(), indent=2))
        context.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="monthly-preparer-synthetic-") as temp:
        (Path(temp) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", ANTHROPIC_API_KEY="",
                   SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/monthly_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic Monthly navigation server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Synthetic navigation server did not become healthy")
                with sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                        browser = engine.launch(headless=True)
                        try:
                            for width in (1365, 390):
                                for method in ("pointer", "keyboard"):
                                    exercise(browser, name, width, method)
                        finally:
                            browser.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                (OUT / "results.json").write_text(json.dumps(REPORT, indent=2) + "\n")
    if REPORT["failures"]:
        raise AssertionError("Prepared-by native navigation failed: " + json.dumps(REPORT["failures"]))
    print("PASS eight native Prepared-by pointer/keyboard correction and reload journeys")


if __name__ == "__main__":
    main()
