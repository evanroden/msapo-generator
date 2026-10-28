"""Exercise imported-image descriptions through the locked Streamlit frontend."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "import-picture-alt"
PORT = 8561
URL = f"http://127.0.0.1:{PORT}"


def exercise(browser, name):
    context = browser.new_context(viewport={"width": 1100, "height": 900})
    external, errors = [], []
    def guard(route):
        if urlparse(route.request.url).hostname == "127.0.0.1":
            route.continue_()
        else:
            external.append(route.request.url)
            route.abort()
    context.route("**/*", guard)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_default_timeout(20000)
    try:
        page.goto(URL, wait_until="domcontentloaded")
        first = page.locator(".st-key-monthly_import_picture_synthetic_first img")
        second = page.locator(".st-key-monthly_import_picture_synthetic_second img")
        unrelated = page.locator(".st-key-synthetic_unrelated_picture img")
        expect(first).to_have_attribute("alt", "Synthetic pump inspection · Image-only")
        expect(second).to_have_attribute("alt", "Original chart/contact page 2 · Image-only")
        # Native st.image still uses its index for images outside our owners.
        expect(unrelated).to_have_attribute("alt", "0")
        page.get_by_role("checkbox", name="Use updated caption", exact=True).check()
        expect(first).to_have_attribute("alt", "Updated synthetic pump inspection · Image-only")
        page.get_by_role("button", name="Unrelated rerun", exact=True).click()
        expect(first).to_have_attribute("alt", "Updated synthetic pump inspection · Image-only")
        expect(second).to_have_attribute("alt", "Original chart/contact page 2 · Image-only")
        expect(unrelated).to_have_attribute("alt", "0")
        # Check the accessible image name, not merely a nearby visible caption.
        expect(page.get_by_role("img", name="Updated synthetic pump inspection · Image-only", exact=True)).to_have_count(1)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        assert not errors and not external, (errors, external)
        return {"engine": name, "result": "passed", "synthetic_only": True,
                "native_caption_changes_and_rerenders": True, "unrelated_images_unchanged": True}
    except Exception:
        page.screenshot(path=str(OUT / f"{name}-failure.png"), full_page=True)
        (OUT / f"{name}-failure.html").write_text(page.content())
        raise
    finally:
        context.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="import-alt-synthetic-") as data:
        env = dict(os.environ, EPC_DATA_DIR=data, ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/import_picture_alt_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic image-description server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Synthetic image-description server did not become healthy")
                with sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("webkit", playwright.webkit)):
                        browser = engine.launch(headless=True)
                        try:
                            results.append(exercise(browser, name))
                        finally:
                            browser.close()
            finally:
                (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("PASS native imported-image descriptions, caption updates and rerenders")


if __name__ == "__main__":
    main()
