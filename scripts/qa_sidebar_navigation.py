"""Real Streamlit sidebar with app CSS and invented, session-only destinations.

Run in the existing browser-equipped synthetic DOM job. No production app,
contract, authentication, shared storage or report is read or changed. Chromium
and WebKit narrow viewports are emulations, not physical-device acceptance.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "sidebar-navigation"
PORT = 8588
URL = f"http://127.0.0.1:{PORT}"
COLLAPSED_SIDEBAR_RULE = '''    [data-testid="stSidebar"][aria-expanded="false"],
    [data-testid="stSidebar"][aria-expanded="false"] * {
        visibility: hidden;
    }
'''
FIXTURE = '''import streamlit as st
from app.web_ui import CUSTOM_CSS
from scripts.qa_sidebar_navigation import COLLAPSED_SIDEBAR_RULE

st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
css = CUSTOM_CSS
if st.query_params.get("sidebar_focus_baseline") == "1":
    assert css.count(COLLAPSED_SIDEBAR_RULE) == 1
    css = css.replace(COLLAPSED_SIDEBAR_RULE, "")
st.markdown(css, unsafe_allow_html=True)
st.segmented_control("Choose workflow", ("Purchase order", "Expense reimbursement", "Monthly report"),
    default="Monthly report", key="workflow_mode", label_visibility="collapsed",
    width="stretch", required=True)
with st.sidebar:
    with st.expander("Administration"):
        for destination in ("Synthetic branding", "Synthetic master templates"):
            if st.button(destination):
                st.session_state["sidebar_destination"] = destination
        for index in range(4):
            st.link_button(f"Synthetic administration {index + 1}",
                f"http://127.0.0.1:8588/?synthetic_admin={index}", on_click="ignore")
st.title("Synthetic sidebar navigation")
st.write("Destination: " + st.session_state.get("sidebar_destination", "none"))
# A non-Streamlit header must not be revived by a broad visibility override.
st.markdown('<header id="synthetic-preview-toolbar"><button>Hidden preview tool</button></header><footer id="synthetic-footer">Hidden footer</footer>', unsafe_allow_html=True)
'''


def inspect_opener(page):
    """Read only: computed styles, viewport geometry and the actual hit target."""
    return page.get_by_test_id("stExpandSidebarButton").evaluate("""node => {
        const r = node.getBoundingClientRect();
        const hit = document.elementFromPoint(r.x + r.width/2, r.y + r.height/2);
        return {visibility: getComputedStyle(node).visibility,
            display: getComputedStyle(node).display, tag: node.tagName,
            rect: r.toJSON(), ownsHit: !!hit && node.contains(hit),
            hit: hit ? {tag: hit.tagName, testid: hit.getAttribute('data-testid')} : null,
            sidebar: (() => {
                const sidebar = document.querySelector('[data-testid="stSidebar"]');
                return {expanded: sidebar?.getAttribute('aria-expanded'),
                    rect: sidebar?.getBoundingClientRect().toJSON()};
            })(),
            inViewport: r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0 &&
                r.right <= innerWidth && r.bottom <= innerHeight};
    }""")


def actionable_opener(page, record):
    """Keep the hit-test gate, but allow the native sidebar transition to finish.

    The retained 390px failure showed aria-expanded=false before the sidebar
    stopped covering the opener. A trial click waits for ordinary visibility,
    stability and event reception without dispatching a click or changing DOM.
    """
    record["before_actionability"] = inspect_opener(page)
    opener = page.get_by_test_id("stExpandSidebarButton")
    opener.click(trial=True, timeout=5000)
    record["after_actionability"] = state = inspect_opener(page)
    assert state["visibility"] == "visible" and state["inViewport"] and state["ownsHit"], state
    return opener


def require_quiet_chrome(page):
    from playwright.sync_api import expect

    # Later markdown fragments hydrate independently of the page title too.
    for selector in ('[data-testid="stHeader"]', '#synthetic-preview-toolbar', '#synthetic-footer'):
        expect(page.locator(selector)).to_have_count(1, timeout=5000)
    for selector in ('[data-testid="stHeader"]', '[data-testid="stToolbar"]',
                     '#MainMenu', '#synthetic-preview-toolbar', '#synthetic-footer'):
        for node in page.locator(selector).all():
            assert node.evaluate("node => getComputedStyle(node).visibility") == "hidden", selector
    assert not page.get_by_role("button", name="Hidden preview tool").count()


def inspect_workflow_overlap(page):
    """Wait for native radio hydration before measuring actual button geometry.

    Streamlit can show the later title while the segmented-control container
    still has no buttons. Missing or hidden buttons must still fail, rather
    than passing an empty overlap sample.
    """
    from playwright.sync_api import expect

    workflow = page.locator(".st-key-workflow_mode")
    radios = workflow.locator('button[role="radio"]')
    expect(radios).to_have_count(3, timeout=5000)
    for index in range(3):
        expect(radios.nth(index)).to_be_visible(timeout=5000)
    return workflow.evaluate("""node => {
        const opener = document.querySelector('[data-testid="stExpandSidebarButton"]').getBoundingClientRect();
        return [...node.querySelectorAll('button[role="radio"]')].map(button => {
            const r = button.getBoundingClientRect();
            return {label: button.textContent, rect: r.toJSON(), area:
                Math.max(0, Math.min(opener.right,r.right)-Math.max(opener.left,r.left))*
                Math.max(0, Math.min(opener.bottom,r.bottom)-Math.max(opener.top,r.top))};
        });
    }""")


class CollapsedSidebarFocusError(AssertionError):
    """Ordinary Tab reached an off-canvas native sidebar control."""


def tab_to_control(page, control, record, *, key="Tab"):
    """Use real Tab input and reject every collapsed-sidebar focus stop."""
    assert key in ("Tab", "Shift+Tab")
    for _ in range(30):
        page.keyboard.press(key)
        state = page.evaluate("""() => {
            const node = document.activeElement;
            const sidebar = node?.closest('[data-testid="stSidebar"]');
            return {tag: node?.tagName, text: node?.textContent?.trim().slice(0, 100),
                visibility: node ? getComputedStyle(node).visibility : null,
                insideCollapsedSidebar: sidebar?.getAttribute('aria-expanded') === 'false'};
        }""")
        record.append(state)
        if state["insideCollapsedSidebar"]:
            raise CollapsedSidebarFocusError(f"Collapsed sidebar received Tab focus: {state}")
        if control.evaluate("node => document.activeElement === node"):
            return
    raise AssertionError("Native control was unreachable by Tab")


def journey(browser, width, output, record, *, focus_baseline=False):
    from playwright.sync_api import expect

    context = browser.new_context(viewport={"width": width, "height": 900})
    # The fixture never needs an external origin. Fail, rather than silently
    # accepting a navigation that leaves its isolated loopback server.
    external = []
    def local_only(route):
        address = urlparse(route.request.url)
        if address.hostname == "127.0.0.1" and address.port == PORT:
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()
    context.route("**/*", local_only)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(URL + ("?sidebar_focus_baseline=1" if focus_baseline else ""),
                  wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="Synthetic sidebar navigation")).to_be_visible()
        sidebar = page.get_by_test_id("stSidebar")
        opener = page.get_by_test_id("stExpandSidebarButton")
        expect(sidebar).to_have_attribute("aria-expanded", "false")
        opener.wait_for(state="attached")
        expect(opener).to_be_visible()
        record["initial_opener_readiness"] = {}
        opener = actionable_opener(page, record["initial_opener_readiness"])
        record["initial_opener"] = record["initial_opener_readiness"]["after_actionability"]
        assert record["initial_opener"]["visibility"] == "visible"
        assert record["initial_opener"]["tag"] == "BUTTON"
        assert record["initial_opener"]["inViewport"] and record["initial_opener"]["ownsHit"]
        record["workflow_overlap"] = inspect_workflow_overlap(page)
        assert len(record["workflow_overlap"]) == 3
        assert all(row["area"] == 0 for row in record["workflow_overlap"]), record["workflow_overlap"]
        record["main_padding_top"] = page.locator(".block-container").evaluate(
            "node => getComputedStyle(node).paddingTop")
        assert record["main_padding_top"] == ("60px" if width <= 1100 else "20px")
        require_quiet_chrome(page)
        page.screenshot(path=str(output / "collapsed.png"))

        # Ordinary pointer input: open, disclose Administration and choose the
        # two invented destinations. No force click, JS click or DOM mutation.
        opener.click()
        expect(sidebar).to_have_attribute("aria-expanded", "true")
        sidebar.get_by_text("Administration", exact=True).click()
        for name in ("Synthetic branding", "Synthetic master templates"):
            sidebar.get_by_role("button", name=name, exact=True).click()
            expect(page.get_by_text("Destination: " + name, exact=True)).to_be_visible()
        expect(sidebar.get_by_role("link")).to_have_count(4)
        page.screenshot(path=str(output / "expanded.png"))
        record["pointer_destinations"] = ["Synthetic branding", "Synthetic master templates"]

        sidebar.hover()
        sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
        expect(sidebar).to_have_attribute("aria-expanded", "false")
        expect(opener).to_be_visible()
        require_quiet_chrome(page)

        # Being eventually reachable is insufficient: no off-canvas control
        # may intercept Tab on the way to the ordinary visible native opener.
        record["tab_after_pointer_collapse"] = []
        tab_to_control(page, opener, record["tab_after_pointer_collapse"])
        record["reverse_tab_while_collapsed"] = []
        tab_to_control(page, opener, record["reverse_tab_while_collapsed"], key="Shift+Tab")
        page.keyboard.press("Enter")
        expect(sidebar).to_have_attribute("aria-expanded", "true")
        record["keyboard_reopen"] = True
        expect(sidebar.get_by_role("button", name="Synthetic branding", exact=True)).to_be_visible()
        require_quiet_chrome(page)

        # Reproduce keyboard collapse too. Hover exposes Streamlit's native
        # desktop collapse affordance; Tab obtains focus and Enter activates it.
        # No programmatic focus or JS click is used.
        sidebar.hover()
        collapse = sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button")
        record["tab_to_collapse"] = []
        tab_to_control(page, collapse, record["tab_to_collapse"])
        page.keyboard.press("Enter")
        expect(sidebar).to_have_attribute("aria-expanded", "false")
        record["tab_after_keyboard_collapse"] = []
        tab_to_control(page, opener, record["tab_after_keyboard_collapse"])
        page.keyboard.press("Enter")
        expect(sidebar).to_have_attribute("aria-expanded", "true")
        expect(sidebar.get_by_role("link")).to_have_count(4)
        record["keyboard_collapse_without_hidden_stops"] = True

        # Repeat collapse/reopen, then reload. Streamlit may retain the current
        # state; either way, normal collapse must leave a usable opener.
        sidebar.hover()
        sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
        expect(opener).to_be_visible()
        opener.click()
        expect(sidebar).to_have_attribute("aria-expanded", "true")
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="Synthetic sidebar navigation")).to_be_visible()
        expect(sidebar).to_have_attribute("aria-expanded", re.compile("^(true|false)$"))
        record["sidebar_expanded_after_reload"] = sidebar.get_attribute("aria-expanded")
        if record["sidebar_expanded_after_reload"] == "true":
            sidebar.hover()
            sidebar.get_by_test_id("stSidebarCollapseButton").get_by_role("button").click()
        expect(sidebar).to_have_attribute("aria-expanded", "false")
        expect(opener).to_be_visible()
        record["reload_opener"] = {}
        actionable_opener(page, record["reload_opener"]).click()
        expect(sidebar).to_have_attribute("aria-expanded", "true")
        expect(sidebar.get_by_text("Administration", exact=True)).to_be_visible()
        require_quiet_chrome(page)
        assert not errors, errors
        assert not external, external
        record["repeated_navigation_and_reload"] = True
        record["passed"] = True
    finally:
        record["page_errors"] = errors
        record["external_requests"] = external
        page.screenshot(path=str(output / "last-state.png"))
        context.close()


def main():
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {"scope": "synthetic native sidebar and real app CSS only",
                "physical_device": False, "checks": []}
    with tempfile.TemporaryDirectory(prefix="runtime-", dir=OUT) as directory:
        temporary = Path(directory)
        fixture = temporary / "fixture.py"
        fixture.write_text(FIXTURE)
        env = {**os.environ, "PYTHONPATH": str(ROOT), "EPC_DATA_DIR": str(temporary / "data"),
               "ANTHROPIC_API_KEY": "test-key-not-used"}
        with (OUT / "server.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(fixture),
                "--server.address=127.0.0.1", f"--server.port={PORT}",
                "--browser.gatherUsageStats=false"], cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("Synthetic Streamlit server exited before readiness")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise TimeoutError("Synthetic Streamlit server did not become ready")
                with sync_playwright() as playwright:
                    for name in ("chromium", "webkit"):
                        browser = getattr(playwright, name).launch(headless=True)
                        try:
                            if name == "chromium":
                                # Same native fixture with only the new closed-
                                # subtree rule removed must expose the original
                                # defect, not pass a vacuous focus assertion.
                                output = OUT / "chromium-390-focus-baseline"
                                output.mkdir(exist_ok=True)
                                baseline = {"browser": name, "width": 390, "rejected": False}
                                evidence["collapsed_focus_baseline"] = baseline
                                try:
                                    journey(browser, 390, output, baseline, focus_baseline=True)
                                except CollapsedSidebarFocusError as error:
                                    baseline["expected_failure"] = str(error)
                                    baseline["rejected"] = True
                                else:
                                    raise AssertionError("Unfixed native sidebar did not expose hidden focus stops")
                                assert not baseline["page_errors"] and not baseline["external_requests"], baseline
                            for width in (1365, 1024, 390):
                                output = OUT / f"{name}-{width}"
                                output.mkdir(exist_ok=True)
                                record = {"browser": name, "width": width, "passed": False}
                                evidence["checks"].append(record)
                                journey(browser, width, output, record)
                        finally:
                            browser.close()
            except Exception as error:
                evidence["failure"] = str(error)
                raise
            finally:
                server.terminate()
                server.wait(timeout=15)
                (OUT / "evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
