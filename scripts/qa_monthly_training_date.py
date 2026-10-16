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
from scripts.qa_training_date_delivery import TrainingDateDelivery

OUT = ROOT / "test-artifacts" / "monthly-training-date"
PORT = 8535
URL = f"http://127.0.0.1:{PORT}"
TITLE = "Synthetic hospital emergency preparedness and life safety refresher"
PARTICIPANT = "Synthetic Person North"
ROW = [TITLE, "2026-09-15", "In person", PARTICIPANT, ""]
RECEIPT = '[data-enfra-training-receipt]'
READY = """() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'"""
DATE_EVENTS = """(() => {
  const events = [], nodes = new WeakMap(); let sequence = 0;
  window.__enfraTrainingDateEvents = events;
  for (const type of ['focus','beforeinput','input','change','blur','keydown']) {
    document.addEventListener(type, event => {
      const target = event.target;
      if (!target?.matches?.('[data-testid="stDateInputField"]')) return;
      if (!nodes.has(target)) nodes.set(target, ++sequence);
      events.push({type, at:performance.now(), trusted:event.isTrusted, node:nodes.get(target),
        value:target.value.slice(0,20), start:target.selectionStart, end:target.selectionEnd,
        focused:target===document.activeElement, inputType:event.inputType||null,
        data:typeof event.data==='string'?event.data.slice(0,16):null,
        key:type==='keydown'?event.key:null});
      if (events.length > 80) events.shift();
    }, {capture:true,passive:true});
  }
})();"""


def _date_input_state(field):
    return field.evaluate("""input=>({value:input.value,start:input.selectionStart,
      end:input.selectionEnd,focused:input===document.activeElement})""")


def replace_date(page, field, value, stage):
    """Replace text through the actual input's normal keyboard edit sequence.

    Atomic ``fill`` selects and inserts before the locked mask refreshes its
    animation-frame selection cache. A partial date can therefore keep its old
    month even when beforeinput has the correct selected range. Deletion and
    each typed character run the native change handler, which synchronously
    updates that cache. The pointer focus/mouseup handlers also defer a cursor
    restore to the next frame, so observe their completion before selecting.
    This is the initial edit, never a rescue after submit.
    """
    observation = {"stage": stage, "requested": value,
                   "method": "keyboard-select-all-delete-type"}
    live.EVIDENCE["phase"] = "date-replacement:" + stage
    try:
        observation["before"] = _date_input_state(field)
        field.click()
        observation["focused_before_replacement"] = _date_input_state(field)
        assert observation["focused_before_replacement"]["focused"]
        if observation["before"]["value"]:
            observation["focus_frames"] = field.evaluate("""input=>new Promise((resolve,reject)=>{
              const deadline=setTimeout(()=>reject(new Error('Native date focus did not finish two visible frames.')),1000);
              const frames=[],read=()=>({value:input.value,start:input.selectionStart,
                end:input.selectionEnd,focused:input===document.activeElement});
              requestAnimationFrame(()=>{frames.push(read());
                requestAnimationFrame(()=>{frames.push(read());clearTimeout(deadline);resolve(frames)});
              });
            })""")
            assert observation["focus_frames"][0] == observation["focus_frames"][1], "Native date focus/caret must settle before replacement."
            assert observation["focus_frames"][1]["focused"]
            assert observation["focus_frames"][1]["value"] == observation["before"]["value"]
        else:
            # Empty focus can defer only cursor0. Its0..0 selection is already
            # unchanged by that callback, so a frame budget is no prerequisite.
            observation["focus_frames_not_required"] = "empty-input-selection-0-0"
        field.press("ControlOrMeta+A")
        observation["selected"] = _date_input_state(field)
        assert observation["selected"]["start"] == 0
        assert observation["selected"]["end"] == len(observation["selected"]["value"])
        field.press("Backspace")
        observation["after_delete"] = _date_input_state(field)
        expect(field).to_have_value("")
        field.press_sequentially(value)
        observation["after_type"] = _date_input_state(field)
        expect(field).to_have_value(value)
        field.press("Tab")
        observation["after_tab"] = _date_input_state(field)
        expect(field).to_have_value(value)
    finally:
        try:
            observation["events"] = page.evaluate("()=>(window.__enfraTrainingDateEvents||[]).splice(0)")
        except Exception as exc:
            observation["observation_error"] = str(exc)[:300]
        live.EVIDENCE.setdefault("date_replacements", []).append(observation)


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
    live.EVIDENCE["phase"] = "open-training-form"
    summary = page.locator('[data-testid="stExpander"] summary').filter(has=page.get_by_text("Add training session", exact=True))
    expect(summary).to_have_count(1)
    if not summary.evaluate("el => el.closest('details')?.open ?? el.getAttribute('aria-expanded')==='true'"):
        summary.click()
    date = page.locator('[data-testid="stDateInput"]').filter(has=page.get_by_text("Training date", exact=True))
    expect(date).to_have_count(1)
    field = date.get_by_test_id("stDateInputField")
    expect(field).to_be_visible()
    return date, field


