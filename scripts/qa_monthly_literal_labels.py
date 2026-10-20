"""Check literal labels through the actual Streamlit frontend, including GFM.

All inputs are invented. This local fixture has no production storage access.
Server-side AppTest cannot detect the frontend's post-parse automatic links.
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
OUT = ROOT / "test-artifacts" / "monthly-literal-labels"
PORT = 8534
URL = f"http://127.0.0.1:{PORT}"
VALUES = (
    "[Synthetic](https://example.invalid) **Account**",
    "https://example.invalid/one?q=two",
    "www.example.invalid",
    "synthetic@example.invalid",
    "**Bold** _em_ `code` & <tag> $money$ :red[text]",
)


def exercise(browser, name):
    context = browser.new_context(viewport={"width": 1100, "height": 900})
    context.route("**/*", lambda route: route.continue_()
                  if urlparse(route.request.url).hostname == "127.0.0.1" else route.abort())
    page = context.new_page()
    page.set_default_timeout(15000)
    try:
        page.goto(URL, wait_until="domcontentloaded")
        expect(page.get_by_text("Selected value: none", exact=True)).to_be_visible()
        for index, raw in enumerate(VALUES):
            case = page.locator(f".st-key-literal_case_{index}")
            expect(case.locator("h3")).to_be_visible()
            # U+2060 is a presentation-only anti-autolink delimiter. Raw input
            # values and the selected identity below must contain no delimiter.
            # Compare DOM text, not browser-specific innerText block/newline
            # layout. Native expect assertions also wait for lazy hydration.
            visible_text = re.compile("^" + "\u2060?".join(re.escape(c) for c in raw) + "$")
            expect(case.locator("h3")).to_have_text(visible_text)
            expect(case.locator("[data-testid=stCaptionContainer]")).to_have_text(visible_text)
            expect(case.get_by_role("textbox")).to_have_value(raw)
            expect(case.get_by_role("radio")).to_be_visible()
            expect(case.locator("a, strong, em, del, code, img")).to_have_count(0)
        page.locator(".st-key-literal_case_0").get_by_role("button", exact=False).press("Enter")
        expect(page.get_by_text("Selected value: " + VALUES[0], exact=True)).to_be_visible()
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        return {"engine": name, "cases": len(VALUES), "unwanted_links_or_formatting": 0,
                "raw_input_and_selected_identity_preserved": True}
    except Exception:
        text_state = page.evaluate("""() => Array.from(document.querySelectorAll(
            '[class*="st-key-literal_case_"]')).map(node => ({
            heading: node.querySelector('h3')?.textContent,
            caption: node.querySelector('[data-testid="stCaptionContainer"]')?.textContent,
            input: node.querySelector('input[type="text"]')?.value,
            links: node.querySelectorAll('a').length}))""")
        (OUT / f"{name}-failure-text.json").write_text(json.dumps(text_state, indent=2))
        page.screenshot(path=str(OUT / f"{name}-failure.png"), full_page=True)
        raise
    finally:
        context.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="literal-labels-synthetic-") as data:
        env = dict(os.environ, EPC_DATA_DIR=data, ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/literal_labels_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic literal-label server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Synthetic literal-label server did not become healthy")
                results = []
                with sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("webkit", playwright.webkit)):
                        browser = engine.launch(headless=True)
                        try:
                            results.append(exercise(browser, name))
                        finally:
                            browser.close()
                (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("PASS actual literal-label DOM, no links/formatting, raw identity preserved")


if __name__ == "__main__":
    main()
