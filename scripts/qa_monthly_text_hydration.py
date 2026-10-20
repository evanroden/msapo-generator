"""Actual Training/issue text and generation in the guarded synthetic app.

Local disposable storage only, no customer data or external readers. Reuses
strict generation receipts. Each edit must reach both the canonical report and
the disk journal before reload; a layout stamp is not a save acknowledgment.
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
from scripts.workspace_wire_observations import WireObservations

EXPECTED = {"Training notes": "Hospital staff completed a synthetic training exercise.",
            "Issue description": "Synthetic actuator feedback follow-up."}
READY = """() => Boolean(document.querySelector('.epc-workspace')?.dataset.epcFullRender) &&
 document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning'"""
RECEIPT = '[data-enfra-text-receipt]'
# Passive evidence only. A MutationObserver callback can first see removal and
# acknowledgment together; its shared timestamp/observation never orders them.
TEXT_EDIT_OBSERVER = """expected => {
    window.__enfraTextEditCleanup?.();
    const state={node:null,events:[],first_input:null,first_detachment:null,
        first_matching_ack:null,transitions:[],transitions_truncated:false,
        observations:0,receipt_parse_errors:0};
    window.__enfraTextEdit=state;
    let signature;
    const sample=(source,at=performance.now())=>{
        const nodes=document.querySelectorAll('[data-enfra-text-receipt]');
        let receipt=null;
        try {if(nodes.length) receipt=JSON.parse(nodes[nodes.length-1].dataset.enfraTextReceipt);}
        catch {state.receipt_parse_errors++;}
        const textHash=part=>expected.label==='Training notes' ? part?.training :
            (Array.isArray(part?.issues) && part.issues.length===1 ? part.issues[0] : null);
        const details={
            script_state:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')||null,
            full_render:document.querySelector('.epc-workspace')?.dataset.epcFullRender||null,
            active_id:document.activeElement?.id||null,
            input_node_id:state.node?.id||null,
            input_node_connected:state.node ? state.node.isConnected : null,
            working_sha:textHash(receipt?.working)||null,
            durable_sha:textHash(receipt?.durable)||null,
            working_fingerprint:receipt?.working_fingerprint||null,
            durable_fingerprint:receipt?.durable_fingerprint||null,
            durable_revision:receipt?.durable_revision??null
        };
        const observed={at_ms:at,observation:++state.observations,source,...details};
        if(state.node && !state.node.isConnected && !state.first_detachment)
            state.first_detachment=observed;
        if(state.node && !state.first_matching_ack && details.working_sha===expected.sha &&
            details.durable_sha===expected.sha &&
            receipt?.working_fingerprint===receipt?.durable_fingerprint &&
            details.script_state==='notRunning') state.first_matching_ack=observed;
        const nextSignature=JSON.stringify(details);
        if(nextSignature!==signature) {
            if(state.transitions.length<32) state.transitions.push(observed);
            else state.transitions_truncated=true;
            signature=nextSignature;
        }
        return observed;
    };
    state.sample=sample;
    state.snapshot=()=>{
        const detached=state.first_detachment, ack=state.first_matching_ack;
        const ordering=!detached ? 'no_detachment_observed' : !ack ? 'detachment_without_matching_ack' :
            detached.observation===ack.observation ? 'same_observation' :
            detached.observation<ack.observation ? 'detachment_observed_before_ack' : 'ack_observed_before_detachment';
        return {clock:'performance.now',time_origin_ms:performance.timeOrigin,label:expected.label,
            first_input:state.first_input,first_detachment:detached,first_matching_ack:ack,ordering,
            observations:state.observations,transitions:state.transitions,
            transitions_truncated:state.transitions_truncated,receipt_parse_errors:state.receipt_parse_errors};
    };
    const observe=event=>{
        const target=event.target;
        if(target?.tagName!=='TEXTAREA' || target.getAttribute('aria-label')!==expected.label) return;
        const at=performance.now(), first=event.type==='input' && state.node===null;
        if(first) state.node=target;
        const observed=sample('native:'+event.type,at);
        if(first) state.first_input=observed;
        if(state.events.length<16) state.events.push({kind:event.type,id:target.id,at_ms:at,
            trusted:event.isTrusted,sameInputNode:state.node===target,script_state:observed.script_state});
    };
    const mutations=new MutationObserver(()=>sample('mutation'));
    mutations.observe(document.documentElement,{childList:true,subtree:true,attributes:true,
        attributeFilter:['data-enfra-text-receipt','data-test-script-state','data-epc-full-render']});
    for(const kind of ['input','change','blur']) document.addEventListener(kind,observe,true);
    window.__enfraTextEditCleanup=()=>{
        mutations.disconnect();
        for(const kind of ['input','change','blur']) document.removeEventListener(kind,observe,true);
    };
    sample('installed');
}"""


def phase(name):
    live.EVIDENCE["phase"] = name
    live.event("text_stage", name=name)


def receipt(page):
    values = page.locator(RECEIPT)
    return json.loads(values.last.get_attribute('data-enfra-text-receipt')) if values.count() else None


