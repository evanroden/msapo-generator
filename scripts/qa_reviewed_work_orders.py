"""Native source upload/correction/reopen/output journey, synthetic storage only."""
from dataclasses import asdict
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
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "reviewed-work-orders"
PORT = 8543
URL = f"http://127.0.0.1:{PORT}"
PREFIX = "reviewed_source_browser"
RECEIPT = "data-reviewed-work-order-receipt"
CSV = (b'Work Order,Site,Date,Finish Date,Area,Task,Tag,Status,Type,Trade\n'
       b'000001,Demo North,2026-09-03,2026-09-03,Plant,"Inspect pump\nRecord pressure",P-1,Open,PM,HVAC\n'
       b'000002,Demo North,2026-09-04,2026-09-04,Plant,Test valve,V-2,Closed,Repair,Plumbing\n')
TASK = "Inspect pump\nPressure checked through native controls"


def state(draft):
    blocks = {b.key: b for b in draft.blocks}
    reviews = [json.loads(value) for value in draft.source_row_reviews]
    return {"fingerprint": draft.fingerprint, "reviews": len(draft.source_row_reviews),
        "sources": [{"id": source.id, "date": source.service_date, "facility": source.facility}
                    for source in draft.sources],
        "records": {r["kind"]: r["groups"][0]["record"]["review"]["rows"] for r in reviews},
        "workorders": [asdict(t) for t in blocks["work_orders"].extra_tables],
        "maintenance": [asdict(t) for t in blocks["service_calls"].extra_tables],
        "manual": blocks["activity_summary"].text}


def receipt(page):
    return json.loads(page.locator("[" + RECEIPT + "]").get_attribute(RECEIPT))


def settled(page, predicate):
    from playwright.sync_api import expect
    expect(page.locator("[" + RECEIPT + "]")).to_have_count(1)
    page.wait_for_function("([name, predicate]) => {const e=document.querySelector('['+name+']'); return e && document.querySelector('[data-testid=stApp]')?.getAttribute('data-test-script-state')==='notRunning' && Function('v','return ('+predicate+')(v)')(JSON.parse(e.getAttribute(name)));}",
        arg=[RECEIPT, predicate], timeout=25000)
    assert page.get_by_test_id("stException").count() == 0
    return receipt(page)


def select(page, label, option):
    # This journey deliberately uses the native keyboard opener. Pointer
    # dropdown/scroll behavior has its own repository-wide browser gate.
    # Locator.press does not scroll its target into view. Opening an offscreen
    # popup and letting the later option click scroll it closes the native
    # overlay before that click can land, especially after a narrow reload.
    control = page.get_by_role("combobox", name=label, exact=True)
    control.scroll_into_view_if_needed()
    settled(page, "v=>true")
    control.press("ArrowDown")
    page.get_by_role("option", name=option, exact=True).click()


def include(page, name):
    checkbox = page.get_by_test_id("stCheckbox").filter(has_text=name)
    checkbox.click()  # Native visible label, not the clipped accessibility input.


def validate_output(word, pdf):
    from docx import Document
    import pymupdf
    document = Document(BytesIO(word))
    tables = [tuple(tuple(c.text for c in row.cells) for row in t.rows) for t in document.tables]
    work = next(t for t in tables if t[0][0] == "Work order")
    counts = next(t for t in tables if t[0][0] == "Uploaded row sample")
    calls = next(t for t in tables if t[0][0] == "WO #")
    assert [row[0] for row in work[1:]] == ["000001", "000002"]
    assert [row[4] for row in work[1:]] == ["Completed", "Completed"]
    assert [row[0] for row in calls[1:]] == ["000001", "000002"]
    assert calls[1][3] == TASK
    assert counts[1:] == (
        ("All reviewed rows in scope", "2", "2", "0"),
        ("PM", "1", "1", "0"),
        ("Non-PM", "1", "1", "0"),
        ("Unclassified work type", "0", "0", "0"),
    )
    with pymupdf.open(stream=pdf, filetype="pdf") as rendered:
        text = "\n".join(page.get_text() for page in rendered)
    assert text.count("000001") == text.count("000002") == 2
    # PDF extraction exposes visual line wrapping inside the narrow task cell.
    # Keep exact multiline text above for Word; preserve word order/content here.
    assert " ".join(TASK.split()) in " ".join(text.split())
    return {"docx_sha256": sha256(word).hexdigest(), "pdf_sha256": sha256(pdf).hexdigest()}


