"""Actual Water upload/review/removal/reload journey inside existing synthetic QA.

Reuses qa_monthly_adaptive's guarded localhost server and browser geometry.
No production route, paid reader, live storage, hidden state injection or retry.
"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from zipfile import ZipFile
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf
from playwright.sync_api import expect

WATER = ".st-key-epc_pair_monthly_water"
CAPTION = "Synthetic conductivity check; follow-up remains pending."
NAME = "Synthetic water treatment - long source name for the September review.pdf"


def source_pdf():
    with pymupdf.open() as pdf:
        for number in (1, 2):
            page = pdf.new_page()
            page.insert_text((45, 65), "TEST ONLY - ALL RECORDS INVENTED", fontsize=18)
            page.insert_text((45, 110), "Water treatment")
            page.insert_text((45, 140), "Facility: Demo North")
            page.insert_text((45, 170), "Service date: 2026-09-17")
            page.insert_text((45, 200), "Vendor: Synthetic Chemical Vendor")
            page.insert_text((45, 240), f"Synthetic water page {number}: conductivity inspected.")
            page.insert_text((45, 275), "Follow-up sample remains pending.")
        return pdf.tobytes()


def receipt(page):
    node = page.locator("[data-enfra-water-receipt]").last
    return json.loads(node.get_attribute("data-enfra-water-receipt"))


def wait_pages(page, order, *, pending=None):
    page.wait_for_function("""wanted => {
      const nodes=document.querySelectorAll('[data-enfra-water-receipt]');
      if(!nodes.length)return false;
      const s=JSON.parse(nodes[nodes.length-1].dataset.enfraWaterReceipt);
      const numbers=part=>part.pages.map(p=>p.source_pages.length===1?p.source_pages[0][1]:null);
      return JSON.stringify(numbers(s.working))===JSON.stringify(wanted.order) &&
        JSON.stringify(s.working)===JSON.stringify(s.durable) &&
        s.working_fingerprint===s.durable_fingerprint &&
        (!wanted.check_pending||JSON.stringify(s.working.pending)===JSON.stringify(wanted.pending)) &&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={"order": order, "check_pending": pending is not None,
            "pending": pending if pending is not None else []}, timeout=45000)
    return receipt(page)


def choose_page(page, number):
    water = page.locator(WATER)
    control = water.get_by_role("combobox", name="Page to review", exact=True)
    control.click()
    page.get_by_role("option", name=re.compile(r"^Page " + str(number) + r"(?: ·|$)")).click()
    expect(control).to_have_value(re.compile(r"^Page " + str(number) + r"(?: ·|$)"))


def upload(page, raw):
    page.locator(WATER).get_by_role("button", name="Add files", exact=True).click()
    uploader = page.locator('[data-testid="stFileUploader"]').filter(
        has=page.get_by_text("Water-treatment files", exact=True))
    uploader.locator('input[type="file"]').set_input_files(
        {"name": NAME, "mimeType": "application/pdf", "buffer": raw})
    expect(page.locator(WATER).get_by_text("Reviewing " + NAME, exact=True)).to_be_visible(timeout=45000)
    page.keyboard.press("Escape")