def submit_form(page, submit, stage):
    live.EVIDENCE["phase"] = "submit-training:" + stage
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


def record_date_control(page, date, stage):
    """Observe the real clear control without bypassing its accessible state."""
    observed = {"stage": stage}
    try:
        observed["accessibility"] = date.aria_snapshot(timeout=1000)
    except Exception as exc:
        observed["accessibility_error"] = str(exc)[:300]
    try:
        observed["dom"] = date.evaluate("""root => ({
      controls: Array.from(root.querySelectorAll('[role="button"]')).slice(0,4).map(el=>({
        tag:el.tagName, role:el.getAttribute('role'), name:el.getAttribute('aria-label'),
        title:el.getAttribute('title'), tabIndex:el.tabIndex,
        focused:el===document.activeElement,
        hiddenAncestors:(()=>{const result=[];for(let n=el;n;n=n.parentElement){
          const style=getComputedStyle(n);
          if(n.hidden||n.inert||n.getAttribute('aria-hidden')==='true'||
             style.display==='none'||style.visibility==='hidden')
            result.push({tag:n.tagName, testid:n.dataset.testid||null,
              ariaHidden:n.getAttribute('aria-hidden'), inert:Boolean(n.inert),
              hidden:n.hidden, display:style.display, visibility:style.visibility});
        }return result.slice(0,8)})()
      })),
      openListboxes:document.querySelectorAll('[role="listbox"]').length,
      active:{tag:document.activeElement?.tagName,role:document.activeElement?.getAttribute('role')}
    })""")
    except Exception as exc:
        observed["dom_error"] = str(exc)[:300]
    live.EVIDENCE.setdefault("date_controls", []).append(observed)
    return observed


def no_second_date(date):
    expect(date.locator('[aria-live="assertive"]')).not_to_contain_text("second date")


def selected_date(date, expected):
    expect(date.locator('[aria-live="assertive"]')).to_have_text(f"Selected date is {expected}.")
    no_second_date(date)


def select_day(page, field, day):
    live.EVIDENCE["phase"] = f"calendar-day:{day}"
    field.click()
    cell = page.get_by_role("gridcell", name=re.compile(rf"September {day}(?:st|nd|rd|th) 2026"))
    expect(cell).to_have_count(1)
    cell.click()
    expect(field).to_have_value(f"2026/09/{day:02d}")
    expect(cell).not_to_be_visible()


def export_and_check(page, stage, included):
    live.EVIDENCE["phase"] = "output:" + stage
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
    # Native table cells wrap at their normal width. Preserve the exact word
    # sequence while allowing PDF extraction's typographic line breaks.
    for label, text in (("DOCX", words), ("PDF", " ".join(printed.split()))):
        assert (TITLE in text) == included, f"{label} must reflect the deliberate monthly session inclusion."
        if included:
            assert "2026-09-15" in text and PARTICIPANT in text
    live.EVIDENCE.setdefault("outputs", []).append({"stage": stage, "included": included,
        "docx_bytes": len(word), "docx_sha256": sha256(word).hexdigest(),
        "pdf_bytes": len(pdf), "pdf_sha256": sha256(pdf).hexdigest()})


def capture_observers(page, stage):
    """Retain each document before reload without masking its primary result."""
    observation = {"stage": stage}
    try:
        observation["evidence"] = page.evaluate("() => window.__enfraTrainingObserverEvidence || null")
    except Exception as exc:
        observation["diagnostic_error"] = str(exc)[:300]
    records = live.EVIDENCE.setdefault("observer_documents", [])
    records.append(observation)
    if len(records) > 4:
        records.pop(0)


