"""CI-only, native-pointer/keyboard Monthly simplicity acceptance.

Fresh ordinary report, real synthetic CSV intake, actual manager/Training
controls. No auto-opening after additions, input injection, or widget substitutes.
Run only in an independently permitted browser environment. This script does
not establish physical-device or human assistive-technology acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.contracts import RRH_CONTRACT as CONTRACT

OUT = ROOT / "test-artifacts" / "monthly-simplicity"
PORT = 8543
URL = f"http://127.0.0.1:{PORT}/?workflow=monthly"
SITE = "United Memorial Medical Center"
ACTOR = "Synthetic Simplicity Reviewer"
PERSON = "Synthetic Simplicity Participant"
RECEIPT = "[data-monthly-simplicity-receipt]"
PANEL = 'div[class*="st-key-"][class*="_source_manager_panel"]'


def allowed_url(url):
    """This exact server and its canonical native WebKit blob module URLs only."""
    try:
        if url.startswith("blob:"):
            inner = urlparse(url[5:])
            if inner.query or inner.fragment or not allowed_url(url[5:]):
                return False
            identity = inner.path.lstrip("/")
            return str(uuid.UUID(identity)) == identity
        parsed = urlparse(url)
        return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port == PORT and parsed.username is None and parsed.password is None)
    except ValueError:
        return False


def expect(locator):
    from playwright.sync_api import expect as native_expect
    return native_expect(locator)


def select(page, name, value):
    from scripts.qa_water_fresh_page_journey import select as native_select
    return native_select(page, name, value)


def require_native_errors_clean(value):
    assert isinstance(value, dict) and value.get("installed") is True, "Native error collector missing"
    assert value.get("schema") == "enfra-fresh-native-errors-v1"
    assert value.get("origin") == f"http://127.0.0.1:{PORT}" and value.get("limit") == 16
    assert type(value.get("total")) is int and type(value.get("overflow")) is int
    assert value["total"] == 0 and value["overflow"] == 0 and value.get("errors") == [], value


def settled(page):
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
      ?.getAttribute('data-test-script-state')==='notRunning'""", timeout=30000)


def receipt(page):
    expect(page.locator(RECEIPT)).to_have_count(1)
    return json.loads(page.locator(RECEIPT).get_attribute("data-monthly-simplicity-receipt"))


def wait_rows(page, expected):
    page.wait_for_function("""rows => {
      const node=document.querySelector('[data-monthly-simplicity-receipt]');
      return node && JSON.stringify(JSON.parse(node.getAttribute('data-monthly-simplicity-receipt')).events)===JSON.stringify(rows)
        && document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg=expected, timeout=30000)


def disclosure(page):
    return page.locator('[data-testid="stExpander"] summary').filter(
        has=page.get_by_text("Add completed training", exact=True))


def form_open(page, expected=True):
    summary = disclosure(page)
    expect(summary).to_have_count(1)
    expect(summary.locator("xpath=ancestor::details[1]")).to_have_attribute("open", "") if expected else expect(
        summary.locator("xpath=ancestor::details[1]")).not_to_have_attribute("open", "")
    topic = page.get_by_role("textbox", name="Training topic", exact=True)
    expect(topic).to_be_visible() if expected else expect(topic).not_to_be_visible()
    return topic


def refresh(page):
    # Neutral fixture probe is excluded from the product task click comparison.
    before = receipt(page)["render_id"]
    page.get_by_role("button", name="Refresh synthetic observation", exact=True).click()
    wait_render(page, before)


def wait_render(page, before):
    page.wait_for_function("""before => {
      const node=document.querySelector('[data-monthly-simplicity-receipt]');
      return node && JSON.parse(node.getAttribute('data-monthly-simplicity-receipt')).render_id!==before
        && document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg=before, timeout=30000)


def submit_training(page):
    before = receipt(page)["render_id"]
    page.get_by_role("button", name="Add completed training", exact=True).click()
    wait_render(page, before)


def fill_training(page, number):
    # Deliberately does NOT open the disclosure; the next form must already be visible.
    topic = form_open(page)
    expect(topic).to_have_value("")
    field = page.locator('[data-testid="stDateInput"]').filter(
        has=page.get_by_text("Training date", exact=True)).get_by_test_id("stDateInputField")
    expect(field).to_have_value("")
    topic.fill(f"Synthetic completed training {number}")
    from scripts.qa_monthly_training_date import replace_date
    replace_date(page, field, f"2026/09/{14 + number:02d}", f"simplicity-add-{number}")
    participants = page.locator('[data-testid="stMultiSelect"]').filter(
        has=page.get_by_text("Participants", exact=True))
    expect(participants.locator('[data-tag]')).to_have_count(0)
    combo = participants.get_by_role("combobox")
    combo.click()
    combo.fill(PERSON)
    # Production accept-new-options is intentionally exercised for the empty roster.
    option = page.get_by_role("option").filter(has_text=PERSON)
    expect(option).to_have_count(1)
    option.click()
    expect(participants.locator('[data-tag]')).to_have_text([PERSON])
    # A native multiselect keeps its menu open after choosing a participant.
    # Complete that keyboard interaction before addressing sibling form fields;
    # do not bypass the menu's accessibility scope with hidden DOM selectors.
    combo.press("Escape")
    expect(combo).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("textbox", name="Hours (optional)", exact=True)).to_have_value("")