def await_text(page, label, text):
    expected = sha256(text.encode()).hexdigest()
    page.wait_for_function("""expected => {
        const nodes=document.querySelectorAll('[data-enfra-text-receipt]');
        if(!nodes.length) return false;
        const state=JSON.parse(nodes[nodes.length-1].dataset.enfraTextReceipt);
        const matches = part => part && (expected.label==='Training notes'
            ? part.training===expected.sha : part.issues.length===1 && part.issues[0]===expected.sha);
        window.__enfraTextEdit?.sample?.('await_text');
        return matches(state.working) && matches(state.durable) &&
            state.working_fingerprint===state.durable_fingerprint &&
            document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={"label": label, "sha": expected}, timeout=25000)
    expect(page.get_by_role("textbox", name=label, exact=True)).to_have_value(text)
    current = receipt(page)
    live.EVIDENCE.setdefault('text_receipts', []).append({"phase": live.EVIDENCE["phase"], **current})


def commit_text(page, label, text, *, expected_before):
    field = page.get_by_role("textbox", name=label, exact=True)
    # Reload can expose an offscreen native field before its controlled value
    # hydrates. Establish this edit's exact prerequisite on the same locator;
    # a missing/wrong value must fail before the deliberate clear or reentry.
    expect(field).to_have_value(expected_before)
    before = field.input_value()
    assert before == expected_before, "The field changed after its expected value was observed."
    live.event("text_edit_requested", label=label, before_sha256=sha256(before.encode()).hexdigest(),
               requested_sha256=sha256(text.encode()).hexdigest())
    assert before != text, "This edit must change the existing field, not silently pass a no-op."
    initial_id = field.get_attribute('id')
    # A locator sampled before its actionability wait may still refer to a
    # previous hydration mount. Capture the DOM node receiving the FIRST real
    # input event and require that exact object at the post-acknowledgment check.
    # This observes native events only: no value writes, event injection, input
    # cloning or focus intervention. Keep the earlier ID for diagnosis too.
    page.evaluate(TEXT_EDIT_OBSERVER, {"label": label, "sha": sha256(text.encode()).hexdigest()})
    field.fill(text)
    field.press("Tab")
    await_text(page, label, text)
    continuity = field.evaluate("""current => {
        const state=window.__enfraTextEdit;
        state?.sample?.('continuity');
        return {inputObserved:Boolean(state?.node),sameNode:state?.node===current,
            inputNodeConnected:Boolean(state?.node?.isConnected),currentId:current.id,
            inputNodeId:state?.node?.id||null,events:state?.events||[],timing:state?.snapshot?.()||null};
    }""")
    continuity.update(label=label, phase=live.EVIDENCE["phase"], pre_action_id=initial_id)
    live.EVIDENCE.setdefault('node_continuity', []).append(continuity)
    page.evaluate("window.__enfraTextEditCleanup?.()")
    assert continuity['inputObserved'], "The editor test must observe an actual native input event."
    assert continuity['sameNode'] and continuity['inputNodeConnected'], "The input-event node was replaced by the post-acknowledgment continuity check."


def export_and_check(page, stage):
    phase(stage)
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
    live.ROOT = OUT / name
    live.ROOT.mkdir(parents=True, exist_ok=True)
    live.EVIDENCE = {"synthetic_only": True, "public_url": URL, "browser": name,
                     "checks": {}, "events": [], "artifacts": {},
                     "tested_checkout": subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip()}
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    attempts, errors = [], []

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
    page.on('pageerror', lambda error: errors.append(str(error)[:500]))
    wire = WireObservations(PORT)
    wire.attach(page)
    try:
        phase('initial native values')
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
            phase(label + ' clear and save')
            commit_text(page, label, "", expected_before=wording)
            phase(label + ' clear reload')
            page.reload(wait_until="domcontentloaded")
            await_text(page, label, "")
            live.checkpoint(label + " deliberate clear survives reload", True)
            phase(label + ' reentry and save')
            commit_text(page, label, wording, expected_before="")
            phase(label + ' reentry reload')
            page.reload(wait_until="domcontentloaded")
            await_text(page, label, wording)
            live.checkpoint(label + " reentry survives reload", True)
        expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_have_value(activity)
        export_and_check(page, "restored-native-text")
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        live.checkpoint("no external browser requests", not attempts)
        live.screenshot(page, "final-synthetic-output")
    except Exception as exc:
        live.EVIDENCE["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            live.EVIDENCE["native_timing"] = page.evaluate("window.__enfraTextEdit?.snapshot?.()||null")
            live.EVIDENCE["last_text_receipt"] = receipt(page)
            live.EVIDENCE["visible_text_hashes"] = {
                label: sha256(page.get_by_role('textbox', name=label, exact=True).input_value().encode()).hexdigest()
                for label in EXPECTED}
            live.EVIDENCE["native_events"] = page.evaluate("window.__enfraTextEdit?.events||[]")
            live.EVIDENCE["script_state"] = page.locator('[data-testid="stApp"]').get_attribute('data-test-script-state')
            live.EVIDENCE["structural_changes"] = page.get_by_text("QA structural change since accepted click", exact=False).all_text_contents()
            live.screenshot(page, "first-failure")
        except Exception:
            pass
        raise
    finally:
        live.EVIDENCE['browser_errors'] = errors
        (live.ROOT / "results.json").write_text(json.dumps(live.EVIDENCE, indent=2) + "\n")
        (live.ROOT / "wire.json").write_text(json.dumps(wire.snapshot(), indent=2) + "\n")
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
    print("PASS native Training/issue hydration, real generation and durable clear/reentry/reload in both engines")


if __name__ == "__main__":
    main()