OBSERVER = """(() => {window.reviewedRowEvents=[]; for(const type of ['keydown','input','click'])
 document.addEventListener(type,e=>{const n=e.target;if(n.matches('input,textarea,button'))
 window.reviewedRowEvents.push({type,key:e.key||'',trusted:e.isTrusted,label:n.getAttribute('aria-label')||n.textContent?.slice(0,80)});},true);})() """


def exercise(browser, name):
    from playwright.sync_api import expect
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    record = {"browser": name, "passed": False, "errors": [], "external": []}
    def route(request):
        if urlparse(request.request.url).hostname not in {"127.0.0.1", "localhost"}:
            record["external"].append(request.request.url)
            request.abort()
        else:
            request.continue_()
    context.route("**/*", route)
    context.add_init_script(OBSERVER)
    context.tracing.start(screenshots=True, snapshots=True)
    page = context.new_page()
    page.on("pageerror", lambda error: record["errors"].append(str(error)))
    try:
        page.goto(URL, wait_until="domcontentloaded")
        settled(page, "v=>v.working.reviews===0")
        page.locator('input[type="file"]').set_input_files({"name": "synthetic-cmms.csv", "mimeType": "text/csv", "buffer": CSV})
        start = page.get_by_role("button", name="Review and correct imported rows", exact=True)
        expect(start).to_be_visible(timeout=25000)
        # Source scope is a real source-details action, not a fixture override.
        # Source details may be in a collapsed expander. A visible-only count
        # silently skipped this required native review in the WIP journey.
        facility = page.get_by_role("combobox", name="Source facility", exact=True, include_hidden=True)
        expect(facility).to_have_count(1)
        panel = page.get_by_test_id("stExpander").filter(has=facility)
        if not panel.evaluate("n=>(n.matches('details')?n:n.querySelector('details')).open"):
            panel.locator("summary").click()
        select(page, "Source facility", "Demonstration North Facility")
        source_date = panel.get_by_test_id("stDateInput").get_by_role("textbox")
        source_date.fill("2026-09-04")
        source_date.press("Tab")
        page.get_by_role("button", name="Use these source details", exact=True).click()
        settled(page, "v=>v.working.sources.length===1 && v.working.sources[0].date==='2026-09-04' && v.working.sources[0].facility==='north'")
        start.click()
        settled(page, "v=>v.working.reviews===1")
        status = page.get_by_role("textbox", name="Recorded status", exact=True)
        expect(status).to_have_value("Open")
        status.fill("Completed")
        status.press("Tab")
        page.get_by_role("button", name="Save row correction", exact=True).click()
        settled(page, "v=>v.working.records.workorders[0].status==='Completed'")
        expect(page.get_by_role("textbox", name="Recorded status", exact=True)).to_have_value("Completed")
        include(page, "Include Work Orders in this report")
        page.get_by_role("button", name="Include reviewed rows in Activity", exact=True).click()
        settled(page, "v=>v.working.workorders.length===2 && v.working.workorders[1].rows[0].slice(-3).join(',')==='2,2,0'")
        select(page, "Use these records for", "Completed in-house maintenance calls")
        start.click()
        settled(page, "v=>v.working.reviews===2")
        task = page.get_by_role("textbox", name="Work performed", exact=True)
        expect(task).to_have_value("Inspect pump\nRecord pressure")
        task.fill(TASK)
        page.get_by_role("textbox", name="Recorded status", exact=True).fill("Completed")
        page.get_by_role("button", name="Save row correction", exact=True).click()
        settled(page, "v=>v.working.records.maintenance[0].task.includes('Pressure checked through native controls')")
        expect(page.get_by_role("textbox", name="Work performed", exact=True)).to_have_value(TASK)
        include(page, "Include Maintenance calls in this report")
        page.get_by_role("button", name="Include reviewed rows in Maintenance", exact=True).click()
        settled(page, "v=>v.working.reviews===2 && v.working.maintenance.length===1 && v.working.maintenance[0].rows.length===2")
        page.get_by_role("button", name="Done with source files", exact=True).click()
        page.get_by_role("button", name="Manage source files", exact=True).click()
        expect(page.get_by_role("textbox", name="Work performed", exact=True)).to_have_value(TASK)
        page.get_by_role("button", name="Save synthetic report", exact=True).click()
        baseline = settled(page, "v=>v.saved && v.saved.fingerprint===v.working.fingerprint && v.revision===1")
        assert baseline["originals_unchanged"]
        page.screenshot(path=str(out / "saved-desktop.png"), full_page=True)
        record["before_reload_events"] = page.evaluate("window.reviewedRowEvents")
        assert any(e["type"] == "keydown" and e["key"] == "Tab" and e["trusted"] for e in record["before_reload_events"])
        page.set_viewport_size({"width": 545, "height": 757})
        page.reload(wait_until="domcontentloaded")
        reopened = settled(page, "v=>v.saved && v.saved.fingerprint===v.working.fingerprint && v.working.reviews===2")
        assert reopened == baseline
        assert page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+2")
        page.get_by_role("button", name="Manage source files", exact=True).click()
        select(page, "Use these records for", "Completed in-house maintenance calls")
        expect(page.get_by_role("textbox", name="Work performed", exact=True)).to_have_value(TASK)
        page.get_by_role("button", name="Include reviewed rows in Maintenance", exact=True).click()
        assert settled(page, "v=>v.saved && v.saved.fingerprint===v.working.fingerprint") == baseline
        page.get_by_role("button", name="Generate synthetic Word and PDF", exact=True).click()
        outputs = {}
        for kind, extension in (("Word", "docx"), ("PDF", "pdf")):
            button = page.get_by_role("button", name="Download synthetic " + kind, exact=True)
            expect(button).to_be_visible(timeout=120000)
            with page.expect_download(timeout=120000) as event:
                button.click()
            target = out / ("reviewed." + extension)
            event.value.save_as(target)
            outputs[extension] = target.read_bytes()
        record["outputs"] = validate_output(outputs["docx"], outputs["pdf"])
        assert receipt(page) == baseline
        page.screenshot(path=str(out / "reopened-narrow.png"), full_page=True)
        assert not record["errors"] and not record["external"]
        record["passed"] = True
    except Exception as error:
        record["first_failure"] = str(error)
        record["traceback"] = traceback.format_exc()
        page.screenshot(path=str(out / "first-failure.png"), full_page=True)
        (out / "first-failure.html").write_text(page.content())
        raise
    finally:
        (out / "result.json").write_text(json.dumps(record, indent=2))
        context.tracing.stop(path=str(out / "trace.zip"))
        context.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reviewed-work-orders-synthetic-") as directory:
        base = Path(directory)
        (base / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
        env = dict(os.environ, EPC_DATA_DIR=str(base), EPC_MONTHLY_DOM_FIXTURE="1",
            EPC_REVIEWED_WORK_ORDER_FIXTURE="1", ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled",
            STREAMLIT_GLOBAL_DEVELOPMENT_MODE="false")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/reviewed_work_orders_app.py", "--server.address", "127.0.0.1",
                "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic server stopped")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Synthetic server did not become healthy")
                failures = []
                with sync_playwright() as playwright:
                    for name in os.environ.get("REVIEWED_ROW_BROWSERS", "chromium,webkit").split(","):
                        if name not in {"chromium", "webkit"}:
                            raise ValueError("Unknown browser engine")
                        browser = getattr(playwright, name).launch(headless=True)
                        try:
                            exercise(browser, name)
                        except Exception as error:
                            failures.append(f"{name}: {error}")
                        finally:
                            browser.close()
                if failures:
                    raise AssertionError("; ".join(failures))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    print("PASS native reviewed rows, saved reopen and actual Word/PDF")


if __name__ == "__main__":
    main()
