"""MR-021 synthetic native-browser first useful image timings (Chromium/WebKit).

This uses the real isolated Monthly QA app, native upload, gallery and preview
worker. Headless CI browser timing is not physical-device/served acceptance.
No private inputs, external requests, false image stubs or paid reader calls.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_monthly_adaptive as qa
from scripts import qa_issue_page_gallery as gallery

URL = "http://127.0.0.1:8534"
OUT = ROOT / "test-artifacts" / "monthly-preview-latency"
qa.URL = URL


def _decoded(image):
    image.wait_for(state="visible", timeout=90000)
    expect(image).to_have_js_property("complete", True, timeout=30000)
    assert image.evaluate("(node) => node.naturalWidth > 0 && node.naturalHeight > 0")
    return {"width": image.evaluate("(node) => node.naturalWidth"),
            "height": image.evaluate("(node) => node.naturalHeight"),
            "sha256": sha256((image.get_attribute("src") or "").encode()).hexdigest()}


def _exercise(browser_type, engine):
    browser = browser_type.launch(headless=True)
    records = []
    try:
        for sequence in range(3):
            context = browser.new_context(viewport={"width": 1365, "height": 900})
            context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
            external = []
            errors = []
            context.route("**/*", lambda route: route.continue_()
                          if urlparse(route.request.url).scheme in {"data", "blob"}
                          or (urlparse(route.request.url).hostname == "127.0.0.1"
                              and urlparse(route.request.url).port == 8534)
                          else (external.append(route.request.url), route.abort()))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                page.goto(URL, wait_until="domcontentloaded")
                # The clock starts at the native first report-load press. It
                # includes reruns/queue/conversion/raster/browser decode.
                start = time.perf_counter()
                page.get_by_role("button", name="Load known-value report", exact=True).click()
                expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
                field = page.get_by_role("textbox", name="Activity summary", exact=True)
                expect(field).to_be_visible(timeout=90000)
                qa.scroll_pair(page, qa.ACTIVITY)
                qa.current_image(page, qa.ACTIVITY)
                image = page.locator(qa.ACTIVITY).locator(".report-preview img").first
                first = _decoded(image)
                first_seconds = time.perf_counter() - start

                # Browser upload-to-useful-thumbnail includes the native
                # clicks needed to reveal the requested evidence page.
                alpha = gallery.source_pdf(f"latency-{sequence}-{engine}", 5)
                beta = gallery.source_pdf(f"control-{sequence}-{engine}", 2)
                manager = page.get_by_role("button", name="Manage source files", exact=True)
                if manager.count():
                    manager.click()
                uploader = page.get_by_test_id("stFileUploader").filter(has_text="Add source files")
                upload_started = time.perf_counter()
                uploader.locator('input[type="file"]').set_input_files([
                    {"name": "synthetic-preview-latency.pdf", "mimeType": "application/pdf", "buffer": alpha},
                    {"name": "synthetic-preview-control.pdf", "mimeType": "application/pdf", "buffer": beta}])
                expect(page.get_by_role("combobox", name="File to review", exact=True)).to_be_visible(timeout=90000)
                page.get_by_role("button", name="Done with source files", exact=True).click()
                issue = page.locator(gallery.ISSUES)
                qa.scroll_pair(page, gallery.ISSUES)
                gallery.open_gallery(issue)
                issue.get_by_role("button", name="Preview synthetic-preview-latency.pdf · page 1", exact=True).click()
                caption = "synthetic-preview-latency.pdf · page 1 · Preview only; original and issue links are unchanged."
                expect(issue.get_by_text(caption, exact=True)).to_be_visible(timeout=90000)
                thumb = _decoded(issue.get_by_test_id("stImage").locator("img").first)
                thumbnail_seconds = time.perf_counter() - upload_started

                # Newest rendered revision must win after a real edit. This
                # distinguishes a decoded old raster from a current result.
                qa.scroll_pair(page, qa.ACTIVITY)
                earlier = field.input_value()
                # Change the start of the first content page rather than
                # appending after the visible range: the raster must differ,
                # so a stale "Current" status can never satisfy this probe.
                revised = (f"MR-021 CURRENT REVISION {engine}-{sequence}: synthetic only.\n"
                           + earlier)
                previous_src = image.get_attribute("src")
                assert previous_src and previous_src.startswith("data:image/jpeg;base64,")
                field.fill(revised)
                field.press("Tab")
                digest = sha256(revised.encode()).hexdigest()
                expect(page.get_by_text("QA durable Activity SHA256: " + digest, exact=True)).to_be_visible(timeout=90000)
                update_started = time.perf_counter()
                qa.scroll_pair(page, qa.ACTIVITY)
                # A new image byte identity, not the editor text or the
                # server's possibly momentarily old "Current" label, proves
                # the newest rendered section replaced the earlier raster.
                latest_image = page.locator(qa.ACTIVITY).locator(".report-preview img").first
                expect(latest_image).not_to_have_attribute("src", previous_src, timeout=90000)
                qa.current_image(page, qa.ACTIVITY)
                latest = _decoded(latest_image)
                assert latest["sha256"] != first["sha256"], "New revision reused the old raster"
                assert field.input_value() == revised, "Manual edit was lost."
                assert not external and not errors, {"external": external, "pageerrors": errors}
                records.append({"index": sequence + 1, "fresh_report_press_to_decoded_section_seconds": round(first_seconds, 4),
                                "native_upload_to_requested_decoded_thumbnail_seconds": round(thumbnail_seconds, 4),
                                "edit_commit_to_current_section_seconds": round(time.perf_counter() - update_started, 4),
                                "first_section_image": first, "thumbnail": thumb, "latest_section_image": latest,
                                "manual_edit_retained": True, "upload_sha256": sha256(alpha).hexdigest(),
                                "second_upload_sha256": sha256(beta).hexdigest()})
            except Exception:
                OUT.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(OUT / f"{engine}-{sequence + 1}-failure.png"))
                raise
            finally:
                context.close()
    finally:
        browser.close()
    return records


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = {"fixture": "real isolated Monthly QA native app", "upload_bytes_transport": "localhost Playwright",
                "backend_resources": "CI-host runner; not the 512MiB/0.5CPU Docker resource job",
                "browser_device": "headless desktop engine; not actual mobile Safari or Render",
                "commit": os.environ.get("GITHUB_SHA") or os.environ.get("MSAPO_SHA") or "unreported",
                "engines": {}}
    if os.environ.get("QA491_EXTERNAL_SERVER") == "1":
        # The same real synthetic Monthly app is served inside the separately
        # restricted production container. Browser Playwright stays on host;
        # actual Streamlit, LibreOffice and PyMuPDF share the 512-MiB/0.5-CPU cap.
        evidence["backend_resources"] = "Docker production image 512 MiB RAM, 0.5 CPU"
        with urllib.request.urlopen(URL + "/_stcore/health", timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("The capped synthetic Monthly app is not healthy.")
        with sync_playwright() as playwright:
            for browser_type, name in ((playwright.chromium, "chromium"),
                                       (playwright.webkit, "webkit")):
                evidence["engines"][name] = _exercise(browser_type, name)
        (OUT / "browser.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        print(json.dumps(evidence, indent=2, sort_keys=True), flush=True)
        return
    with tempfile.TemporaryDirectory(prefix="qa491-browser-") as directory:
        (Path(directory) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
        env = dict(os.environ, EPC_DATA_DIR=directory, EPC_MONTHLY_DOM_FIXTURE="1",
                   ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        qa.URL = URL
        with (OUT / "streamlit.log").open("w") as log:
            server = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/monthly_app.py",
                "--server.address", "127.0.0.1", "--server.port", "8534",
                "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(300):
                    if server.poll() is not None:
                        raise RuntimeError("Synthetic Monthly browser fixture terminated")
                    try:
                        with urllib.request.urlopen(URL + "/_stcore/health", timeout=1) as check:
                            if check.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise TimeoutError("Synthetic Monthly browser fixture failed health check")
                with sync_playwright() as playwright:
                    for browser_type, name in ((playwright.chromium, "chromium"),
                                               (playwright.webkit, "webkit")):
                        evidence["engines"][name] = _exercise(browser_type, name)
            finally:
                server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
    (OUT / "browser.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps(evidence, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