def enter_topic_and_participant(page):
    """Use one native input and the widget's ordinary manual-menu opening.

    The earlier fill-only failure has no participant event/node evidence and
    remains unclassified. This is one initial pointer/filter/selection path;
    no retry or replacement input may rescue a lost menu or filter.
    """
    observation = {"method": "one-native-input-pointer-open-filter-select"}
    field = None
    try:
        participants = page.locator('[data-testid="stMultiSelect"]').filter(has=page.get_by_text("Participants", exact=True))
        expect(participants).to_have_count(1)
        locator = participants.get_by_role("combobox")
        expect(locator).to_have_count(1)
        field = locator.element_handle()
        assert field is not None
        observation["before_topic"] = field.evaluate("""input=>{
          const events=[], workspace=input.closest('.epc-workspace'), app=input.closest('[data-testid="stApp"]');
          const read=()=>({connected:input.isConnected,focused:input===document.activeElement,
            value:input.value.slice(0,160),expanded:input.getAttribute('aria-expanded'),
            fullRender:workspace?.dataset.epcFullRender||null,
            scriptState:app?.getAttribute('data-test-script-state')||null});
          const record=(type,event)=>{events.push({at:performance.now(),type,...read(),
            trusted:event?.isTrusted??null,inputType:event?.inputType||null,
            data:typeof event?.data==='string'?event.data.slice(0,160):null});
            if(events.length>60)events.shift();};
          const handlers=['focus','beforeinput','input','change','blur'].map(type=>{
            const handler=event=>record(type,event);input.addEventListener(type,handler,{capture:true,passive:true});
            return [type,handler];
          });
          const mutations=new MutationObserver(records=>record('attributes:'+Array.from(new Set(records.map(r=>r.attributeName))).join(',')));
          mutations.observe(input,{attributes:true,attributeFilter:['aria-expanded','aria-controls']});
          if(workspace)mutations.observe(workspace,{attributes:true,attributeFilter:['data-epc-full-render']});
          if(app)mutations.observe(app,{attributes:true,attributeFilter:['data-test-script-state']});
          window.__enfraTrainingParticipantEvidence={events};
          window.__enfraTrainingParticipantDispose=()=>{mutations.disconnect();
            for(const [type,handler] of handlers)input.removeEventListener(type,handler,{capture:true});};
          record('bound-original-input');return read();
        }""")
        assert observation["before_topic"]["connected"]
        page.get_by_role("textbox", name="Training topic", exact=True).fill(TITLE)
        assert field.evaluate("input=>input.isConnected"), "Participants input must survive topic entry."
        field.click()
        page.wait_for_function("""input=>input.isConnected&&input===document.activeElement&&
          input.getAttribute('aria-expanded')==='true'""", arg=field, timeout=5000)
        observation["opened"] = field.evaluate("input=>({connected:input.isConnected,focused:input===document.activeElement,value:input.value,expanded:input.getAttribute('aria-expanded')})")
        field.fill(PARTICIPANT)
        page.wait_for_function("""({input,value})=>input.isConnected&&input===document.activeElement&&
          input.getAttribute('aria-expanded')==='true'&&input.value===value""", arg={"input": field, "value": PARTICIPANT}, timeout=5000)
        observation["filtered"] = field.evaluate("input=>({connected:input.isConnected,focused:input===document.activeElement,value:input.value,expanded:input.getAttribute('aria-expanded')})")
        option = page.get_by_role("option", name=PARTICIPANT, exact=True)
        expect(option).to_have_count(1)
        expect(option).to_be_visible()
        option.click()
        expect(participants.locator('[data-tag]')).to_have_text([PARTICIPANT])
        assert field.evaluate("input=>input.isConnected"), "Participants input must survive option selection."
    finally:
        try:
            if field is not None:
                observation["final"] = field.evaluate("input=>({connected:input.isConnected,focused:input===document.activeElement,value:input.value,expanded:input.getAttribute('aria-expanded')})")
            observation["native"] = page.evaluate("""()=>{const result=window.__enfraTrainingParticipantEvidence||null;
              window.__enfraTrainingParticipantDispose?.();delete window.__enfraTrainingParticipantDispose;
              delete window.__enfraTrainingParticipantEvidence;return result;}""")
        except Exception as exc:
            observation["observation_error"] = str(exc)[:300]
        live.EVIDENCE.setdefault("participant_selection", []).append(observation)


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
    page.add_init_script(DATE_EVENTS + "\n" + (ROOT / "scripts/qa_training_observer_diagnostics.js").read_text())
    TrainingDateDelivery(lambda row: live.EVIDENCE.setdefault("date_wire", []).append(row)).attach(page)
    page.set_default_timeout(20000)
    started = time.monotonic()
    def page_error(error):
        message = str(error)[:500]
        errors.append(message)
        records = live.EVIDENCE.setdefault("browser_error_events", [])
        records.append({"message": message, "phase": live.EVIDENCE.get("phase"),
                        "elapsed_seconds": time.monotonic() - started})
        if len(records) > 8:
            records.pop(0)
    page.on("pageerror", page_error)
    page.on("response", lambda response: date_responses.append(response) if "/DateInput." in response.url and response.url.endswith(".js") else None)
    try:
        live.EVIDENCE["phase"] = "open-synthetic-server"
        page.goto(URL, wait_until="domcontentloaded")
        live.EVIDENCE["phase"] = "load-synthetic-fixture"
        live.load_fixture(page, "prefill")
        page.wait_for_function(READY, timeout=25000)
        date, field = open_form(page)
        expect(field).to_have_value("")
        if patched:
            live.EVIDENCE["phase"] = "enter-topic-and-participant"
            # A multiselect deliberately keeps its popup open after selection.
            # Complete these existing entry actions before the date's normal
            # pointer/keyboard sequence, keeping the later clear assertion
            # independent of the other widget's open-popup state.
            # No extra dismissal gesture or hidden-control click is added.
            enter_topic_and_participant(page)
        replace_date(page, field, "2026/09/14", "typed-single-date")
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
        live.EVIDENCE["phase"] = "keyboard-calendar-selection"
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
        record_date_control(page, date, "before-native-clear")
        clear = date.get_by_role("button", name="Clear value", exact=True)
        expect(clear).to_have_count(1)
        expect(clear).to_be_visible()
        live.EVIDENCE["phase"] = "native-clear-date"
        clear.click()
        expect(field).to_have_value("")
        expect(date.locator('[aria-live="assertive"]')).to_have_text("")
        record_date(page, date, "cleared-date")
        submit = page.get_by_role("button", name="Add training session", exact=True)
        submit_form(page, submit, "missing-date")
        expect(page.get_by_text("Choose a training date within this reporting month.", exact=True)).to_be_visible()
        await_events(page, baseline["working"]["events"], baseline)
        for value, stage in (("2026/09/", "partial-date"), ("2026/08/31", "before-month"), ("2026/10/01", "after-month")):
            date, field = open_form(page)
            replace_date(page, field, value, stage)
            record_date(page, date, stage)
            no_second_date(date)
            submit_form(page, submit, stage)
            expect(page.get_by_text("Choose a training date within this reporting month.", exact=True)).to_be_visible()
            await_events(page, baseline["working"]["events"], baseline)
        date, field = open_form(page)
        replace_date(page, field, "2026/09/14", "valid-date-before-calendar")
        select_day(page, field, 15)
        no_second_date(date)
        submit_form(page, submit, "valid-date")
        await_events(page, [*baseline["working"]["events"], ROW], baseline)
        capture_observers(page, "before-added-session-reload")
        live.EVIDENCE["phase"] = "reload-added-session"
        page.reload(wait_until="domcontentloaded")
        await_events(page, [*baseline["working"]["events"], ROW], baseline)
        added = page.get_by_role("button", name=f"Remove session: {TITLE} · 2026-09-15", exact=True)
        added.scroll_into_view_if_needed()
        live.screenshot(page, "desktop-session-card")
        export_and_check(page, "session-added", True)
        live.EVIDENCE["phase"] = "narrow-session-card"
        page.set_viewport_size({"width": 390, "height": 844})
        added.scroll_into_view_if_needed()
        expect(added).to_be_visible()
        assert page.evaluate("() => document.documentElement.scrollWidth<=innerWidth+1"), "Training must not cause whole-page narrow overflow."
        live.screenshot(page, "narrow-session-card")
        live.EVIDENCE["phase"] = "remove-monthly-session"
        added.click()
        await_events(page, baseline["working"]["events"], baseline)
        capture_observers(page, "before-removed-session-reload")
        live.EVIDENCE["phase"] = "reload-removed-session"
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
            if date.count() == 1:
                record_date_control(page, date, "first-failure")
            live.screenshot(page, "first-failure")
        except Exception:
            pass
        raise
    finally:
        capture_observers(page, "final")
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
