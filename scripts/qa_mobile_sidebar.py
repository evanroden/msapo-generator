"""Touch/sidebar regression: isolated synthetic workflows and real native hit targets.

Run locally or in CI with Playwright 1.58.0 and Chromium/WebKit installed.
No external requests or real reports; screenshot evidence stays in test-artifacts.
"""
from __future__ import annotations

from contextlib import ExitStack
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
OUT = ROOT / "test-artifacts" / "mobile-sidebar"
PORTS = {"monthly": 8531, "purchase": 8532, "expense": 8533}
FIXTURES = {
    "monthly": "tests/fixtures/workspaces/monthly_app.py",
    "purchase": "tests/fixtures/workspaces/po_app.py",
    "expense": "tests/fixtures/workspaces/expense_app.py",
}
EVIDENCE = {"synthetic_only": True, "breakpoint_css_px": 1024,
            "engines": ["chromium", "webkit"], "checks": [], "failures": [],
            "posture": "Emulated mobile/touch viewports, not physical hardware"}


def check(label, passed, details=None):
    EVIDENCE["checks"].append({"name": label, "passed": bool(passed), "details": details})
    print(("PASS " if passed else "FAIL ") + label, flush=True)
    if not passed:
        raise AssertionError(label + ": " + str(details))


def screenshot(page, label):
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / (label + ".png")), timeout=30000)


def wait_sidebar(page, expanded):
    expect(page.get_by_test_id("stSidebar")).to_have_attribute(
        "aria-expanded", "true" if expanded else "false", timeout=15000)


def settle(page):
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def hit(page, control, label):
    expect(control).to_be_visible(timeout=15000)
    control.scroll_into_view_if_needed()
    settle(page)
    receipt = control.evaluate("""node => {
        const rect = node.getBoundingClientRect();
        const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
        const target = document.elementFromPoint(x, y);
        const sidebar = document.querySelector('[data-testid="stSidebar"]');
        return {point: [x, y], viewport: [innerWidth, innerHeight],
            box: rect.toJSON(), owned: !!target && node.contains(target),
            hit: target ? {tag: target.tagName, testid: target.dataset.testid || '',
                className: typeof target.className === 'string'
                    ? target.className.slice(0, 120) : ''} : null,
            sidebar: sidebar ? {expanded: sidebar.getAttribute('aria-expanded'),
                display: getComputedStyle(sidebar).display,
                pointerEvents: getComputedStyle(sidebar).pointerEvents,
                rect: sidebar.getBoundingClientRect().toJSON()} : null};
    }""")
    check(label, receipt["owned"], receipt)
    return receipt["point"]


def tap(page, xy):
    page.touchscreen.tap(xy[0], xy[1])


def close_after_open(page, label):
    sidebar = page.get_by_test_id("stSidebar")
    opener = page.get_by_test_id("stExpandSidebarButton")
    if sidebar.get_attribute("aria-expanded") == "false":
        expect(opener).to_be_visible()
        opener.click()
    wait_sidebar(page, True)
    screenshot(page, label + "-open")
    administration = sidebar.get_by_test_id("stExpander").filter(
        has=page.get_by_text("Administration", exact=True))
    expect(administration).to_be_visible()
    administration.get_by_text("Administration", exact=True).click()
    links = administration.get_by_role("link")
    expect(links).to_have_count(4)
    for index in range(4):
        expect(links.nth(index)).to_be_visible()
    check(label + " native Administration links remain accessible", True)
    design = sidebar.get_by_test_id("stExpander").filter(has=page.get_by_text("Report design and artwork", exact=True))
    expect(design).to_be_visible()
    hit(page, design.get_by_text("Report design and artwork", exact=True), label + " optional design disclosure hit")
    sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
    wait_sidebar(page, False)
    settle(page)
    screenshot(page, label + "-closed")
    state = page.evaluate("""() => {
        const node = document.querySelector('[data-testid="stSidebar"]');
        const style = getComputedStyle(node);
        return {display: style.display, pointerEvents: style.pointerEvents,
                expanded: node.getAttribute('aria-expanded'),
                rects: node.getClientRects().length};
    }""")
    check(label + " collapsed sidebar is excluded from hit-testing",
          state["display"] == "none" and state["pointerEvents"] == "none"
          and state["rects"] == 0, state)


