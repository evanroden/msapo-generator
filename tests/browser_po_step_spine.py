"""Browser smoke check for the U10 step list against a served app.

Run: python tests/browser_po_step_spine.py --url http://localhost:8501/
Requires installed Playwright Chromium and WebKit browsers.
"""
from __future__ import annotations

import argparse
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import sync_playwright


def check(url: str) -> None:
    parts = urlsplit(url)
    url = urlunsplit((parts.scheme, parts.netloc, parts.path, "workflow=purchase", ""))
    with sync_playwright() as playwright:
        for engine_name in ("chromium", "webkit"):
            for width, height in ((1920, 993), (390, 844)):
                browser = getattr(playwright, engine_name).launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    spine = page.get_by_role("navigation", name="Purchase order steps")
                    spine.wait_for(state="visible", timeout=30000)
                    links = spine.locator("a.po-step-link")
                    assert links.count() == 4
                    for link in links.all():
                        assert link.get_attribute("href", timeout=1000).startswith("#po-step-")
                    box = spine.bounding_box()
                    assert box is not None
                    assert box["y"] >= 0, (engine_name, width, "list starts above viewport", box)
                    assert box["y"] + box["height"] <= height, (
                        engine_name, width, "step list below fold", box
                    )
                    assert spine.locator('a[aria-current="step"]').count() == 1
                    quote_link = spine.locator('a[href="#po-step-quote"]')
                    quote_link.click()
                    assert page.evaluate("location.hash") == "#po-step-quote"
                    assert page.locator("#po-step-quote").count() == 1
                    # Once a synthetic quote exists, every section is mounted.
                    page.get_by_text("About", exact=True).last.click()
                    page.get_by_role("button", name="Load synthetic quote").click()
                    spine = page.get_by_role("navigation", name="Purchase order steps")
                    for name in ("quote", "scope", "details", "generate"):
                        anchor = f"#po-step-{name}"
                        assert page.locator(anchor).count() == 1
                        spine.locator(f'a[href="{anchor}"]').click()
                        assert page.evaluate("location.hash") == anchor
                    print(f"PASS {engine_name} {width}x{height}: fold + four anchors")
                finally:
                    browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501/")
    check(parser.parse_args().url)
