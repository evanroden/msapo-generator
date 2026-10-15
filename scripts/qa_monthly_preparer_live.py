"""Exact-served Prepared-by navigation with fresh isolated synthetic reports.

Run sequentially after the existing two-session live gate. Uses its unchanged
build, fixture-generation and reset receipts; never opens ordinary client data.
No owner archive, standing write, paid reader, email or financial action occurs.
"""
from __future__ import annotations

import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright
from scripts import qa_monthly_live as live


def assert_isolated_route(page):
    query = parse_qs(urlparse(page.url).query)
    if query.get("workflow") != ["monthly"] or query.get("monthly_qa") != ["isolated"]:
        raise AssertionError("Synthetic navigation left its authorized isolated route.")


def exercise(browser, method):
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": live.URL}])
    page = context.new_page()
    page.set_default_timeout(20000)
    try:
        observed = live.open_until_matching(page)
        assert_isolated_route(page)
        live.checkpoint(method + " exact served revision", observed == "Running code: " + live.EXPECTED)
        expect(page.get_by_text("ISOLATED SYNTHETIC TESTING — not a client report", exact=False)).to_be_visible()
        empty = live.await_fixture_state(page, "empty")
        state = live.load_fixture(page, "prefill", previous_generation=empty["generation"])
        field = page.get_by_role("textbox", name="Prepared by", exact=True)
        activity = page.get_by_role("textbox", name="Activity summary", exact=True)
        expect(activity).to_be_visible(timeout=60000)
        page.wait_for_function("""() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
            document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'""",
            timeout=20000)
        expect(field).not_to_have_value("")
        original = activity.input_value()
        assert original
        field.fill("")
        field.press("Tab")
        links = page.locator('a[href="#report-prepared-by"]')
        expect(links).to_have_count(3, timeout=45000)
        expect(field).to_have_value("")
        link = page.locator('.st-key-epc_pair_monthly_organization').get_by_role(
            'link', name='Enter Prepared by', exact=True)
        link.scroll_into_view_if_needed()
        expect(link).to_be_visible()
        if method == "pointer":
            link.click()
        else:
            link.focus()
            page.keyboard.press("Shift+Tab")
            expect(link).not_to_be_focused()
            page.keyboard.press("Tab")
            expect(link).to_be_focused()
            page.keyboard.press("Enter")
        expect(field).to_be_focused(timeout=5000)
        assert_isolated_route(page)
        assert urlparse(page.url).fragment == "report-prepared-by"
        target = field.evaluate("""node => {
            const r=node.getBoundingClientRect(), h=document.querySelector('[data-testid="stHeader"]')?.getBoundingClientRect();
            const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return {rect:r.toJSON(),headerBottom:h?.bottom||0,focused:document.activeElement===node,
                centerOwned:hit===node||node.contains(hit),viewportHeight:innerHeight};
        }""")
        live.checkpoint(method + " visible native prerequisite focused",
            target["focused"] and target["centerOwned"] and target["rect"]["top"] >= target["headerBottom"]
            and target["rect"]["bottom"] <= target["viewportHeight"], json.dumps(target))
        live.screenshot(page, method + "-prepared-field-focused")
        page.keyboard.type("Synthetic Live Navigation Reviewer")
        page.keyboard.press("Tab")
        expect(links).to_have_count(0, timeout=45000)
        expect(field).to_have_value("Synthetic Live Navigation Reviewer")
        expect(activity).to_have_value(original)
        page.reload(wait_until="domcontentloaded")
        expect(field).to_have_value("Synthetic Live Navigation Reviewer", timeout=45000)
        expect(activity).to_have_value(original, timeout=45000)
        assert_isolated_route(page)
        expect(page.get_by_text("Running code: " + live.EXPECTED, exact=True)).to_be_visible()
        live.checkpoint(method + " corrected name and Activity survive reload", True)
        live.reset_fixture(page, state, "preparer-" + method)
    except Exception as exc:
        live.event("preparer_failure", method=method, error_type=type(exc).__name__)
        try:
            live.state_diagnostics(page, "preparer-" + method, exc)
        except Exception:
            pass
        raise
    finally:
        (live.ROOT / "preparer-results.json").write_text(json.dumps(live.EVIDENCE, indent=2) + "\n")
        context.close()


def main():
    if not re.fullmatch(r"[0-9a-f]{40}", live.EXPECTED):
        raise ValueError("Provide the exact tested full Git revision before live acceptance.")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for method in ("pointer", "keyboard"):
                exercise(browser, method)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
