"""Actual Training/issue text and generation in the guarded synthetic app.

Local disposable storage only, no customer data or external readers. Reuses
existing strict generation receipts, not retries or a relaxed fingerprint gate.
Chromium and WebKit run independently; every first failure is retained.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen
from zipfile import ZipFile

import pymupdf
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "monthly-text-hydration"
PORT = 8530
URL = f"http://127.0.0.1:{PORT}"
from scripts import qa_monthly_live as live

EXPECTED = {"Training notes": "Hospital staff completed a synthetic training exercise.",
            "Issue description": "Synthetic actuator feedback follow-up."}
READY = """() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'"""


def commit_text(page, field, text):
    before = page.locator('.epc-workspace').get_attribute('data-epc-full-render')
    field.fill(text)
    field.press("Tab")
    page.wait_for_function("""before => {
        const stamp=document.querySelector('.epc-workspace')?.dataset.epcFullRender;
        return stamp && stamp!==before && document.querySelector('[data-testid="stApp"]')
            ?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg=before, timeout=25000)
    expect(field).to_have_value(text)


def export_and_check(page, stage):
    live.request_qa_generation(page, stage)
    word = live.download(page, "Download isolated QA DOCX", stage + ".docx")
    pdf = live.download(page, "Download isolated QA PDF", stage + ".pdf")
    with ZipFile(BytesIO(word)) as archive:
        from lxml import etree
        xml = etree.fromstring(archive.read('word/document.xml'))
        words = "\n".join(xml.xpath('//*[local-name()="t"]/text()'))
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        printed = "\n".join(page.get_text() for page in document)
    for label, text in EXPECTED.items():
        live.checkpoint(stage + " " + label + " present in actual Word/PDF", text in words and text in printed)


def exercise(browser_type, name):
    # Only harness evidence routing changes here; no production function or
    # renderer is patched. The imported helpers act solely on the passed page.
    live.ROOT = OUT / name
    live.ROOT.mkdir(parents=True, exist_ok=True)
    live.EVIDENCE = {"synthetic_only": True, "public_url": URL, "browser": name,
                     "checks": {}, "events": [], "artifacts": {}}
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    attempts = []

    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"data", "blob"} or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            attempts.append(parsed.hostname)
            request.abort()

    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    try:
        page.goto(URL, wait_until="domcontentloaded")
        live.load_fixture(page, "prefill")
        for label, wording in EXPECTED.items():
            expect(page.get_by_role("textbox", name=label, exact=True)).to_have_value(wording, timeout=30000)
        page.wait_for_function(READY, timeout=20000)
        page.get_by_role("button", name="Compare fixture facts", exact=True).click()
        expect(page.get_by_text("known-value prefill: 18/18 independent content/provenance checks.", exact=False)).to_be_visible(timeout=45000)
        export_and_check(page, "first-native-hydration")
        activity = page.get_by_role("textbox", name="Activity summary", exact=True).input_value()
        for label, wording in EXPECTED.items():
            field = page.get_by_role("textbox", name=label, exact=True)
            identity = field.get_attribute("id")
            commit_text(page, field, "")
            page.reload(wait_until="domcontentloaded")
            expect(field).to_have_value("", timeout=45000)
            page.wait_for_function(READY, timeout=20000)
            live.checkpoint(label + " deliberate clear survives reload", True)
            commit_text(page, field, wording)
            page.reload(wait_until="domcontentloaded")
            expect(field).to_have_value(wording, timeout=45000)
            page.wait_for_function(READY, timeout=20000)
            live.checkpoint(label + " reentry survives reload", True)
            # A full browser reload is a fresh native mount; stability within
            # an edit is asserted separately by the protobuf AppTest regression.
            live.event("native_text_restored", field=label, text_sha256=sha256(wording.encode()).hexdigest(),
                       initial_dom_id_present=bool(identity))
        expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_have_value(activity)
        export_and_check(page, "restored-native-text")
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        live.checkpoint("no external browser requests", not attempts)
        live.screenshot(page, "final-synthetic-output")
    except Exception as exc:
        live.EVIDENCE["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            live.EVIDENCE["structural_changes"] = page.get_by_text("QA structural change since accepted click", exact=False).all_text_contents()
            live.screenshot(page, "first-failure")
        except Exception:
            pass
        raise
    finally:
        (live.ROOT / "results.json").write_text(json.dumps(live.EVIDENCE, indent=2) + "\n")
        context.close()
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    with tempfile.TemporaryDirectory(prefix="monthly-text-hydration-") as temp:
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
                        raise RuntimeError("Guarded synthetic server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Guarded synthetic server did not become healthy")
                with sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                        try:
                            exercise(engine, name)
                        except Exception as exc:
                            failures.append(name + ": " + type(exc).__name__ + ": " + str(exc)[:300])
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    if failures:
        raise AssertionError("Native text hydration failures: " + "; ".join(failures))
    print("PASS native Training/issue hydration, real generation and deliberate clear/reentry/reload in both engines")


if __name__ == "__main__":
    main()