def exercise(engine, name, record):
    browser = engine.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=False)
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(24), "url": URL}])
    external, errors = [], []
    def route(request):
        if not allowed_url(request.request.url):
            external.append(request.request.url)
            request.abort()
        else:
            request.continue_()
    context.route("**/*", route)
    diagnostic = os.environ.get("EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS") == "1"
    if diagnostic:
        context.tracing.start(screenshots=False, snapshots=False, sources=False)
    page = context.new_page()
    if diagnostic:
        from scripts.qa_simplicity_delivery import Wire
        wire = Wire()
        wire.attach(page)
        page.add_init_script((ROOT / "scripts/qa_simplicity_pointer.js").read_text())
    collector = (ROOT / "scripts/qa_fresh_native_errors.js").read_text()
    assert collector.count("http://127.0.0.1:8529") == 1
    page.add_init_script(collector.replace("http://127.0.0.1:8529", f"http://127.0.0.1:{PORT}"))
    page.set_default_timeout(30000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    def capture(stage):
        record["steps"].append({"stage": stage, "receipt": receipt(page)})
        page.screenshot(path=str(OUT / f"{name}-{stage}.png"), full_page=False)
    try:
        record["phase"] = "ordinary empty report"
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_role("button", name=CONTRACT, exact=True).click()
        site = page.get_by_role("checkbox", name=SITE, exact=True)
        site.locator("xpath=ancestor::label[1]").click()
        select(page, "Reporting month", "September")
        select(page, "Reporting year", "2026")
        page.get_by_role("button", name="Use ENFRA template", exact=True).click()
        actor = page.get_by_role("textbox", name="Your name", exact=True)
        actor.fill(ACTOR)
        actor.press("Tab")
        page.get_by_role("button", name="Start this report", exact=True).click()
        expect(page.locator(PANEL)).to_be_visible(timeout=45000)
        settled(page)
        initial = receipt(page)
        assert initial["period"] == "2026-09" and initial["sources"] == [] and initial["events"] == []
        capture("first-intake-open")
        page.get_by_role("button", name="Done with source files", exact=True).click()
        expect(page.locator(PANEL)).not_to_be_visible()
        refresh(page)
        expect(page.locator(PANEL)).not_to_be_visible()
        assert receipt(page)["fingerprint"] == initial["fingerprint"]
        page.get_by_role("button", name="Manage source files", exact=True).press("Enter")
        expect(page.locator(PANEL)).to_be_visible()
        capture("explicit-reopen")

        record["phase"] = "native synthetic CSV intake and acceptance"
        uploader = page.locator('[data-testid="stFileUploader"]').filter(
            has=page.get_by_text("Add source files", exact=True))
        csv = f"Work Order,Date,Status,Facility\nTEST-001,2026-09-04,Completed,{SITE}\n".encode()
        uploader.locator('input[type="file"]').set_input_files(
            {"name": "synthetic-simplicity-orders.csv", "mimeType": "text/csv", "buffer": csv})
        page.get_by_role("button", name="Add totals to summary", exact=True).click()
        expect(page.locator(PANEL)).not_to_be_visible()
        settled(page)
        assert len(receipt(page)["sources"]) == 1
        capture("accepted-cmms-closed")
        page.get_by_role("button", name="Manage source files", exact=True).click()
        expect(page.locator(PANEL)).to_be_visible()
        refresh(page)
        expect(page.locator(PANEL)).to_be_visible()
        capture("accepted-cmms-reopened")
        page.get_by_role("button", name="Done with source files", exact=True).click()

        record["phase"] = "three sequential native training additions"
        summary = disclosure(page)
        summary.click()  # One initial deliberate open only.
        form_open(page)
        expected, source_baseline = [], receipt(page)["sources"]
        for number in (1, 2, 3):
            fill_training(page, number)
            submit_training(page)
            expected.append([f"Synthetic completed training {number}", f"2026-09-{14 + number:02d}", "In person", PERSON, ""])
            wait_rows(page, expected)
            expect(form_open(page)).to_have_value("")
            assert receipt(page)["sources"] == source_baseline
            capture(f"training-added-{number}-still-open")
        refresh(page)
        expect(form_open(page)).to_have_value("")
        submit_training(page)
        expect(page.get_by_text("Enter a topic", exact=True)).to_be_visible()
        wait_rows(page, expected)
        capture("cleared-submit-no-duplicate")
        topic = form_open(page)
        topic.fill("Synthetic retained invalid entry")
        hours = page.get_by_role("textbox", name="Hours (optional)", exact=True)
        hours.fill("invalid")
        submit_training(page)
        expect(page.get_by_text("Enter positive hours, or leave blank if unknown", exact=True)).to_be_visible()
        expect(topic).to_have_value("Synthetic retained invalid entry")
        expect(hours).to_have_value("invalid")
        wait_rows(page, expected)
        disclosure(page).click()
        form_open(page, False)
        refresh(page)
        form_open(page, False)
        disclosure(page).press("Enter")
        expect(form_open(page)).to_have_value("Synthetic retained invalid entry")
        expect(hours).to_have_value("invalid")
        capture("manual-collapse-reopen-retains-invalid-entry")
        record["phase"] = "narrow viewport retained form and source reentry"
        page.set_viewport_size({"width": 390, "height": 844})
        expect(form_open(page)).to_have_value("Synthetic retained invalid entry")
        page.get_by_role("button", name="Manage source files", exact=True).click()
        expect(page.locator(PANEL)).to_be_visible()
        page.get_by_role("button", name="Done with source files", exact=True).press("Enter")
        expect(page.locator(PANEL)).not_to_be_visible()
        expect(form_open(page)).to_have_value("Synthetic retained invalid entry")
        expect(hours).to_have_value("invalid")
        wait_rows(page, expected)
        capture("narrow-source-reentry-retains-training")
        record["native_window_errors"] = page.evaluate("() => window.__enfraFreshNativeErrors || null")
        require_native_errors_clean(record["native_window_errors"])
        assert not external and not errors, {"external": external, "browser_errors": errors}
        record["result"] = "pass"
        record["completed_task_activations"] = {
            "fresh_intake_open": 0, "initial_training_disclosure_open": 1,
            "post_add_training_disclosure_open": 0, "successful_training_submissions": 3,
            "validation_training_submissions": 2, "total_training_submissions": 5,
            "manual_training_close_reopen_pairs": 1}
        record["inferred_saved_activations"] = {"fresh_intake": 1, "three_training_additions": 2}
    except Exception:
        try:
            record["native_text_inputs"] = page.locator('[data-testid="stTextInput"] input').evaluate_all("""inputs => inputs.map(input => ({
                type: input.type, ariaLabel: input.getAttribute('aria-label'),
                labels: Array.from(input.labels || [], label => label.textContent),
                hiddenByAncestor: Boolean(input.closest('[aria-hidden="true"],[inert]')),
                connected: input.isConnected
            }))""")
            page.screenshot(path=str(OUT / f"{name}-first-failure.png"), full_page=False)
            record["native_window_errors"] = page.evaluate("() => window.__enfraFreshNativeErrors || null")
        except Exception as evidence_error:
            record["failure_capture_error"] = str(evidence_error)[:500]
        raise
    finally:
        record["external_requests"], record["browser_errors"] = external, errors
        if diagnostic:
            try:
                record["delivery_wire"] = wire.rows
                record["delivery_pointer"] = page.evaluate("() => window.__enfraSimplicityPointer || []")
                record["final_receipt"] = page.evaluate("() => { const n=document.querySelector('[data-monthly-simplicity-receipt]'); if(!n) return null; const r=JSON.parse(n.getAttribute('data-monthly-simplicity-receipt')); return {fingerprint:r.fingerprint, sources:r.sources}; }")
            except Exception as error:
                record["diagnostic_capture_failed"] = type(error).__name__
            try:
                from scripts.qa_simplicity_delivery import safe_trace
                with tempfile.TemporaryDirectory(prefix="simplicity-trace-") as trace_root:
                    trace_path = Path(trace_root) / "raw.zip"
                    context.tracing.stop(path=str(trace_path))
                    record["delivery_trace"] = safe_trace(trace_path)
            except Exception:
                pass
        context.close()
        browser.close()


@contextmanager
def server(name):
    with tempfile.TemporaryDirectory(prefix="monthly-simplicity-") as temp:
        (Path(temp) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", EPC_MONTHLY_FRESH_TASK="1", EPC_MONTHLY_SIMPLICITY_TASK="1",
                   ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        with (OUT / f"{name}-streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/monthly_simplicity_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic simplicity server exited")
                    try:
                        with urlopen(URL.split('/?')[0] + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Synthetic simplicity server startup timed out")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"synthetic": True, "ordinary_route": True, "physical_device": False, "engines": [], "failures": []}
    with sync_playwright() as playwright:
        for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
            record = {"engine": name, "steps": []}
            result["engines"].append(record)
            try:
                with server(name):
                    exercise(engine, name, record)
            except Exception as exc:
                record["result"] = "failed"
                record["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
                result["failures"].append(name)
            finally:
                (OUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    if result["failures"]:
        raise AssertionError("Monthly simplicity acceptance failed: " + ", ".join(result["failures"]))
    print("PASS native first intake, accepted CMMS closure/reentry and three sequential Training additions in both engines")


if __name__ == "__main__":
    main()