def local_context(browser, port, width, height, *, cookie=False):
    context = browser.new_context(
        viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
    if cookie:
        context.add_cookies([{"name": "epc_device_id",
                              "value": secrets.token_hex(16),
                              "url": "http://127.0.0.1:" + str(port)}])
    forbidden = []
    def route(request):
        url = urlparse(request.request.url)
        if url.scheme in {"data", "blob"} or (
                url.hostname == "127.0.0.1" and url.port == port):
            request.continue_()
        else:
            forbidden.append(url.scheme + ":" + str(url.hostname))
            request.abort()
    context.route("**/*", route)
    return context, forbidden


def monthly(browser, engine, width, height, *, resize=False):
    label = engine + ("-wide-to-390" if resize else "-" + str(width))
    initial_width = 1280 if resize else width
    context, forbidden = local_context(
        browser, PORTS["monthly"], initial_width, height, cookie=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto("http://127.0.0.1:" + str(PORTS["monthly"]),
                  wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(
            re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(
                timeout=90000)
        page.get_by_role("textbox", name="Activity summary", exact=True).wait_for(
            timeout=60000)
        page.locator(".epc-workspace-row").first.wait_for(timeout=30000)
        sidebar = page.get_by_test_id("stSidebar")
        if resize:
            EVIDENCE.setdefault("initial_sidebar", {})[label] = (
                sidebar.get_attribute("aria-expanded"))
            if sidebar.get_attribute("aria-expanded") == "false":
                page.get_by_test_id("stExpandSidebarButton").click()
            wait_sidebar(page, True)
            screenshot(page, label + "-before-resize")
            page.set_viewport_size({"width": 390, "height": 844})
            width = 390
            height = 844
            wait_sidebar(page, False)
        else:
            settle(page)
            initial_state = sidebar.get_attribute("aria-expanded")
            EVIDENCE.setdefault("initial_sidebar", {})[label] = initial_state
            screenshot(page, label + "-initial")
            if width == 390:
                check(label + " editor starts with sidebar collapsed",
                      initial_state == "false", {"expanded": initial_state})
            else:
                check(label + " tablet editor starts full width",
                      initial_state == "false", {"expanded": initial_state})
        close_after_open(page, label)
        # These native elements must receive events at their own centre; a
        # translated zero-opacity sidebar cannot pass this probe.
        cover = page.locator(".st-key-epc_pair_monthly_cover")
        preview = cover.get_by_role("button", name="View preview", exact=True)
        next_button = page.locator(".epc-section-next").first
        mode = page.locator(".epc-workspace").first.get_attribute("data-epc-mode")
        expect(next_button).to_be_enabled(timeout=15000)
        hit(page, next_button, label + " section Next hit")
        if mode == "compact":
            preview_xy = hit(page, preview, label + " Cover preview hit")
            tap(page, preview_xy)
            back = cover.get_by_role("button", name="Back to editing", exact=True)
            expect(back).to_be_visible(timeout=30000)
            check(label + " first touch opens Cover preview", True)
            screenshot(page, label + "-preview-open")
            back_xy = hit(page, back, label + " Back to editing hit")
            tap(page, back_xy)
            expect(preview).to_be_visible(timeout=15000)
            check(label + " Cover returns to editor on one touch", True)
        else:
            # At 820px a two-column workspace may show its preview directly,
            # and deliberately does not expose the compact-only View preview.
            check(label + " tablet uses its visible side-by-side Cover preview",
                  mode in ("wide", "book") and not preview.is_visible()
                  and cover.locator(".epc-workspace-reference").is_visible(),
                  {"mode": mode})
            expect(cover.get_by_text("About this report", exact=True)).to_have_count(0)
            check(label + " optional design controls stay outside Cover", True)
        next_xy = hit(page, next_button, label + " Next still receives pointer")
        progress_before = page.locator(".epc-section-progress").inner_text()
        tap(page, next_xy)
        expect(page.locator(".epc-section-progress")).not_to_have_text(
            progress_before, timeout=15000)
        check(label + " first touch activates section Next", True)
        check(label + " no browser errors or external requests",
              not errors and not forbidden,
              {"errors": errors, "external": forbidden})
    finally:
        screenshot(page, label + "-final")
        context.close()


def other_workflow(browser, engine, name, width, height):
    label = engine + "-" + str(width) + "-" + name
    port = PORTS[name]
    context, forbidden = local_context(browser, port, width, height)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto("http://127.0.0.1:" + str(port), wait_until="domcontentloaded")
        if name == "purchase":
            page.get_by_role("heading", name="Purchase order", exact=True).wait_for(
                timeout=60000)
            # The label is intentionally hidden by the native segmented
            # control; probe its visible Purchase order radio button instead.
            control = page.locator('.st-key-workflow_mode button[role="radio"]').first
        else:
            page.get_by_role("heading", name="Expense reimbursement",
                             exact=True).wait_for(timeout=60000)
            control = page.locator('[data-testid="stFileUploader"] button').first
        # The same shell must not leave a collapsed sidebar intercepting the
        # first upload/source control in either of the other two workflows.
        sidebar = page.get_by_test_id("stSidebar")
        if sidebar.count() and sidebar.get_attribute("aria-expanded") == "true":
            sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
            wait_sidebar(page, False)
        hit(page, control, label + " first workflow control hit")
        screenshot(page, label + "-first-control")
        check(label + " no browser errors or external requests",
              not errors and not forbidden, {"errors": errors, "external": forbidden})
    finally:
        context.close()


def launch(name, directory):
    port = PORTS[name]
    env = dict(os.environ, EPC_DATA_DIR=str(directory),
               SMARTSHEET_API_MODE="disabled", ANTHROPIC_API_KEY="",
               PDF_BACKEND="libreoffice", PYTHONDONTWRITEBYTECODE="1")
    if name == "monthly":
        env["EPC_MONTHLY_DOM_FIXTURE"] = "1"
        (directory / "monthly-dom-synthetic-only.marker").write_text(
            "synthetic-monthly-dom-v1", encoding="ascii")
    if name == "expense":
        (directory / ".synthetic-expense-fixture").touch()
    logfile = (OUT / (name + "-streamlit.log")).open("w")
    process = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", FIXTURES[name],
        "--server.address", "127.0.0.1", "--server.port", str(port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
    ], cwd=ROOT, env=env, stdout=logfile, stderr=subprocess.STDOUT)
    return process, logfile


def health(process, port):
    end = time.monotonic() + 45
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError("Synthetic app exited during startup: " + str(port))
        try:
            with urlopen("http://127.0.0.1:" + str(port) + "/_stcore/health",
                         timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.2)
    raise TimeoutError("Synthetic app not ready on " + str(port))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        directories = {
            name: Path(stack.enter_context(tempfile.TemporaryDirectory(prefix={
                "monthly": "monthly-dom-synthetic-",
                "purchase": "po-adaptive-synthetic-",
                "expense": "expense-adaptive-synthetic-"}[name])))
            for name in PORTS
        }
        processes = {}
        try:
            for name in PORTS:
                processes[name] = launch(name, directories[name])
            for name, (process, _) in processes.items():
                health(process, PORTS[name])
            with sync_playwright() as playwright:
                for engine in ("chromium", "webkit"):
                    browser = getattr(playwright, engine).launch(headless=True)
                    try:
                        for width, height in ((390, 844), (820, 1180)):
                            for name in ("monthly", "purchase", "expense"):
                                try:
                                    if name == "monthly":
                                        monthly(browser, engine, width, height)
                                    else:
                                        other_workflow(browser, engine, name, width, height)
                                except Exception as exc:
                                    EVIDENCE["failures"].append(
                                        engine + "/" + str(width) + "/" + name + ": "
                                        + type(exc).__name__ + ": " + str(exc)[:600])
                            if width == 390:
                                try:
                                    monthly(browser, engine, width, height, resize=True)
                                except Exception as exc:
                                    EVIDENCE["failures"].append(
                                        engine + "/wide-to-390: " + type(exc).__name__
                                        + ": " + str(exc)[:600])
                    finally:
                        browser.close()
        finally:
            for process, logfile in processes.values():
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                logfile.close()
            EVIDENCE["passed"] = sum(int(c["passed"]) for c in EVIDENCE["checks"])
            EVIDENCE["failed"] = len(EVIDENCE["failures"]) + sum(
                int(not c["passed"]) for c in EVIDENCE["checks"])
            (OUT / "results.json").write_text(
                json.dumps(EVIDENCE, indent=2), encoding="utf-8")
    if EVIDENCE["failures"]:
        raise AssertionError("; ".join(EVIDENCE["failures"]))


if __name__ == "__main__":
    main()
