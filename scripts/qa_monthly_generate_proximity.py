"""390px synthetic QA browser regression for blockers beside Monthly creation.

Requires a running local Streamlit server (or an explicitly supplied isolated
QA URL) and installed Playwright Chromium. Never opens the live report route,
submits client data, or exports an artifact.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


ORIGIN = os.environ.get("MONTHLY_QA_PUBLIC_URL", "http://127.0.0.1:8501").rstrip("/")
URL = ORIGIN + "/?workflow=monthly&monthly_qa=isolated"


def _same_viewport(reason, button, *, width: int, height: int):
    """Bounds after scrolling to the action: both must remain visible."""
    button.scroll_into_view_if_needed()
    assert reason.is_visible()
    text_box, button_box = reason.bounding_box(), button.bounding_box()
    assert text_box and button_box
    for box in (text_box, button_box):
        assert box["x"] >= -2 and box["x"] + box["width"] <= width + 2, box
        assert box["y"] >= -2 and box["y"] + box["height"] <= height + 2, box
    assert text_box["y"] + text_box["height"] <= button_box["y"] + 2, (
        text_box, button_box)


def main():
    target = urlparse(URL)
    if target.scheme not in {"http", "https"}:
        raise ValueError("The isolated QA browser URL must be HTTP(S).")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=65000)
            expect(page.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False)).to_be_visible()
            page.get_by_role("button", name="Load known-value report", exact=True).click()
            activity = page.get_by_role("textbox", name="Activity summary", exact=True)
            expect(activity).to_be_visible(timeout=60000)
            # A synthetic price is deliberately inserted only in the isolated
            # disposable QA namespace. The real preflight gate must stay intact.
            activity.fill("September 2026 synthetic maintenance; test price $42.00.")
            activity.press("Tab")
            qa = page.get_by_role("button", name="Generate QA Word and PDF", exact=True)
            reason = page.get_by_text(re.compile(r"^Before generating:.*", re.I)).filter(
                has_text=re.compile("pric", re.I)).first
            expect(reason).to_be_visible(timeout=45000)
            _same_viewport(reason, qa, width=390, height=844)

            standard = page.get_by_role("button", name="Create Word and PDF", exact=True)
            expect(standard).to_be_disabled()
            # The ordinary action has its own, separately rendered reason next
            # to it, even though the QA toolbar is earlier in the document.
            ordinary = page.get_by_text(re.compile(r"^Before generating:.*", re.I)).filter(
                has_text=re.compile("pric", re.I)).last
            _same_viewport(ordinary, standard, width=390, height=844)
            # Raw receipts remain hidden unless a tester opens QA details.
            qa_state = page.get_by_text(re.compile(r"^QA fixture state:")).first
            expect(qa_state).to_be_hidden()
            print("PASS: 390x844 QA and Monthly generation reasons and actions share each viewport.")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
