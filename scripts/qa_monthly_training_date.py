"""Actual native single-date Training journey, with an unpatched browser baseline.

Run in the existing independently permitted CI synthetic harness only. The
compatibility patch is installed in the same way as the production Docker image.
No runtime input writes, substitute widgets, fake labels, or suppressed live
regions are used. Browser assertions observe DOM accessibility state; they are
not a claim of a human screen-reader/audio or physical-device test.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
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
from zipfile import ZipFile

import pymupdf
import streamlit
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import patch_streamlit_date_input as compat
from scripts import qa_monthly_live as live

OUT = ROOT / "test-artifacts" / "monthly-training-date"
PORT = 8535
URL = f"http://127.0.0.1:{PORT}"
TITLE = "Synthetic hospital emergency preparedness and life safety refresher"
PARTICIPANT = "Synthetic Person North"
ROW = [TITLE, "2026-09-15", "In person", PARTICIPANT, ""]
RECEIPT = '[data-enfra-training-receipt]'
READY = """() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'"""


def receipt(page):
    nodes = page.locator(RECEIPT)
    return json.loads(nodes.last.get_attribute("data-enfra-training-receipt")) if nodes.count() else None


def await_events(page, rows, baseline):
    page.wait_for_function("""expected=>{
      const nodes=document.querySelectorAll('[data-enfra-training-receipt]');
      if(!nodes.length)return false;
      const state=JSON.parse(nodes[nodes.length-1].dataset.enfraTrainingReceipt);
      const matches=part=>part&&JSON.stringify(part.events)===JSON.stringify(expected.rows)&&
        part.matrix===expected.matrix&&part.notes===expected.notes&&part.unrelated===expected.unrelated;
      return matches(state.working)&&matches(state.durable)&&
        state.standing===expected.standing&&state.working_fingerprint===state.durable_fingerprint&&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={**baseline["working"], "standing": baseline["standing"], "rows": rows}, timeout=25000)
    live.EVIDENCE.setdefault("receipts", []).append(receipt(page))


def open_form(page):
    summary = page.locator('[data-testid="stExpander"] summary').filter(has=page.get_by_text("Add training session", exact=True))
    expect(summary).to_have_count(1)
    if not summary.evaluate("el => el.closest('details')?.open ?? el.getAttribute('aria-expanded')==='true'"):
        summary.click()
    date = page.locator('[data-testid="stDateInput"]').filter(has=page.get_by_text("Training date", exact=True))
    expect(date).to_have_count(1)
    field = date.get_by_test_id("stDateInputField")
    expect(field).to_be_visible()
    return date, field


def submit_form(page, submit):
    before = page.locator(".epc-workspace").get_attribute("data-epc-full-render")
    assert before, "A native full-editor receipt must precede the submission."
    submit.click()
    page.wait_for_function("""before=>{
        const current=document.querySelector('.epc-workspace')?.dataset.epcFullRender;
        return current&&current!==before&&document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg=before, timeout=25000)


def record_date(page, date, stage):
    values = {"stage": stage, "input": date.get_by_test_id("stDateInputField").input_value(),
              "announcements": date.locator('[aria-live="assertive"]').all_text_contents(),
              "active": page.evaluate("() => ({tag:document.activeElement?.tagName,role:document.activeElement?.getAttribute('role')})")}
    live.EVIDENCE.setdefault("date_states", []).append(values)
    return values


def no_second_date(date):
    expect(date.locator('[aria-live="assertive"]')).not_to_contain_text("second date")


def selected_date(date, expected):
    expect(date.locator('[aria-live="assertive"]')).to_have_text(f"Selected date is {expected}.")
    no_second_date(date)


def select_day(page, field, day):
    field.click()
    cell = page.get_by_role("gridcell", name=re.compile(rf"September {day}(?:st|nd|rd|th) 2026"))
    expect(cell).to_have_count(1)
    cell.click()
    expect(field).to_have_value(f"2026/09/{day:02d}")
    expect(cell).not_to_be_visible()


def export_and_check(page, stage, included):
    live.request_qa_generation(page, stage)
    word = live.download(page, "Download isolated QA DOCX", stage + ".docx")
    pdf = live.download(page, "Download isolated QA PDF", stage + ".pdf")
    with ZipFile(BytesIO(word)) as archive:
        from lxml import etree
        xml = etree.fromstring(archive.read("word/document.xml"))
        words = "\n".join(xml.xpath('//*[local-name()="t"]/text()'))
        session_rows = []
        for row in xml.xpath('//*[local-name()="tr"]'):
            cells = ["".join(cell.xpath('.//*[local-name()="t"]/text()'))
                     for cell in row.xpath('./*[local-name()="tc"]')]
            if TITLE in cells:
                session_rows.append(cells)
        assert session_rows == [ROW] if included else not session_rows
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        printed = "\n".join(page.get_text() for page in document)
    for label, text in (("DOCX", words), ("PDF", printed)):
        assert (TITLE in text) == included, f"{label} must reflect the deliberate monthly session inclusion."
        if included:
            assert "2026-09-15" in text and PARTICIPANT in text
    live.EVIDENCE.setdefault("outputs", []).append({"stage": stage, "included": included,
        "docx_bytes": len(word), "docx_sha256": sha256(word).hexdigest(),
        "pdf_bytes": len(pdf), "pdf_sha256": sha256(pdf).hexdigest()})


def exercise(browser_type, engine, *, patched):
    scope = "repaired" if patched else "unpatched-baseline"
    live.ROOT = OUT / scope / engine
    live.ROOT.mkdir(parents=True, exist_ok=True)
    live.EVIDENCE = {"synthetic_only": True, "browser": engine, "scope": scope,
                     "checks": {}, "events": [], "artifacts": {}, "tested_checkout":
                     subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    attempts, errors, date_responses = [], [], []
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
    page.on("pageerror", lambda error: errors.append(str(error)[:500]))
    page.on("response", lambda response: date_responses.append(response) if "/DateInput." in response.url and response.url.endswith(".js") else None)
    try:
        page.goto(URL, wait_until="domcontentloaded")
        live.load_fixture(page, "prefill")
        page.wait_for_function(READY, timeout=25000)
        date, field = open_form(page)
        expect(field).to_have_value("")
        field.fill("2026/09/14")
        field.press("Tab")
        expect(field).to_have_value("2026/09/14")
        assert len(date_responses) == 1
        asset = date_responses[0]
        asset_hash = sha256(asset.body()).hexdigest()
        live.EVIDENCE["date_asset"] = {"url": asset.url, "sha256": asset_hash}
        assert (asset_hash != compat.ORIGINAL_SHA256) == patched
        if patched:
            expected = json.loads((OUT / "compatibility-patch.json").read_text())
            assert asset_hash == expected["patched_sha256"] and expected["bundle"] in asset.url
        if not patched:
            expect(date.locator('[aria-live="assertive"]')).to_contain_text("Select the second date.")
            record_date(page, date, "single-date-announced-as-range")
            live.screenshot(page, "observed-scalar-announcement-defect")
            assert not errors and not attempts
            return
        selected_date(date, "2026/09/14")
        record_date(page, date, "typed-single-date")
        select_day(page, field, 15)
        selected_date(date, "2026/09/15")
        record_date(page, date, "one-calendar-selection-closes")
        live.screenshot(page, "correct-single-date-announcement")
        field.click()
        field.press("ArrowDown")
        page.wait_for_function("() => document.activeElement?.getAttribute('role')==='gridcell'")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("Enter")
        expect(field).to_have_value("2026/09/16")
        selected_date(date, "2026/09/16")
        record_date(page, date, "keyboard-single-selection")
        baseline = receipt(page)
        assert baseline and baseline["working"] == baseline["durable"]
        page.get_by_role("textbox", name="Training topic", exact=True).fill(TITLE)
        participants = page.locator('[data-testid="stMultiSelect"]').filter(has=page.get_by_text("Participants", exact=True))
        participants.get_by_role("combobox").fill(PARTICIPANT)
        page.get_by_role("option", name=PARTICIPANT, exact=True).click()
        date.get_by_role("button", name="Clear value", exact=True).click()
        expect(field).to_have_value("")
        expect(date.locator('[aria-live="assertive"]')).to_have_text("")
        record_date(page, date, "cleared-date")
        submit = page.get_by_role("button", name="Add training session", exact=True)
        submit_form(page, submit)
        expect(page.get_by_text("Choose a training date within this reporting month.", exact=True)).to_be_visible()
        await_events(page, baseline["working"]["events"], baseline)
        for value, stage in (("2026/09/", "partial-date"), ("2026/08/31", "before-month"), ("2026/10/01", "after-month")):
            date, field = open_form(page)
            field.fill(value)
            field.press("Tab")
            record_date(page, date, stage)
            no_second_date(date)
            submit_form(page, submit)
            expect(page.get_by_text("Choose a training date within this reporting month.", exact=True)).to_be_visible()
            await_events(page, baseline["working"]["events"], baseline)
        date, field = open_form(page)
        field.fill("2026/09/14")
        field.press("Tab")
        select_day(page, field, 15)
        no_second_date(date)
        submit_form(page, submit)
        await_events(page, [*baseline["working"]["events"], ROW], baseline)
        page.reload(wait_until="domcontentloaded")
        await_events(page, [*baseline["working"]["events"], ROW], baseline)
        added = page.get_by_role("button", name=f"Remove session: {TITLE} · 2026-09-15", exact=True)
        added.scroll_into_view_if_needed()
        live.screenshot(page, "desktop-session-card")
        export_and_check(page, "session-added", True)
        page.set_viewport_size({"width": 390, "height": 844})
        added.scroll_into_view_if_needed()
        expect(added).to_be_visible()
        assert page.evaluate("() => document.documentElement.scrollWidth<=innerWidth+1"), "Training must not cause whole-page narrow overflow."
        live.screenshot(page, "narrow-session-card")
        added.click()
        await_events(page, baseline["working"]["events"], baseline)
        page.reload(wait_until="domcontentloaded")
        await_events(page, baseline["working"]["events"], baseline)
        export_and_check(page, "session-removed", False)
        assert not errors and not attempts
        live.screenshot(page, "training-date-session-output-complete")
    except Exception as exc:
        live.EVIDENCE["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            live.EVIDENCE["last_receipt"] = receipt(page)
            live.EVIDENCE["date_dom"] = page.locator('[data-testid="stDateInput"]').all_text_contents()
            live.screenshot(page, "first-failure")
        except Exception:
            pass
        raise
    finally:
        live.EVIDENCE["browser_errors"] = errors
        live.EVIDENCE["external_requests"] = attempts
        (live.ROOT / "results.json").write_text(json.dumps(live.EVIDENCE, indent=2) + "\n")
        context.close()
        browser.close()


@contextmanager
def server(stage):
    with tempfile.TemporaryDirectory(prefix="monthly-training-date-") as temp:
        (Path(temp) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", EPC_MONTHLY_TRAINING_TASK="1",
                   ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        with (OUT / (stage + "-streamlit.log")).open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "tests/fixtures/workspaces/monthly_app.py",
                "--server.address", "127.0.0.1", "--server.port", str(PORT), "--server.headless", "true",
                "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Guarded synthetic Training server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Guarded synthetic Training server did not become healthy")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    static = Path(streamlit.__file__).parent / "static"
    asset = static / "static" / "js" / compat.BUNDLE_NAME
    assert sha256(asset.read_bytes()).hexdigest() == compat.ORIGINAL_SHA256, "Baseline requires the exact unpatched locked wheel."
    assert compat.INDEX_BUNDLE.encode() in (static / "index.html").read_bytes(), "Baseline must actually select the unpatched entry."
    failures = []
    with sync_playwright() as playwright:
        with server("baseline"):
            for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                try:
                    exercise(engine, name, patched=False)
                except Exception as exc:
                    failures.append("baseline " + name + ": " + str(exc)[:300])
        if failures:
            raise AssertionError("The planned scalar-date baseline was not established: " + "; ".join(failures))
        patch_receipt = compat.patch_bundle(static, installed_version=version("streamlit"))
        (OUT / "compatibility-patch.json").write_text(json.dumps(patch_receipt, indent=2) + "\n")
        # Fresh server and browser contexts avoid reusing the original static
        # cache; the widget protocol/control itself remains the production one.
        with server("repaired"):
            for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                try:
                    exercise(engine, name, patched=True)
                except Exception as exc:
                    failures.append("repaired " + name + ": " + str(exc)[:300])
    if failures:
        raise AssertionError("Native Training date failures: " + "; ".join(failures))
    print("PASS actual scalar-date accessibility state, one-date entry, session durable add/remove and Word/PDF output in both engines")


if __name__ == "__main__":
    main()