def exercise(page, name, qa):
    """One desktop task continued on narrow mobile, including real native output."""
    raw = source_pdf()
    source_hash = sha256(raw).hexdigest()
    out = qa.OUT / (name + "-water")
    out.mkdir(parents=True, exist_ok=True)
    (out / "unchanged-synthetic-source.pdf").write_bytes(raw)
    observations = {"source_sha256": source_hash, "source_bytes": len(raw),
                    "desktop": {"width": 1365, "height": 900},
                    "narrow": {"width": 390, "height": 844}, "steps": []}

    def record(stage, state):
        observations["steps"].append({"stage": stage, "receipt": state})
        (out / "task.json").write_text(json.dumps(observations, indent=2))
        qa.capture(page, name, "water-" + stage)

    def unchanged(state):
        assert state["originals"] == [{"id": source_hash, "sha256": source_hash, "size": len(raw)}]
        assert state["working"]["unrelated_sha256"] == baseline
        assert state["working"] == state["durable"]

    try:
        page.set_viewport_size({"width": 1365, "height": 900})
        qa.mode(page, "wide")
        water = page.locator(WATER)
        qa.scroll_pair(page, WATER)
        initial = wait_pages(page, [])
        baseline = initial["working"]["unrelated_sha256"]
        record("before-upload", initial)
        upload(page, raw)
        expect(water.get_by_role("button", name="Include page and continue", exact=True)).to_be_enabled()
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        expect(water.get_by_role("combobox", name="Page to review", exact=True)).to_have_value(re.compile(r"^Page 2(?: ·|$)"))
        state = wait_pages(page, [])
        unchanged(state)
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        state = wait_pages(page, [1, 2], pending=[])
        unchanged(state)
        assert len(state["working"]["sources"]) == 1
        expect(water.get_by_role("button", name="Add reviewed pages", exact=True)).to_have_count(0)
        expect(water.get_by_role("button", name="View or change pictures", exact=True)).to_have_count(0)
        qa.current_image(page, WATER)
        record("desktop-included", state)

        water.get_by_role("button", name="Edit pages", exact=True).click()
        choose_page(page, 1)
        caption = water.get_by_role("textbox", name="Page caption", exact=True)
        caption.fill(CAPTION)
        caption.press("Tab")
        state = wait_pages(page, [1, 2], pending=[0])
        assert state["working"]["pages"][0]["caption_sha256"] == sha256(CAPTION.encode()).hexdigest()
        unchanged(state)
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        wait_pages(page, [1, 2], pending=[])
        water.get_by_role("button", name="Move page later", exact=True).click()
        state = wait_pages(page, [2, 1], pending=[])
        unchanged(state)
        record("desktop-caption-order", state)
        water.get_by_role("button", name="Leave page out and continue", exact=True).click()
        state = wait_pages(page, [2], pending=[])
        unchanged(state)
        assert state["working"]["sources"][0]["excluded"] == [1]
        record("desktop-omitted", state)

        page.reload(wait_until="domcontentloaded")
        state = wait_pages(page, [2], pending=[])
        unchanged(state)
        page.set_viewport_size({"width": 390, "height": 844})
        qa.mode(page, "compact")
        qa.scroll_pair(page, WATER, inset=90)
        upload(page, raw)  # Same bytes after a genuine new browser session.
        state = wait_pages(page, [2], pending=[])
        unchanged(state)
        assert state["working"]["sources"][0]["excluded"] == [1]
        record("narrow-repeat-keeps-omission", state)
        water.get_by_role("button", name="Edit pages", exact=True).click()
        choose_page(page, 1)
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        state = wait_pages(page, [2, 1], pending=[])
        unchanged(state)
        assert state["working"]["sources"][0]["excluded"] == []
        assert len(set(p["asset"] for p in state["working"]["pages"])) == 2
        assert page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+2")
        record("narrow-reincluded", state)
        page.reload(wait_until="domcontentloaded")
        state = wait_pages(page, [2, 1], pending=[])
        unchanged(state)
        qa.scroll_pair(page, WATER, inset=90)
        water.get_by_role("button", name="View preview", exact=True).click()
        qa.current_image(page, WATER)
        record("narrow-current-preview", state)
        water.get_by_role("button", name="Back to editing", exact=True).click()

        from scripts import qa_monthly_live as live
        live.ROOT = out
        live.EVIDENCE = {"checks": {}, "events": [], "artifacts": {}, "synthetic_only": True}
        live.request_qa_generation(page, "water-page-journey")
        word = live.download(page, "Download isolated QA DOCX", "water-pages.docx")
        pdf = live.download(page, "Download isolated QA PDF", "water-pages.pdf")
        with ZipFile(BytesIO(word)) as package:
            from lxml import etree
            xml = etree.fromstring(package.read("word/document.xml"))
            text = "\n".join(xml.xpath('//*[local-name()="t"]/text()'))
            assert text.count(CAPTION) == 1
            media = {sha256(package.read(n)).hexdigest() for n in package.namelist() if n.startswith("word/media/")}
            for item in state["working"]["pages"]:
                assert item["asset"].split(".")[0] in media
        with pymupdf.open(stream=pdf, filetype="pdf") as document:
            assert sum(p.get_text().count(CAPTION) for p in document) == 1
            observations["output_pdf_pages"] = len(document)
        observations["exports"] = live.EVIDENCE
        observations["result"] = "passed"
        qa.check(name, "Water native upload/review/order/omit/reload/reinclude and actual Word/PDF", True)
    except Exception as exc:
        observations["result"] = "failed"
        observations["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            observations["last_receipt"] = receipt(page)
            qa.capture(page, name, "water-first-failure")
        except Exception:
            pass
        raise
    finally:
        (out / "task.json").write_text(json.dumps(observations, indent=2))


def browser_task(browser_type, name):
    import secrets
    from urllib.parse import urlparse
    from scripts import qa_monthly_adaptive as qa
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": qa.URL}])
    attempts, errors = [], []
    def route(request):
        address = urlparse(request.request.url)
        if address.scheme in {"data", "blob"} or (address.hostname == "127.0.0.1" and address.port == 8520):
            request.continue_()
        else:
            attempts.append(address.hostname)
            request.abort()
    context.route("**/*", route)
    context.add_init_script("""window.__waterShareAttempts=[];
      Object.defineProperty(navigator,'share',{configurable:true,value:()=>{
        window.__waterShareAttempts.push('share');
        return Promise.reject(new Error('Sharing is forbidden in synthetic QA'));
      }});""")
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    out = qa.OUT / (name + "-water")
    out.mkdir(parents=True, exist_ok=True)
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    try:
        page.goto(qa.URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
        expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_be_visible(timeout=45000)
        exercise(page, name, qa)
        qa.check(name, "Water task has no external request, browser error or sharing",
                 not attempts and not errors and not page.evaluate("window.__waterShareAttempts.length"),
                 {"external": attempts, "errors": errors})
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
    finally:
        (out / "browser.json").write_text(json.dumps({"external": attempts, "errors": errors}, indent=2))
        context.tracing.stop(path=str(out / "browser-trace.zip"))
        context.close()
        browser.close()


def main():
    # Reuse only the established disposable server lifecycle, network boundary,
    # timeout and cleanup. The existing adaptive exercise remains unchanged and
    # still runs separately in CI. This is a new independently reported task.
    from scripts import qa_monthly_adaptive as qa
    qa.OUT = qa.ROOT / "test-artifacts" / "water-page-journey"
    qa.REPORT = {"synthetic_only": True, "actual_workflow": "production guided Water editor",
                 "browsers": {}, "checks": [], "physical_device": False}
    qa.exercise = browser_task
    qa.main()


if __name__ == "__main__":
    # Direct script invocation also needs the repository on sys.path.
    main()
