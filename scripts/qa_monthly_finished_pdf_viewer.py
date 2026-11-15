"""Browser evidence for exact finished-PDF bytes and stale-fragment retirement.

Runs real production Streamlit preview component with synthetic PDF bytes at a
private localhost endpoint. No Render access, browser-to-Internet requests,
shared-report data, persistence, PDF regeneration or fixture substitution.
"""
from __future__ import annotations

from base64 import b64decode
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

import pymupdf
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "finished-pdf-viewer"
PORT = 8563
URL = f"http://127.0.0.1:{PORT}"


def image_ready(page):
    image = page.locator(".report-preview img").first
    expect(page.locator(".report-preview-status")).to_contain_text(
        "Preview · 1 page", timeout=90000)
    image.wait_for(state="visible", timeout=30000)
    page.wait_for_function(
        """() => {
          const deep = root => [...root.querySelectorAll('.report-preview img'),
            ...[...root.querySelectorAll('*')].filter(node => node.shadowRoot)
              .flatMap(node => deep(node.shadowRoot))];
          return deep(document).some(img => img.complete && img.naturalWidth > 0);
        }""", timeout=45000)
    value = image.get_attribute("src")
    assert value and value.startswith("data:image/jpeg;base64,"), value
    return b64decode(value.partition(",")[2], validate=True)


def download_current(page):
    """Download actual native Streamlit bytes, not the fixture's Python variable."""
    with page.expect_download(timeout=45000) as operation:
        page.get_by_role("button", name="Download current synthetic PDF", exact=True).click()
    return Path(operation.value.path()).read_bytes()


def assert_download_matches_view(raw: bytes, viewed_jpeg: bytes, expected: str):
    """Independently rasterize the downloaded PDF, matching the viewer's DPI.

    Comparing only captions or a different A/B JPEG digest misses a viewer
    that displays an older PDF while the download already serves new bytes.
    """
    assert raw.startswith(b"%PDF-") and viewed_jpeg.startswith(bytes((0xFF, 0xD8)))
    with pymupdf.open(stream=raw, filetype="pdf") as doc:
        assert len(doc) == 1, "Synthetic viewer must display one PDF page."
        page = doc[0]
        assert expected in page.get_text(), "Downloaded bytes are not the selected report."
        for dpi in (96, 120, 150):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(dpi / 72, dpi / 72),
                                  colorspace=pymupdf.csRGB, alpha=False)
            if pix.tobytes("jpeg", jpg_quality=88) == viewed_jpeg:
                return dpi
    raise AssertionError("Displayed page JPEG does not match rasterization of the downloaded PDF.")


