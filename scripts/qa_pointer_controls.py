"""Pointer regression on the actual PO/expense Streamlit forms, with synthetic data.

No .check(), .set_checked(), JS-dispatched clicks or label-centre shortcuts:
the pointer must hit the visible box/track, then the label text separately.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "test-artifacts" / "pointer-controls"
OUT.mkdir(parents=True, exist_ok=True)
VIEWS = {
    "desktop": (1920, 993),
    "phone": (390, 844),
    "ipad": (820, 1180),
}
FLOWS = {
    "purchase": ("tests/fixtures/workspaces/po_app.py", 8526, "po-adaptive-synthetic-"),
    "expense": ("tests/fixtures/workspaces/expense_app.py", 8527, "expense-adaptive-synthetic-"),
}
INPUTS = (
    '[data-testid="stCheckbox"] input[type="checkbox"],'
    '[data-testid="stToggle"] input[type="checkbox"]'
)
REPORT = {"synthetic_only": True, "method": "physical pointer at visible box/track and label text",
          "controls": [], "failures": []}

# Compute the centre of a real visible decoration, not the 1px React Aria
# VisuallyHidden input and not the midpoint of the full label. Diagnostics
# include what elementFromPoint hit so a future native frontend update cannot
# silently turn this test into a synthetic input dispatch.
POINT = r"""(input, method) => {
    const label = input.closest('label');
    if (!label) throw new Error('Missing associated native label');
    const outer = label.getBoundingClientRect();
    const kind = input.closest('[data-testid="stToggle"]') ? 'toggle' : 'checkbox';
    if (method === 'text') {
        const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) {
            const node = walker.currentNode;
            if (node.textContent.trim()) textNodes.push(node);
        }
        textNodes.sort((a,b) => b.textContent.trim().length - a.textContent.trim().length);
        const node = textNodes[0];
        if (!node) throw new Error('No visible label text');
        const start = node.textContent.search(/\S/);
        const range = document.createRange();
        range.setStart(node,start);
        range.setEnd(node,Math.min(node.textContent.length,start+12));
        const rect = range.getClientRects()[0];
        if (!rect || !rect.width || !rect.height) throw new Error('Label text has no visible rect');
        const x = rect.x + rect.width/2, y = rect.y + rect.height/2;
        const hit = document.elementFromPoint(x,y);
        return {x,y,kind,method,withinLabel:!!hit && label.contains(hit),
                hitTag:hit?.tagName,rect:rect.toJSON()};
    }
    const size = kind === 'toggle' ? {w:42,h:22} : {w:20,h:20};
    const candidates = [...label.querySelectorAll('div,span')]
        .filter(el => el !== input && !el.contains(input))
        .map(el => {
            const r=el.getBoundingClientRect(), s=getComputedStyle(el);
            return {el,r,s};
        })
        .filter(({r,s}) => r.width >= 12 && r.width <= 88 &&
            r.height >= 12 && r.height <= 50 &&
            r.top >= -1 && r.bottom <= innerHeight+1 &&
            s.display !== 'none' && s.visibility === 'visible')
        .map(({el,r,s}) => ({
            el,r,score:Math.abs(r.width-size.w)*2+Math.abs(r.height-size.h)*2+
                Math.max(0,r.left-outer.left-40)*0.7,
            pointerEvents:s.pointerEvents
        }))
        .sort((a,b) => a.score-b.score);
    if (!candidates.length) throw new Error('No visible checkbox box / toggle track');
    const {r,pointerEvents} = candidates[0];
    const x=r.left+r.width/2, y=r.top+r.height/2;
    const hit=document.elementFromPoint(x,y);
    return {x,y,kind,method,withinLabel:!!hit && label.contains(hit),
            hitTag:hit?.tagName,rect:r.toJSON(),pointerEvents,
            candidates:candidates.length,visibleInput:input.getBoundingClientRect().toJSON()};
}"""


def full_run(page, flow):
    pattern = (r"^Synthetic full-app run count: " if flow == "purchase"
               else r"^Synthetic full app runs: ")
    return int(page.get_by_text(re.compile(pattern)).inner_text().rsplit(": ", 1)[1])


def await_rerun(page, flow, previous):
    page.wait_for_function(r"""p => {
        const app=document.querySelector('[data-testid="stApp"]');
        if (!app || app.getAttribute('data-test-script-state') !== 'notRunning') return false;
        const match=document.body.innerText.match(p.flow === 'purchase'
            ? /Synthetic full-app run count:\s*(\d+)/
            : /Synthetic full app runs:\s*(\d+)/);
        return !!match && Number(match[1])>p.previous;
    }""", arg={"flow": flow, "previous": previous}, timeout=35000)

def contact(page, control, how, touch):
    label = control.locator("xpath=ancestor::label[1]")
    label.scroll_into_view_if_needed(timeout=20000)
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    point = control.evaluate(POINT, how)
    assert point["withinLabel"], "Visible target is occluded: " + repr(point)
    if how == "box":
        assert point["pointerEvents"] != "none", repr(point)
    if touch:
        page.touchscreen.tap(point["x"], point["y"])
    else:
        page.mouse.click(point["x"], point["y"])
    return point


def assert_dependent(page, flow, label):
    if flow == "expense":
        if label.startswith("Split this receipt"):
            expect(page.get_by_label("Number of reimbursement lines", exact=True)).to_be_visible()
            expect(page.get_by_label("Reimbursable amount *", exact=True).first).to_be_visible()
        elif label == "Include reimbursable business mileage":
            expect(page.get_by_label("Business miles *", exact=True)).to_be_visible()
            # Streamlit names its date field "Select a date.", not by the visible
            # label, so find the date control through that label's text.
            expect(page.get_by_test_id("stDateInput").filter(has_text="Travel date *")).to_be_visible()
        elif label.startswith("I confirm this generated signature represents me"):
            expect(page.get_by_role("button", name="Generate expense report and email draft",
                                    exact=True)).to_be_enabled(timeout=15000)
    elif label == "Add Additional Information":
        expect(page.get_by_label("Additional information (optional)", exact=True)).to_be_visible()


def test_flow(page, flow, browser_name, view_name, touch):
    url = "http://127.0.0.1:" + str(FLOWS[flow][1])
    blocked = []
    def local_only(route):
        parsed = urlparse(route.request.url)
        if parsed.scheme in {"data", "blob"} or (
            parsed.hostname == "127.0.0.1" and parsed.port == FLOWS[flow][1]
        ):
            route.continue_()
        else:
            blocked.append(parsed.hostname or parsed.scheme)
            route.abort()
    page.route("**/*", local_only)
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    if flow == "purchase":
        # The scope checkboxes come first in the purchase form and sit in a
        # collapsed expander, so open it before waiting for a visible box.
        scope = page.get_by_text("Review scope, inclusions, and exclusions", exact=True)
        expect(scope).to_be_visible(timeout=60000)
        if scope.locator("xpath=ancestor::details[1]").get_attribute("open") is None:
            scope.click()
        page.wait_for_timeout(100)  # expander animation; no control state is inferred from this
    page.wait_for_selector(INPUTS, timeout=60000)
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
        ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=35000)

    if flow == "purchase":
        expect(scope.locator("xpath=ancestor::details[1]")).to_have_attribute("open", "")
    else:
        expect(page.get_by_label("Include reimbursable business mileage", exact=True)).to_have_count(1)
        expect(page.get_by_label("Split this receipt into multiple reimbursement lines",
                                 exact=True)).to_have_count(2)
        expect(page.get_by_label(re.compile(r"^I confirm this generated signature represents me"))).to_have_count(1)

    native = page.locator(INPUTS)
    # Streamlit can report backend idle before the final native widgets have
    # reconciled in WebKit. Require the existing full inventory before reading
    # labels or beginning physical pointer checks, never accept a partial form.
    page.wait_for_function("""p => document.querySelectorAll(p.selector).length >= p.minimum""",
                           arg={"selector": INPUTS, "minimum": 6 if flow == "purchase" else 4},
                           timeout=35000)
    count = native.count()
    assert count >= (6 if flow == "purchase" else 4), (flow,count)
    # Keep confirmation last. It gates generation, unlike all optional toggles.
    labels = [native.nth(i).evaluate(
        "n => n.closest('label')?.innerText.trim().replace(/\\s+/g,' ') || ''"
    ) for i in range(count)]
    order = sorted(range(count), key=lambda i: "I confirm this generated signature" in labels[i])
    if flow == "expense":
        expect(page.get_by_role("button", name="Generate expense report and email draft",
                                exact=True)).to_be_disabled()

    for index in order:
        native = page.locator(INPUTS)
        assert native.count() == count, "Native checkbox inventory changed unexpectedly"
        control = native.nth(index)
        label = labels[index]
        assert label, "Accessible control has no label text"
        assert not control.is_disabled(), "Fixture rendered a disabled control: " + label
        before = control.is_checked()
        previous = full_run(page,flow)
        box = contact(page,control,"box",touch)
        expect(page.locator(INPUTS).nth(index)).to_be_checked(checked=not before,timeout=15000)
        await_rerun(page,flow,previous)
        if not before:
            assert_dependent(page,flow,label)
        previous=full_run(page,flow)
        control = page.locator(INPUTS).nth(index)
        text_point = contact(page,control,"text",touch)
        expect(page.locator(INPUTS).nth(index)).to_be_checked(checked=before,timeout=15000)
        await_rerun(page,flow,previous)
        REPORT["controls"].append({"engine":browser_name,"viewport":view_name,
            "flow":flow,"index":index,"label":label,"box":box,"label_text":text_point,
            "box_changed":True,"label_changed":True})
        if label.startswith("I confirm this generated signature"):
            expect(page.get_by_role("button",name="Generate expense report and email draft",
                                    exact=True)).to_be_disabled()

    # Native focus + Space remains usable, independently of the pointer tests.
    keyboard = page.locator(INPUTS).first
    old = keyboard.is_checked()
    previous = full_run(page, flow)
    keyboard.focus()
    keyboard.press("Space")
    expect(page.locator(INPUTS).first).to_be_checked(checked=not old, timeout=15000)
    await_rerun(page, flow, previous)
    keyboard = page.locator(INPUTS).first
    previous = full_run(page, flow)
    keyboard.press("Space")
    expect(page.locator(INPUTS).first).to_be_checked(checked=old, timeout=15000)
    await_rerun(page, flow, previous)
    REPORT["controls"].append({"engine":browser_name,"viewport":view_name,
        "flow":flow,"keyboard_space_preserved":True})

    assert not blocked, "Unexpected external browser requests: " + repr(blocked)
    # Only a synthetic control crop, never a full form / client-named screenshot.
    page.locator(INPUTS).first.locator("xpath=ancestor::label[1]").screenshot(
        path=str(OUT / f"{flow}-{browser_name}-{view_name}.png"))


def serve(flow, root):
    fixture, port, _ = FLOWS[flow]
    url = f"http://127.0.0.1:{port}/_stcore/health"
    env = dict(os.environ)
    env.update({k:v for k,v in dotenv_values(ROOT / ".env.example").items() if v is not None})
    env.update(EPC_DATA_DIR=str(root), ANTHROPIC_API_KEY="test-only-not-used",
               SMARTSHEET_API_MODE="disabled",PDF_BACKEND="libreoffice")
    log = (OUT / (flow + "-streamlit.log")).open("w")
    proc = subprocess.Popen([sys.executable,"-m","streamlit","run",fixture,
            "--server.address","127.0.0.1", "--server.port",str(port),
            "--server.headless","true", "--browser.gatherUsageStats","false"],
            cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
    try:
        for _ in range(200):
            if proc.poll() is not None:
                raise RuntimeError(flow + " Streamlit fixture exited unexpectedly")
            try:
                with urllib.request.urlopen(url,timeout=1) as reply:
                    if reply.status == 200:
                        break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError(flow + " Streamlit health check timed out")
        return proc, log
    except Exception:
        proc.terminate()
        proc.wait(timeout=15)
        log.close()
        raise


def main():
    from shutil import which
    if not (which("libreoffice") or which("soffice")):
        raise RuntimeError("Install LibreOffice for real synthetic expense/PO fixtures")
    with sync_playwright() as p:
        for flow, (_, _, prefix) in FLOWS.items():
            with tempfile.TemporaryDirectory(prefix=prefix) as temp:
                root = Path(temp)
                if flow == "expense":
                    (root / ".synthetic-expense-fixture").write_text("synthetic only")
                proc,log = serve(flow,root)
                try:
                    for name, engine in (("chromium",p.chromium),("webkit",p.webkit)):
                        browser = engine.launch(headless=True)
                        try:
                            for view,(width,height) in VIEWS.items():
                                touch = name == "webkit" and view != "desktop"
                                context = browser.new_context(viewport={"width":width,"height":height},
                                    has_touch=touch,is_mobile=touch,accept_downloads=False)
                                page = context.new_page()
                                page.on("pageerror",lambda err: REPORT["failures"].append(
                                    {"browser_error":str(err)[:400],"flow":flow,"engine":name,"view":view}))
                                try:
                                    test_flow(page,flow,name,view,touch)
                                except Exception as exc:
                                    REPORT["failures"].append({"flow":flow,"engine":name,
                                        "viewport":view,"error":str(exc),
                                        "traceback":traceback.format_exc()[-3500:]})
                                    try:
                                        # The visible control only, not a page with account data.
                                        page.locator(INPUTS).first.locator("xpath=ancestor::label[1]").screenshot(
                                            path=str(OUT/f"failure-{flow}-{name}-{view}.png"))
                                    except Exception:
                                        pass
                                finally:
                                    context.close()
                        finally:
                            browser.close()
                finally:
                    proc.terminate()
                    proc.wait(timeout=15)
                    log.close()
    (OUT / "results.json").write_text(json.dumps(REPORT,indent=2))
    successes = len(REPORT["controls"])
    print(f"Pointer-control evidence: {successes} control pairs, {len(REPORT['failures'])} failures")
    if REPORT["failures"]:
        raise AssertionError("Pointer-control regression: " + repr(REPORT["failures"][:4]))


if __name__ == "__main__":
    main()
