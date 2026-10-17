"""Fresh ordinary Monthly first-site pointer acceptance on an isolated local server.

This is the real run_web entry and catalog, not the preselected synthetic QA
fixture. Each action uses native Playwright input once. No client reports,
third-party readers, report generation or standing-data writes are permitted.
Browser emulation is NOT a physical touchscreen or Safari hardware test.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.qa_fresh_native_error_checks import capture_native_window_errors, require_no_native_window_errors
from scripts.qa_workflow_route_observations import WorkflowRouteObservations, workflow_route

OUT = ROOT / "test-artifacts" / "monthly-first-site"
BASE_URL = "http://127.0.0.1:8526/?workflow=monthly"
CONTRACT = "Rochester Regional Health"
FIRST = "United Memorial Medical Center"
SECOND = "Rochester General Hospital"
PORT = 8526
results = {"synthetic_isolated_storage": True, "actual_user_pointer": True,
           "physical_device": False, "touch_emulated": True, "checks": [], "failures": []}


TAIL_CLIENT = r"""(() => {
  if(location.hostname!=='127.0.0.1'||location.port!=='8526')return;
  const names=new Set(['United Memorial Medical Center','Rochester General Hospital']);
  const ids=new WeakMap();let next=0,active=false,count=0,errorCount=0;
  const identity=node=>{if(!node)return null;if(!ids.has(node))ids.set(node,++next);return ids.get(node)};
  const describe=node=>node?.tagName?{node:identity(node),tag:node.tagName,
    name:node.getAttribute('aria-label')||'',domId:node.id||'',connected:node.isConnected,
    checked:node.matches('input[type="checkbox"]')?node.checked:null,
    disabled:!!node.disabled,focused:document.activeElement===node}:null;
  const snapshot=()=>({document:performance.timeOrigin,errorCount,
    running:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
    fullRender:document.querySelector('.epc-workspace')?.dataset.epcFullRender||null,
    identity:document.querySelector('.st-key-monthly_report_identity_sites')?.textContent?.slice(0,1000)||'',
    inputs:[...document.querySelectorAll('input[type="checkbox"]')]
      .filter(node=>names.has(node.getAttribute('aria-label'))).map(describe),
    focused:describe(document.activeElement)});
  const emit=(kind,detail)=>{if(count++<1200)console.debug('ENFRA_SITE_TAIL '+JSON.stringify({
    kind,at:performance.now(),detail}));};
  const emitError=(kind,detail)=>{
    errorCount++;
    if(errorCount<=200)console.debug('ENFRA_SITE_TAIL '+JSON.stringify({kind,at:performance.now(),detail}));
    else if(errorCount===201)console.debug('ENFRA_SITE_TAIL '+JSON.stringify({
      kind:'browser-error-overflow',at:performance.now(),detail:{document:performance.timeOrigin}}));
  };
  // Only inspect the two real inputs. Never prevent, dispatch or commit events,
  // change values, schedule work or observe layout/DOM mutations.
  for(const type of ['pointerdown','pointerup','mousedown','mouseup','click','input','change','keydown','keyup','focus','blur']){
    document.addEventListener(type,event=>{
      if(!active)return;
      const row=event.target?.closest?.('[data-testid="stCheckbox"]');
      const input=event.target?.matches?.('input[type="checkbox"]')?event.target:row?.querySelector('input[type="checkbox"]');
      if(!input||!names.has(input.getAttribute('aria-label')))return;
      emit('native-event',{type,trusted:event.isTrusted,key:event.key||'',
        target:describe(event.target),input:describe(input),related:describe(event.relatedTarget),
        point:{x:event.clientX??null,y:event.clientY??null},...snapshot()});
    },{capture:true,passive:true});
  }
  // Retain browser-native errors even before the tail; returning nothing leaves
  // their normal pageerror/default reporting intact, including ResizeObserver.
  addEventListener('error',event=>emitError('window-error',{message:(event.message||'').slice(0,2000),
    name:event.error?.name||'',stack:event.error?.stack?.slice(0,2000)||'',...snapshot()}),{passive:true});
  addEventListener('unhandledrejection',event=>emitError('unhandled-rejection',{
    message:(event.reason?.message||String(event.reason)).slice(0,2000),name:event.reason?.name||'',
    stack:event.reason?.stack?.slice(0,2000)||'',...snapshot()}),{passive:true});
  window.__enfraSiteTail={arm:()=>{active=true;emit('tail-start',snapshot())},
    stop:()=>{if(active)emit('tail-end',snapshot());active=false}};
})();"""


class SiteTailEvidence:
    """Bounded two-checkbox receipts; no raw widget IDs or unrelated values."""
    def __init__(self, context, page, output, record):
        self.context, self.page, self.output, self.result = context, page, output, record
        self.rows, self.errors, self.diagnostic_errors = [], [], []
        self.active = self.tracing = False
        self.known = OrderedDict()
        self.cache = OrderedDict()
        self.last_run = self.last_finish = None
        self.socket_sequence = 0
        context.add_init_script(TAIL_CLIENT)
        page.on('console', self._console)
        page.on('pageerror', lambda error: self._record('pageerror', {
            'message': str(error)[:2000], 'stack': (getattr(error, 'stack', '') or '')[:2000]}))
        self.attach(page)
        record.update(browser_errors=self.errors, browser_error_count=0,
                      diagnostic_errors=self.diagnostic_errors,
                      tail_evidence={"events": output.name + '-events.jsonl',
                                     "trace": None, "scope": "second-site add through return to zero"})

    def _record(self, kind, detail):
        if kind in {'pageerror', 'window-error', 'unhandled-rejection', 'browser-error-overflow'}:
            # No message whitelist and no replacement of a first workflow error.
            self.result['browser_error_count'] += 1
            if len(self.errors) < 200:
                self.errors.append({'kind': kind, **detail})
        if len(self.rows) < 2000:
            self.rows.append({'kind': kind, 'time': time.time(), 'detail': detail})

    def _console(self, message):
        if message.text.startswith('ENFRA_SITE_TAIL '):
            try:
                item = json.loads(message.text[len('ENFRA_SITE_TAIL '):])
                self._record(item['kind'], {'at': item['at'], **item['detail']})
            except (KeyError, ValueError, TypeError) as exc:
                self.diagnostic_errors.append({'stage': 'client-decode', 'error': str(exc)[:500]})

    def attach(self, page):
        def connected(socket):
            address = urlparse(socket.url)
            if address.hostname != '127.0.0.1' or address.port != PORT:
                raise ValueError('Site observations require the synthetic localhost fixture')
            self.socket_sequence += 1
            socket_id = self.socket_sequence
            socket.on('framereceived', lambda raw: self.message('received', raw, socket_id))
            socket.on('framesent', lambda raw: self.message('sent', raw, socket_id))
        page.on('websocket', connected)

    def message(self, direction, raw, socket_id):
        if not isinstance(raw, bytes) or len(raw) > 4 * 1024 * 1024 or len(self.rows) >= 2000:
            return
        msg = ForwardMsg() if direction == 'received' else BackMsg()
        try:
            msg.ParseFromString(raw)
        except DecodeError:
            return
        kind = msg.WhichOneof('type')
        item = {'direction': direction, 'kind': kind, 'socket': socket_id}
        if direction == 'received' and kind == 'delta':
            if msg.delta.new_element.WhichOneof('type') != 'checkbox':
                return
            widget = msg.delta.new_element.checkbox
            if widget.label not in {FIRST, SECOND}:
                return
            item.update(label=widget.label, id_hash=sha256(widget.id.encode()).hexdigest(),
                        default=widget.default, value=widget.value, set_value=widget.set_value,
                        fragment=msg.delta.fragment_id, path=list(msg.metadata.delta_path),
                        run=self.last_run.get('run') if self.last_run else None)
            self.known[widget.id] = item
            self.known.move_to_end(widget.id)
            while len(self.known) > 32:
                self.known.popitem(last=False)
            if msg.hash:
                self.cache[msg.hash] = dict(item)
                self.cache.move_to_end(msg.hash)
                while len(self.cache) > 32:
                    self.cache.popitem(last=False)
        elif direction == 'received' and kind == 'ref_hash':
            if msg.ref_hash not in self.cache:
                return
            item.update(reference=self.cache[msg.ref_hash], path=list(msg.metadata.delta_path))
        elif direction == 'sent' and kind == 'rerun_script':
            run = msg.rerun_script
            item.update(fragment=run.fragment_id, automatic=run.is_auto_rerun,
                        widgets=[{'label': self.known[w.id]['label'],
                                  'id_hash': self.known[w.id]['id_hash'], 'checked': w.bool_value}
                                 for w in list(run.widget_states.widgets)[:1024]
                                 if w.id in self.known and w.WhichOneof('value') == 'bool_value'])
        elif direction == 'received' and kind == 'new_session':
            item.update(run=msg.new_session.script_run_id,
                        fragments=list(msg.new_session.fragment_ids_this_run))
            self.last_run = dict(item)
        elif direction == 'received' and kind == 'script_finished':
            item['finish'] = msg.script_finished
            self.last_finish = dict(item)
        else:
            return
        if self.active:
            self._record('widget-wire', item)

    def _optional(self, stage, action):
        try:
            action()
        except Exception as exc:
            self.diagnostic_errors.append({'stage': stage, 'error': type(exc).__name__ + ': ' + str(exc)[:500]})

    def start(self):
        self.active = True
        self._record('known-checkboxes', list(self.known.values()))
        self._record('preceding-full-run', {'run': self.last_run, 'finish': self.last_finish})
        def trace():
            self.context.tracing.start(screenshots=True, snapshots=True, sources=False)
            self.tracing = True
            self.result['tail_evidence']['trace'] = self.output.name + '-trace.zip'
        self._optional('trace-start', trace)
        self._optional('tail-start', lambda: self.page.evaluate('window.__enfraSiteTail.arm()'))

    def stop(self):
        if self.active:
            self._optional('tail-stop', lambda: self.page.evaluate('window.__enfraSiteTail.stop()'))
            self.active = False
        if self.tracing:
            self.tracing = False
            self._optional('trace-stop', lambda: self.context.tracing.stop(
                path=str(self.output.with_name(self.output.name + '-trace.zip'))))

    def finish(self):
        self.stop()
        self._optional('write', lambda: self.output.with_name(self.output.name + '-events.jsonl').write_text(
            ''.join(json.dumps(row) + '\n' for row in self.rows), encoding='utf-8'))


def visit(browser, engine, method):
    from playwright.sync_api import expect
    touch = method == "touch"
    context = browser.new_context(viewport={"width": 390 if touch else 1365, "height": 844 if touch else 900},
                                  has_touch=touch)
    page = context.new_page()
    events, browser_errors = [], []
    page.on("pageerror", lambda error: browser_errors.append(str(error)[:1000]))
    page.add_init_script((ROOT / "scripts/qa_fresh_native_errors.js").read_text().replace(
        'http://127.0.0.1:8529', 'http://127.0.0.1:8526'))
    wire = WorkflowRouteObservations()
    wire.attach(page)
    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in ("blob", "data") or parsed.hostname == "127.0.0.1" and parsed.port == 8526:
            request.continue_()
        else:
            request.abort()
            events.append({"unexpected_external_request": parsed.hostname})
    page.route("**/*", route)
    record = {"engine": engine, "path": method}
    evidence = SiteTailEvidence(context, page, OUT / f'{engine}-{method}', record)
    try:
        record["phase"] = "choose fresh contract"
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.get_by_role("button", name=CONTRACT, exact=True).click()
        record["phase"] = "verify zero-selection baseline"
        box = page.get_by_role("checkbox", name=FIRST, exact=True)
        label = box.locator("xpath=ancestor::label[1]")
        label.scroll_into_view_if_needed()
        expect(box).not_to_be_checked()
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible()
        # Capture a small DOM/hit-test receipt BEFORE the one native action.
        record["before"] = box.evaluate("""node => {
            const label=node.closest('label'), rect=label.getBoundingClientRect();
            const row=node.closest('[data-testid="stCheckbox"]'), rowRect=row?.getBoundingClientRect();
            const hit=document.elementFromPoint(rect.left+Math.min(18,rect.width/2),rect.top+rect.height/2);
            const rowEndHit=rowRect&&document.elementFromPoint(rowRect.right-24,rowRect.top+rowRect.height/2);
            return {checked:node.checked,disabled:node.disabled,control:node.getBoundingClientRect().toJSON(),
                label:rect.toJSON(),row:rowRect?.toJSON(),squareHitOwned:!!hit&&label.contains(hit),
                rowEndHitTag:rowEndHit?.tagName,rowEndHitOwned:!!rowEndHit&&label.contains(rowEndHit),
                scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')};
        }""")
        record["phase"] = "single native " + method + " activation"
        if method == "square":
            r = label.bounding_box()
            label.click(position={"x": min(18, r["width"] / 3), "y": r["height"] / 2})
        elif method == "text":
            label.get_by_text(FIRST, exact=True).click()
        elif method == "row":
            geom = record["before"]
            # The native row is materially wider than the text label. Prove
            # the right-hand row surface itself hits its owning semantic label.
            # Earlier tests only hit the narrow label's trailing 12 pixels.
            assert geom["row"] and geom["label"]["width"] >= 340, geom
            assert geom["label"]["right"] >= geom["row"]["right"] - 32, geom
            assert geom["rowEndHitOwned"], geom
            r = geom["row"]
            page.mouse.click(r["right"] - 24, r["top"] + r["height"] / 2)
        elif method == "touch":
            label.tap()
        elif method == "keyboard":
            box.focus()
            box.press("Space")
        else:
            raise AssertionError("Unknown input mode")
        record["phase"] = "verify one native site selected and work enabled"
        expect(box).to_be_checked(timeout=45000)
        expect(page.locator(".st-key-monthly_report_identity_sites")).to_have_text("Site: " + FIRST, timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_have_count(0)
        expect(page.get_by_text("Starting report", exact=True)).to_be_visible(timeout=45000)
        record["phase"] = "second site and return to zero"
        evidence.start()
        # Distinct second site and recovery from zero. These must not silently
        # promote the first failure: it already had an independent assertion.
        second = page.get_by_role("checkbox", name=SECOND, exact=True)
        second_label = second.locator("xpath=ancestor::label[1]")
        second_label.scroll_into_view_if_needed()
        second_label.click()
        expect(second).to_be_checked(timeout=45000)
        expect(box).to_be_checked(timeout=45000)
        box.locator("xpath=ancestor::label[1]").click()
        expect(box).not_to_be_checked(timeout=45000)
        second.locator("xpath=ancestor::label[1]").click()
        expect(second).not_to_be_checked(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible(timeout=45000)
        evidence.stop()
        record["phase"] = "reload zero-site result with normal contract re-entry"
        capture_native_window_errors(page, record, "before-reload")
        page.reload(wait_until="domcontentloaded")
        # Before a draft has actually been created, a clean report has not
        # saved its contract. A normal reload may rightly return to the
        # contract selector. Use the ordinary user click to reach the same
        # selector; do not pretend an absent checkbox is a selection failure.
        # A fresh zero-site report does not persist the contract yet. Reload
        # legitimately returns to the contract cards; await that real page
        # before the one ordinary contract click used to resume navigation.
        contract_card = page.get_by_role("button", name=CONTRACT, exact=True)
        expect(contract_card).to_be_visible(timeout=15000)
        contract_card.click()
        expect(page.get_by_text("Change report sites", exact=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role("checkbox", name=FIRST, exact=True)).not_to_be_checked(timeout=45000)
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible(timeout=45000)
        capture_native_window_errors(page, record, "final")
        require_no_native_window_errors(record.get("native_window_errors"), expected_origin="http://127.0.0.1:8526")
        assert not browser_errors, {"browser_errors": browser_errors}
        if events:
            raise AssertionError("A synthetic browser requested an external URL")
        assert not evidence.errors, "Browser errors were recorded: " + json.dumps(evidence.errors)
        record["result"] = "pass"
        results["checks"].append(record)
    except Exception as exc:
        # Save screenshot BEFORE any further locator could fail (the checked
        # element may have moved, e.g. after reload). Keep the first failure.
        try:
            page.screenshot(path=str(OUT / f"{engine}-{method}-first-failure.png"))
        except Exception:
            pass
        record["result"] = "fail"
        record["error_type"] = type(exc).__name__
        record["message"] = str(exc)[:1000]
        record["workflow_route_after"] = workflow_route(page.url)
        if not record.get("native_window_errors") or record["native_window_errors"][-1].get("stage") != "final":
            capture_native_window_errors(page, record, "final")
        try:
            record["workflow_controls_after"] = page.locator('.st-key-workflow_mode').evaluate(
                "node => Array.from(node.querySelectorAll('[role=radio]')).map(r => "
                "({label:r.textContent.trim(),selected:r.getAttribute('aria-checked')}))")
        except Exception:
            pass
        try:
            record["after"] = page.get_by_role("checkbox", name=FIRST, exact=True).evaluate(
                "node => ({checked:node.checked,disabled:node.disabled})")
        except Exception:
            pass
        results["failures"].append(record)
    finally:
        record["workflow_wire"] = wire.snapshot()
        # Preserve the structured native/tail errors and the independent
        # Playwright pageerror receipt rather than overwriting either collector.
        record["page_errors"] = browser_errors
        evidence.finish()
        try:
            context.close()
        except Exception as exc:
            # Cleanup cannot replace an already recorded workflow assertion.
            if record.get('result') == 'fail':
                record['diagnostic_errors'].append({'stage': 'context-close', 'error': str(exc)[:500]})
            else:
                raise


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="monthly-native-pointer-") as directory:
        env = {**os.environ, "EPC_DATA_DIR": directory, "SMARTSHEET_API_MODE": "disabled",
               "ANTHROPIC_API_KEY": "test-key-not-used"}
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "run_web.py",
                "--server.address", "127.0.0.1", "--server.port", "8526",
                "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                for attempt in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Isolated ordinary Monthly server stopped")
                    try:
                        with urlopen("http://127.0.0.1:8526/_stcore/health", timeout=1) as status:
                            if status.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Isolated Monthly server did not start")
                with sync_playwright() as playwright:
                    for name, browser_type in (("chromium", playwright.chromium),
                                               ("playwright-webkit", playwright.webkit)):
                        browser = browser_type.launch(headless=True)
                        try:
                            for mode in ("square", "text", "row", "keyboard", "touch"):
                                visit(browser, name, mode)
                        finally:
                            browser.close()
            finally:
                process.terminate()
                process.wait(timeout=15)
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    if results["failures"]:
        raise AssertionError("Fresh ordinary Monthly pointer failure: " +
                             "; ".join(f["engine"] + "/" + f["path"] + ": " +
                                       f["error_type"] for f in results["failures"]))
    print("PASS ten genuinely fresh zero-site mouse/keyboard/emulated-touch journeys; no QA prefill")


if __name__ == "__main__":
    main()