def check_engine(engine, name, width):
    label = name + "-" + str(width)
    details = {"browser": name, "width": width, "events": [],
               "artifacts": {}, "external_attempts": [], "errors": []}
    browser = engine.launch(headless=True)
    context = browser.new_context(accept_downloads=True, viewport={"width": width, "height": 780 if width < 600 else 900})
    def route(request):
        target = urlparse(request.request.url)
        if target.scheme in ("data", "blob") or (target.hostname == "127.0.0.1" and target.port == PORT):
            request.continue_()
        else:
            details["external_attempts"].append(request.request.url[:250])
            request.abort()
    context.route("**/*", route)
    page = context.new_page()
    page.on("pageerror", lambda error: details["errors"].append(str(error)[:600]))
    page.set_default_timeout(30000)
    try:
        page.goto(URL, wait_until="domcontentloaded")
        expect(page.get_by_text("QA current PDF: absent", exact=True)).to_be_visible()
        assert page.get_by_text("View PDF here (this session)", exact=True).count() == 0
        details["events"].append("empty browser starts without a saved PDF")

        page.get_by_role("button", name="Create PDF A").click()
        expect(page.get_by_text("QA current PDF: alpha", exact=True)).to_be_visible()
        pdf_a = download_current(page)
        expander = page.get_by_text("View PDF here (this session)", exact=True)
        expander.click()
        image_a = image_ready(page)
        dpi_a = assert_download_matches_view(pdf_a, image_a, "SYNTHETIC FINISHED PDF ALPHA")
        details["artifacts"]["A"] = {"pdf_sha256": sha256(pdf_a).hexdigest(),
                                      "visible_jpeg_sha256": sha256(image_a).hexdigest(),
                                      "matching_dpi": dpi_a}
        page.screenshot(path=str(OUT / f"{label}-pdf-a.png"))
        details["events"].append("A exact downloaded PDF and displayed page JPEG match")

        # A different browser must NOT inherit the PDF while the first viewer
        # is still live and its disposable raster ticket remains active.
        other = browser.new_context(viewport={"width": 1300, "height": 900})
        other.route("**/*", route)
        try:
            other_page = other.new_page()
            other_page.goto(URL, wait_until="domcontentloaded")
            expect(other_page.get_by_text("QA current PDF: absent", exact=True)).to_be_visible()
            expect(other_page.get_by_text("View PDF here (this session)", exact=True)).to_have_count(0)
            details["events"].append("separate browser session cannot access live finished PDF")
        finally:
            other.close()

        page.get_by_role("button", name="Replace with no PDF").click()
        expect(page.get_by_text("QA current PDF: none", exact=True)).to_be_visible()
        expect(page.get_by_text("QA owner entries: 0", exact=True)).to_be_visible()
        expect(page.get_by_text("QA live preview tickets: 0", exact=True)).to_be_visible()
        expect(page.get_by_text("View PDF here (this session)", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Download current synthetic PDF")).to_have_count(0)
        expect(page.locator(".report-preview img")).to_have_count(0)
        details["events"].append("same-draft no-PDF replacement retired viewer and download")

        page.get_by_role("button", name="Replace with PDF B").click()
        expect(page.get_by_text("QA current PDF: bravo", exact=True)).to_be_visible()
        pdf_b = download_current(page)
        assert sha256(pdf_b).digest() != sha256(pdf_a).digest(), "Replacement kept PDF A bytes."
        page.get_by_text("View PDF here (this session)", exact=True).click()
        image_b = image_ready(page)
        assert image_a != image_b, "New package did not replace the visible page raster."
        dpi_b = assert_download_matches_view(pdf_b, image_b, "SYNTHETIC FINISHED PDF BRAVO")
        details["artifacts"]["B"] = {"pdf_sha256": sha256(pdf_b).hexdigest(),
                                      "visible_jpeg_sha256": sha256(image_b).hexdigest(),
                                      "matching_dpi": dpi_b}
        page.screenshot(path=str(OUT / f"{label}-pdf-b.png"))
        details["events"].append("B exact downloaded PDF and displayed page JPEG match; A retired")

        page.get_by_role("button", name="Start over").click()
        expect(page.get_by_text("QA current PDF: absent", exact=True)).to_be_visible()
        expect(page.get_by_text("QA owner entries: 0", exact=True)).to_be_visible()
        expect(page.locator(".report-preview img")).to_have_count(0)
        expect(page.get_by_role("button", name="Download current synthetic PDF")).to_have_count(0)
        details["events"].append("reset discarded viewer, download and disposable owner")

        assert not details["errors"] and not details["external_attempts"], details
        details["result"] = "passed"
    except Exception as exc:
        details["result"] = "failed"
        details["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            page.screenshot(path=str(OUT / f"{label}-first-failure.png"))
        except Exception:
            pass
        raise
    finally:
        (OUT / f"{label}-results.json").write_text(json.dumps(details, indent=2) + "\n")
        context.close()
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="enfra-pdf-viewer-synthetic-") as temp:
        marker = Path(temp) / "synthetic-finished-pdf-only.marker"
        marker.write_text("only synthetic data", encoding="ascii")
        env = dict(os.environ, EPC_FINISHED_PDF_VIEWER_QA="1",
                   EPC_VIEWER_QA_ROOT=temp, PYTHONDONTWRITEBYTECODE="1",
                   SMARTSHEET_API_MODE="disabled", ANTHROPIC_API_KEY="")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run",
                 "tests/fixtures/workspaces/finished_pdf_viewer_app.py",
                 "--server.address", "127.0.0.1",
                 "--server.port", str(PORT),
                 "--server.headless", "true",
                 "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic viewer fixture exited during startup")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.15)
                else:
                    raise RuntimeError("Synthetic viewer fixture did not become healthy")
                with sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium),
                                         ("webkit", playwright.webkit)):
                        for width in (1300, 390):
                            check_engine(engine, name, width)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
