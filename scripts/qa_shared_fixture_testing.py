"""Actual hidden shared-fixture browser journey, using invented documents only.

Runs run_web.py unchanged on localhost:8521 with a disposable EPC_DATA_DIR.
Each engine uploads through the real form and takes an independent first
attempt. Expected facts are authored here, never derived from the importer.
No Render traffic, credentials, authentic files, or external actions are used.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "shared-fixture-testing"
ORIGIN = "http://127.0.0.1:8521"
URL = ORIGIN + "/?workflow=monthly&monthly_qa=fixtures"
MARKER = "shared-fixture-dom-synthetic-only.marker"
GUARD_LOG = "blocked-external.jsonl"
SOURCE_TEXT = "Inspected the synthetic pump in October 2026; follow-up is open."
MANUAL_TEXT = "My manually corrected synthetic Activity; follow-up remains open."
REENTRY_TEXT = "Synthetic re-entry after deliberate clearing; follow-up remains open."
EXPECTATION_ONLY = "EXPECTATION_ONLY_CANARY_NOT_SOURCE_CONTENT"
REPORT = {"synthetic_only": True, "actual_entrypoint": "run_web.py",
          "route": "?workflow=monthly&monthly_qa=fixtures",
          "browser_evidence": "Chromium and Playwright WebKit, not shipping Safari",
          "access_policy": "shared with every visitor; no authentication",
          "checks": [], "browsers": {}, "failures": []}


def serve():
    """Harness-only outgoing guard around the unchanged production entrypoint."""
    base = Path(os.environ.get("EPC_DATA_DIR", "")).resolve()
    if (base.parent != Path(tempfile.gettempdir()).resolve()
            or not base.name.startswith("shared-fixture-dom-synthetic-")
            or not (base / MARKER).is_file()
            or (base / MARKER).read_text() != "shared-fixture-dom-v1"):
        raise RuntimeError("This harness requires its own marked disposable storage root")
    guard_log = base / GUARD_LOG

    def denied(name):
        with guard_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"blocked": name}) + "\n")
        raise AssertionError("Shared-fixture browser QA blocked " + name)

    def audit(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo"}:
            return
        address = args[1] if event == "socket.connect" else args[0]
        host = address[0] if isinstance(address, tuple) else address
        if host in {"localhost", "127.0.0.1", "::1", None}:
            return
        try:
            if ipaddress.ip_address(str(host)).is_loopback:
                return
        except ValueError:
            pass
        denied(event + ":non-loopback")

    sys.addaudithook(audit)
    # Fail on invocation, even if a missing API key would prevent charging.
    # These guards live only in this harness process, never production code.
    from app import monthly_report_ai, ocr, smartsheet
    monthly_report_ai.request_json = lambda *_a, **_k: denied("external monthly reader/writer")
    ocr._ocr_request = lambda *_a, **_k: denied("external OCR")
    smartsheet.submit_po = lambda *_a, **_k: denied("Smartsheet submission")
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(ROOT / "run_web.py"),
                "--server.address", "127.0.0.1", "--server.port", "8521",
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    cli.main()


def check(browser, name, passed, details=None):
    REPORT["checks"].append({"browser": browser, "name": name,
                             "passed": bool(passed), "details": details})
    print(("PASS " if passed else "FAIL ") + browser + " " + name, flush=True)
    if not passed:
        raise AssertionError(name + ": " + str(details))


def synthetic_docx():
    from docx import Document
    document = Document()
    document.add_heading("Synthetic Site A", 0)
    document.add_paragraph("October 2026 Monthly Report")
    document.add_heading("2 Monthly Activity Summary", 1)
    document.add_paragraph(SOURCE_TEXT)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def run_directory(base, cookie):
    # Read-only diagnosis of the production namespacing protocol; no namespace
    # or report is created by this helper or prepopulated for the browser.
    token = sha256(("shared-fixture:" + cookie).encode("ascii")).hexdigest()[:32]
    scope = sha256(("monthly-qa-v1:" + token).encode("ascii")).hexdigest()[:32]
    return base / "_enfra_monthly_report_qa_v1" / scope


def journal(root):
    paths = list(root.rglob("working.json")) if root.is_dir() else []
    values = [json.loads(path.read_text()) for path in paths]
    return [value for value in values if value.get("kind") == "browser_active_work_v1"]


def durable_activity(page, root, expected):
    # Poll the actual atomic journal acknowledgment, not a fixed rendering
    # sleep, a repeated user action, or values injected into session state.
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        values = journal(root)
        if len(values) == 1:
            current = values[0]
            text = next((block.get("text", "") for block in current["draft"]["blocks"]
                         if block["key"] == "activity_summary"), "")
            if text == expected:
                return {"revision": current["revision"], "generation": current["generation"],
                        "activity_sha256": sha256(text.encode()).hexdigest()}
        page.wait_for_timeout(100)
    raise AssertionError("The exact Activity edit did not reach its isolated durable journal")


def idle(page):
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
      ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=45000)


def capture(page, name, label):
    page.screenshot(path=str(OUT / f"{name}-{label}.png"), timeout=30000)
    observed = page.evaluate("""() => ({
      headings:[...document.querySelectorAll('h1,h2,h3')].map(n=>n.textContent),
      alerts:[...document.querySelectorAll('[data-testid="stAlert"]')].map(n=>n.textContent),
      textareas:[...document.querySelectorAll('textarea')].map(n=>({label:n.getAttribute('aria-label'),value:n.value})),
      comboboxes:[...document.querySelectorAll('[role="combobox"]')].map(n=>({label:n.getAttribute('aria-label'),tag:n.tagName,value:n.value,text:n.textContent})),
      scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')
    })""")
    REPORT["browsers"].setdefault(name, {}).setdefault("states", {})[label] = observed
    (OUT / "results.json").write_text(json.dumps(REPORT, indent=2))


def exercise(browser_type, name, base):
    from playwright.sync_api import expect
    browser = browser_type.launch(headless=True)
    contexts, attempts, errors = [], [], []
    error_details = []
    phase = {"name": "initial navigation"}

    def session():
        cookie = secrets.token_hex(16)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
        contexts.append(context)
        context.add_cookies([{"name": "epc_device_id", "value": cookie, "url": ORIGIN}])
        context.add_init_script("""window.__sharedFixtureShareAttempts=[];
          Object.defineProperty(navigator,'share',{configurable:true,value:()=>{
            window.__sharedFixtureShareAttempts.push('share');
            return Promise.reject(new Error('Sharing is forbidden in synthetic QA'));
          }});""")

        def route(request):
            parsed = urlparse(request.request.url)
            if parsed.scheme in {"data", "blob"} or (parsed.hostname == "127.0.0.1" and parsed.port == 8521):
                request.continue_()
            else:
                attempts.append(parsed.scheme + ":" + (parsed.hostname or "external"))
                request.abort()
        context.route("**/*", route)
        page = context.new_page()
        role = "primary" if len(contexts) == 1 else "coworker"
        page.set_default_timeout(20000)
        def browser_exception(error):
            # Metadata only; synthetic browser harness. Retain every error as
            # a hard failure, but identify which operator action canceled it.
            errors.append(str(error))
            error_details.append({"browser": role, "stage": phase["name"],
                                  "message": str(error)[:500],
                                  "stack": str(getattr(error, "stack", ""))[:1600]})
        page.on("pageerror", browser_exception)
        page.goto(URL, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", name="Shared report testing", exact=True)).to_be_visible(timeout=60000)
        return page, cookie

    page = None
    try:
        page, cookie = session()
        root = run_directory(base, cookie)
        expect(page.get_by_text(re.compile(r"^Anyone with this link can upload, view and download"))).to_be_visible()
        original = synthetic_docx()
        digest = sha256(original).hexdigest()
        friendly = "Synthetic partial report " + name
        page.get_by_text("Upload an actual report", exact=True).click()
        upload = page.locator('[data-testid="stFileUploader"]').filter(
            has=page.get_by_text("Original Word report", exact=True))
        upload.locator('input[type="file"]').set_input_files({
            "name": name + "-invented-partial.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": original})
        page.get_by_role("combobox", name="Scenario", exact=True).click()
        page.get_by_role("option", name="Half-finished report, correct month", exact=True).click()
        for label, value in {
            "Fixture name": friendly, "Exact contract": "Synthetic Testing Contract",
            "Source sites": "Synthetic Site A", "Target sites": "Synthetic Site A",
            "Source month (YYYY-MM)": "2026-10", "Target month (YYYY-MM)": "2026-10",
            "Scenario notes": "Independently authored: preserve current incomplete pump work; do not invent completion.",
            "Expected results": "Activity | include | synthetic pump\nActivity | exclude | " + EXPECTATION_ONLY,
        }.items():
            page.get_by_role("textbox", name=label, exact=True).fill(value)
        partial = page.get_by_role("checkbox", name="For the partial-report scenario, I confirm this is the actual half-finished file", exact=True)
        partial.locator("xpath=ancestor::label[1]").click()
        expect(partial).to_be_checked()
        page.get_by_role("button", name="Save shared fixture", exact=True).click()
        shared = page.get_by_role("combobox", name="Shared fixture", exact=True)
        expect(shared).to_be_visible(timeout=45000)
        # Streamlit 1.61.1 renders the selected label as the accessible
        # combobox input value, not as a text node. Assert that precise value
        # and the immutable receipt, rather than waiting on get_by_text.
        expect(shared).to_have_value(re.compile(r"^" + re.escape(friendly) + r" · [0-9a-f]{8}$"), timeout=45000)
        manifests = [json.loads(path.read_text()) for path in
                     (base / "_enfra_shared_fixtures_v1").glob("*/manifest.json")]
        matches = [value for value in manifests if value["metadata"]["friendly_name"] == friendly]
        check(name, "selected upload has one durable immutable receipt", len(matches) == 1
              and matches[0]["original_sha256"] == digest
              and matches[0]["original_size"] == len(original))
        saved = matches[0]
        check(name, "selected fixture identity matches durable receipt",
              shared.input_value() == friendly + " · " + saved["fixture_id"][:8])
        REPORT["browsers"].setdefault(name, {})["uploaded_receipt"] = saved
        page.get_by_text("Confirmed source, target and expected results", exact=True).click()
        expect(page.get_by_text("Original SHA256: " + digest, exact=True)).to_be_visible()
        check(name, "real browser upload saved immutable synthetic original", True,
              {"sha256": digest, "size": len(original), "scenario": "AUTH03", "target": "Synthetic Testing Contract / Synthetic Site A / 2026-10"})

        def download_original(label, current=page):
            # The selected combobox can show its new value before Streamlit
            # commits the rerun that changes the binary download resource.
            # Require the exact fixture/hash-scoped native action to be
            # mounted before the one real download. This is not a retry or a
            # weaker byte assertion: an obsolete or mismatched action fails.
            scope = saved["fixture_id"] + "_" + digest[:16]
            expected_widget = current.locator(".st-key-_shared_fixture_download_" + scope)
            expect(expected_widget).to_be_visible(timeout=45000)
            idle(current)
            with current.expect_download(timeout=30000) as event:
                current.get_by_role("button", name="Download unchanged original", exact=True).click()
            downloaded = event.value
            path = OUT / f"{name}-{label}-original.docx"
            downloaded.save_as(path)
            check(name, label + " original bytes and hash unchanged", path.read_bytes() == original
                  and sha256(path.read_bytes()).hexdigest() == digest)

        download_original("uploaded")
        coworker, coworker_cookie = session()
        coworker_root = run_directory(base, coworker_cookie)
        coworker.get_by_role("combobox", name="Shared fixture", exact=True).click()
        coworker.get_by_role("option", name=re.compile(r"^" + re.escape(friendly) + r" · ")).click()
        expect(coworker.get_by_role("button", name="Download unchanged original", exact=True)).to_be_visible()
        check(name, "second browser sees shared fixture without inheriting first browser run",
              coworker.get_by_role("textbox", name="Activity summary", exact=True).count() == 0
              and root != coworker_root and not journal(coworker_root))
        coworker_generation = (coworker_root / ".enfra-qa-namespace").read_text()
        download_original("coworker", coworker)

        phase["name"] = "start real Starting report importer"
        page.get_by_role("button", name="Start fresh test with this fixture", exact=True).click()
        actor = page.get_by_role("textbox", name="Your name", exact=True)
        expect(actor).to_be_visible(timeout=60000)
        staged_original = root / "_enfra_fixture_start_v1" / "starting-report" / "source.docx"
        lineage = json.loads(staged_original.with_name("lineage.json").read_text())
        check(name, "fresh Starting report uses byte-identical copy with confirmed target lineage",
              staged_original.read_bytes() == original
              and lineage["original_sha256"] == digest
              and lineage["metadata"]["scenario"] == "AUTH03"
              and lineage["metadata"]["target"] == {
                  "contract": "Synthetic Testing Contract", "sites": ["synthetic-site-a"],
                  "month": "2026-10", "site_titles": ["Synthetic Site A"]})
        actor.fill("Synthetic Reviewer")
        actor.press("Tab")
        proceed = page.get_by_role("button", name="Continue to this month’s updates", exact=True)
        expect(proceed).to_be_enabled(timeout=45000)
        capture(page, name, "production-starting-review")
        phase["name"] = "enter ordered report/editor after import"
        proceed.click()
        activity = page.get_by_role("textbox", name="Activity summary", exact=True)
        expect(activity).to_be_visible(timeout=90000)
        expect(activity).to_have_value(re.compile(re.escape(SOURCE_TEXT)), timeout=30000)
        check(name, "production Starting report imported source text rather than expectations",
              SOURCE_TEXT in activity.input_value() and EXPECTATION_ONLY not in activity.input_value())
        capture(page, name, "imported-current-report")

        # The native Streamlit multiline control presents Ctrl+Enter as its
        # explicit apply gesture. Exercise keyboard clearing that way instead
        # of depending only on WebKit's sometimes-interrupted Tab/blur event.
        # Neither action is accepted until its EXACT empty journal is durable.
        for label, wording, mode in (
            ("manual-edit", MANUAL_TEXT, "tab"),
            ("intentional-keyboard-clear", "", "apply"),
            ("reentry", REENTRY_TEXT, "tab"),
            ("explicit-report-clear", "", "button"),
            ("reentry-after-report-clear", REENTRY_TEXT, "tab"),
        ):
            phase["name"] = label + ": native edit"
            if mode == "button":
                # After the prior page reload a visible textarea can arrive
                # before Streamlit finishes wiring actions. Do not dispatch
                # an intentional Clear into that transient render; require
                # the actual app's idle signal, then one native button click.
                idle(page)
                clear = page.get_by_role("button", name="Clear Activity for this report", exact=True)
                expect(clear).to_be_enabled()
                clear.click()
            else:
                activity.fill(wording)
                expect(activity).to_have_value(wording)
                if mode == "apply":
                    activity.press("ControlOrMeta+Enter")
                else:
                    activity.press("Tab")
            receipt = durable_activity(page, root, wording)
            idle(page)
            phase["name"] = label + ": browser reload"
            page.reload(wait_until="domcontentloaded")
            expect(activity).to_be_visible(timeout=60000)
            expect(activity).to_have_value(wording, timeout=30000)
            # Value visibility is not a guarantee that Streamlit has finished
            # hydrating the next editor action after reload. Require the app's
            # completed rerun before taking a new operator action.
            idle(page)
            phase["name"] = label + ": loaded and idle"
            check(name, label + " survives ordinary refresh with exact canonical draft", True, receipt)
            check(name, label + " does not reopen Starting report or duplicate editor",
                  page.get_by_role("textbox", name="Your name", exact=True).count() == 0 and activity.count() == 1)
        capture(page, name, "reentry-after-refresh")
        phase["name"] = "coworker reload"
        coworker.reload(wait_until="domcontentloaded")
        expect(coworker.get_by_role("heading", name="Shared report testing", exact=True)).to_be_visible(timeout=60000)
        check(name, "edited report remains isolated from coworker", not journal(coworker_root)
              and coworker.get_by_role("textbox", name="Activity summary", exact=True).count() == 0)
        old_generation = (root / ".enfra-qa-namespace").read_text()
        phase["name"] = "reset primary workspace"
        page.get_by_role("button", name="Reset this test workspace", exact=True).click()
        expect(activity).to_have_count(0, timeout=45000)
        idle(page)
        check(name, "scoped reset replaces run generation and removes editable run", not journal(root)
              and (root / ".enfra-qa-namespace").read_text() != old_generation)
        check(name, "reset leaves coworker namespace unchanged",
              (coworker_root / ".enfra-qa-namespace").read_text() == coworker_generation)
        # Selection is intentionally disposable on reset. Select the original
        # explicitly before proving its shared bytes still exist unchanged.
        phase["name"] = "select and download original after reset"
        page.get_by_role("combobox", name="Shared fixture", exact=True).click()
        page.get_by_role("option", name=re.compile(r"^" + re.escape(friendly) + r" · ")).click()
        download_original("after-reset")
        capture(page, name, "reset-original-retained")
        check(name, "zero external browser requests", not attempts, attempts)
        check(name, "no browser errors", not errors, errors)
        check(name, "no sharing action", all(not p.evaluate("window.__sharedFixtureShareAttempts")
                                             for c in contexts for p in c.pages))
    except Exception:
        if page is not None:
            try:
                capture(page, name, "failure")
            except Exception as capture_error:
                REPORT["browsers"].setdefault(name, {})["capture_error"] = str(capture_error)[:500]
        REPORT["browsers"].setdefault(name, {})["traceback"] = traceback.format_exc()
        raise
    finally:
        REPORT["browsers"].setdefault(name, {}).update({
            "external_attempts": attempts, "browser_errors": errors,
            "page_error_details": error_details})
        for context in contexts:
            context.close()
        browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    completed = False
    with tempfile.TemporaryDirectory(prefix="shared-fixture-dom-synthetic-") as temp:
        base = Path(temp)
        (base / MARKER).write_text("shared-fixture-dom-v1")
        (base / GUARD_LOG).write_text("")
        env = dict(os.environ, EPC_DATA_DIR=temp, ANTHROPIC_API_KEY="", OPENAI_API_KEY="",
                   SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Production shared-fixture app stopped during startup")
                    try:
                        with urllib.request.urlopen(ORIGIN + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Production shared-fixture app did not become healthy")
                with sync_playwright() as playwright:
                    for engine, name in ((playwright.chromium, "chromium"), (playwright.webkit, "playwright-webkit")):
                        try:
                            exercise(engine, name, base)
                        except Exception as exc:
                            REPORT["failures"].append(name + ": " + type(exc).__name__ + ": " + str(exc)[:500])
                allowed = {MARKER, GUARD_LOG, "_enfra_monthly_report_qa_v1", "_enfra_shared_fixtures_v1",
                           "_enfra_shared_fixture_runs_v1", "_enfra_fixture_run_admission_v1"}
                check("server", "all persisted data stays in explicit shared/test buckets",
                      not (set(p.name for p in base.iterdir()) - allowed), sorted(p.name for p in base.iterdir()))
                blocked = [json.loads(line) for line in (base / GUARD_LOG).read_text().splitlines()]
                check("server", "zero external reader, OCR, submission or network invocations", not blocked, blocked)
                completed = True
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                REPORT["result"] = "passed" if completed and not REPORT["failures"] else "failed"
                (OUT / "results.json").write_text(json.dumps(REPORT, indent=2))
    if REPORT["failures"]:
        raise AssertionError("Shared fixture browser failures: " + "; ".join(REPORT["failures"]))


if __name__ == "__main__":
    serve() if "--serve" in sys.argv else main()
