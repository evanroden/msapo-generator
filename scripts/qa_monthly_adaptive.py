"""Real Monthly app DOM, actual generated previews, synthetic data only.

This starts the production QA/guided workflow on localhost:8520, using fresh
cookie namespaces in one ephemeral data root. It does not visit Render. Both
engines run once; failures retain screenshots, measured DOM and status evidence.
No retry-until-green, fake preview, source-only assertion or hardware claim.
"""
from __future__ import annotations

import hashlib
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

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.workspace_browser_observations import CLIENT_INIT, CLIENT_SNAPSHOT
OUT = ROOT / "test-artifacts" / "monthly-adaptive"
URL = "http://127.0.0.1:8520"
ACTIVITY = ".st-key-epc_pair_monthly_activity"
SCORECARDS = ".st-key-epc_pair_monthly_scorecards"
EMPTY = ".st-key-epc_pair_monthly_mbcx"
TOLERANCE = 4  # CSS pixels, after two animation frames and actual mode acknowledgment.
REPORT = {
    "synthetic_only": True,
    "actual_workflow": "monthly_report_testing_ui.render -> render_guided_workflow",
    "fixture": "unchanged production known-value prepare, then real editor edits",
    "native_preview": "production section jobs, DOCX/PDF conversion and raster store",
    "posture_evidence": "injected segment geometry; not physical hardware/Safari",
    "tolerance_css_px": TOLERANCE,
    "browsers": {},
    "checks": [],
}

# Traverse component shadow roots for diagnostics; Playwright locators already
# pierce open shadow roots, but ordinary document.querySelector does not.
DEEP = """function deep(root,selector) {
 const result=[...root.querySelectorAll(selector)];
 for(const node of root.querySelectorAll('*')) if(node.shadowRoot)
   result.push(...deep(node.shadowRoot,selector));
 return result;
} """


def check(browser, name, passed, detail=None):
    REPORT["checks"].append({"browser": browser, "name": name,
                             "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + browser + " " + name, flush=True)
    if not passed:
        raise AssertionError(name + ": " + str(detail))


def set_checkbox(container, label, selected, browser):
    control = container.get_by_role("checkbox", name=label, exact=True)
    # The locked Streamlit runtime wraps its semantic input in React Aria
    # VisuallyHidden. Click the visible semantic label just as a user does;
    # direct check() targets the clipped input and scrolls to the wrong box.
    target = control.locator("xpath=ancestor::label[1]")
    target.scroll_into_view_if_needed()
    observed = control.evaluate("""node => {
      const label=node.closest('label'), rect=label.getBoundingClientRect();
      const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      return {input:node.getBoundingClientRect().toJSON(),label:rect.toJSON(),
        parentClip:getComputedStyle(node.parentElement).clip,
        hitTag:hit?.tagName,labelOwnsHit:Boolean(hit&&label.contains(hit))};
    }""")
    if control.is_checked() != selected:
        target.click()
    expect(control).to_be_checked(checked=selected)
    check(browser, "normal label pointer sets " + label, control.is_checked() == selected, observed)


def frames(page):
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def mode(page, expected):
    page.wait_for_function("wanted => document.querySelector('.epc-workspace')?.dataset.epcMode===wanted",
                           arg=expected, timeout=20000)
    frames(page)


def inject(page, segments):
    page.evaluate("""segments => {
      Object.defineProperty(window,'viewport',{configurable:true,value:{segments}});
      window.dispatchEvent(new Event('resize'));
    }""", segments)


def snapshot(page):
    return page.evaluate("() => {" + DEEP + """
      const rect=n=>n?.getBoundingClientRect().toJSON() || null;
      const root=document.querySelector('.epc-workspace');
      const ids={}; for(const n of document.querySelectorAll('[id]'))
        ids[n.id]=(ids[n.id]||0)+1;
      return {
        mode:root?.dataset.epcMode, reason:root?.dataset.epcReason,
        viewport:{width:innerWidth,height:innerHeight},
        root:rect(root), rootScroll:root?.scrollTop,
        main:rect(document.querySelector('[data-testid="stMain"]')),
        nav:rect(document.querySelector('.st-key-monthly_report_navigation')),
        duplicateIds:Object.entries(ids).filter(([,n])=>n>1),
        pairs:[...document.querySelectorAll('.epc-workspace-pair')].map(pair=>{
          const ref=pair.querySelector('.epc-workspace-reference');
          const surface=deep(pair,'.report-preview')[0];
          const editor=pair.querySelector('.epc-workspace-editor');
          return {key:pair.querySelector('[data-epc-pair]')?.dataset.epcPair,
            active:pair.dataset.epcActive,pair:rect(pair),reference:rect(ref),
            editor:rect(editor),stickyTop:ref?parseFloat(getComputedStyle(ref).top):null,
            surface:rect(surface),status:deep(pair,'.report-preview-status')[0]?.textContent,
            page:deep(pair,'.report-preview-position')[0]?.textContent,
            zoom:deep(pair,'select[aria-label="Preview zoom"]')[0]?.value,
            images:deep(pair,'.report-preview img').map(n=>({alt:n.alt,loaded:n.complete&&n.naturalWidth>0,
              width:n.naturalWidth,height:n.naturalHeight})),
            heading:pair.querySelector('[data-epc-title]')?.dataset.epcTitle};
        }),
        qaStatus:[...document.querySelectorAll('[data-testid="stCaptionContainer"]')]
          .map(n=>n.textContent).filter(t=>/^(QA |Current fixture:|Monthly DOM )/.test(t)),
        alerts:[...document.querySelectorAll('[data-testid="stAlert"]')].map(n=>n.textContent),
        inputCount:[...document.querySelectorAll('textarea')].filter(n=>n.getAttribute('aria-label')==='Activity summary').length
      };
    }""")


def capture(page, name, label):
    observed = snapshot(page)
    observed["runtime_observations"] = page.evaluate(CLIENT_SNAPSHOT)
    REPORT["browsers"].setdefault(name, {}).setdefault("states", {})[label] = observed
    page.screenshot(path=str(OUT / f"{name}-{label}.png"), timeout=30000)
    (OUT / "results.json").write_text(json.dumps(REPORT, indent=2))
    return observed


def pair_state(observed, key):
    return next(p for p in observed["pairs"] if p["key"] == "monthly_" + key)


def scroll_pair(page, selector, inset=130):
    page.locator(selector).evaluate("""(pair,inset)=>{
      const root=pair.closest('.epc-workspace');
      const scroll=root.dataset.epcMode==='tabletop'?root:document.querySelector('[data-testid="stMain"]');
      const top=scroll===root?root.getBoundingClientRect().top:0;
      scroll.scrollTop+=pair.getBoundingClientRect().top-top-inset;
    }""", inset)
    frames(page)


def current_image(page, selector):
    pair = page.locator(selector)
    status = pair.locator(".report-preview-status")
    expect(status).to_have_text(re.compile(r"^Current · [1-9]\d* pages?$"), timeout=120000)
    image = pair.locator(".report-preview img").first
    image.wait_for(state="visible", timeout=45000)
    expect(image).to_have_js_property("complete", True, timeout=20000)
    page.wait_for_function("""selector => {""" + DEEP + """
      const pair=document.querySelector(selector);
      return pair && deep(pair,'.report-preview img').some(n=>n.complete&&n.naturalWidth>0);
    }""", arg=selector, timeout=20000)
    return pair


def editor_state(field):
    return field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd,focused:document.activeElement===n,identity:n===window.__monthlyActivityNode})")


def exercise(browser_type, name):
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    attempts, errors = [], []
    context.add_init_script(CLIENT_INIT)
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": URL}])
    context.add_init_script("""window.__monthlyShareAttempts=[];
      Object.defineProperty(navigator,'share',{configurable:true,value:()=>{
        window.__monthlyShareAttempts.push('share');
        return Promise.reject(new Error('Native sharing is forbidden in synthetic QA'));
      }});""")

    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"data", "blob"} or (parsed.hostname == "127.0.0.1" and parsed.port == 8520):
            request.continue_()
        else:
            attempts.append(parsed.scheme + ":" + (parsed.hostname or "external"))
            request.abort()

    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
        page.get_by_role("textbox", name="Activity summary", exact=True).wait_for(timeout=60000)
        page.wait_for_selector(".epc-workspace-row", timeout=30000)
        mode(page, "wide")
        page.get_by_role("button", name="Compare fixture facts", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA comparison completed: known-value prefill · 18/18"))).to_be_visible(timeout=60000)
        check(name, "actual known-value pipeline independently checks 18/18", True)

        field = page.get_by_role("textbox", name="Activity summary", exact=True)
        original = field.input_value()
        # Edit the actual authoritative field, not an oracle or a mocked parser.
        # Repeated explicitly synthetic notes yield genuine multipage section PDF.
        long_text = original + "\n\n" + "\n\n".join(
            f"Synthetic layout note {n:02d}: TEST ONLY. The invented September strainer cleaning and inspection record is repeated to exercise native paragraph wrapping and continuation pages."
            for n in range(1, 41))
        field.fill(long_text)
        field.press("Tab")
        digest = hashlib.sha256(long_text.encode()).hexdigest()
        expect(page.get_by_text("QA durable Activity SHA256: " + digest, exact=True)).to_be_visible(timeout=60000)
        # Genuine controls make a long editing section without synthetic padding,
        # alternate editors, forced preview height or eager rendering all sections.
        for label in ("Add work-order spreadsheets", "Add reviewed vendor service pages"):
            set_checkbox(page.locator(ACTIVITY), label, True, name)
        scroll_pair(page, ACTIVITY)
        actual = current_image(page, ACTIVITY)
        baseline = capture(page, name, "actual-activity-current")
        activity = pair_state(baseline, "activity")
        check(name, "actual generated Activity imagery is mounted", bool(activity["surface"]) and any(i["loaded"] for i in activity["images"]), activity)
        check(name, "Activity preview is its section output", all(activity["heading"] in i["alt"] for i in activity["images"]), activity["images"])
        check(name, "long text produced real multiple preview pages", int(activity["page"].split("/")[1]) >= 2, activity["page"])
        duplicates = baseline["duplicateIds"]
        framework = [item for item in duplicates if "glide" in item[0].lower()]
        REPORT["browsers"][name]["framework_duplicate_ids"] = framework
        application = [item for item in duplicates if item not in framework]
        check(name, "document IDs unique apart from reported framework glide IDs", not application, application)
        check(name, "one authoritative Activity editor", page.get_by_role("textbox", name="Activity summary", exact=True).count() == 1)

        # All measurements are from the production section/preview/nav wrappers.
        page.locator(ACTIVITY).evaluate("""pair=>{
          const ref=pair.querySelector('.epc-workspace-reference');
          const main=document.querySelector('[data-testid="stMain"]');
          const top=parseFloat(getComputedStyle(ref).top);
          main.scrollTop+=ref.getBoundingClientRect().top-top+48;
        }""")
        frames(page)
        pinned = capture(page, name, "actual-activity-pinned")
        ap = pair_state(pinned, "activity")
        check(name, "natural Activity has a usable sticky interval", ap["pair"]["bottom"] - ap["stickyTop"] - ap["reference"]["height"] >= 16, ap)
        check(name, "own preview pins below measured navigation", abs(ap["reference"]["top"] - ap["stickyTop"]) <= TOLERANCE and ap["reference"]["top"] >= pinned["nav"]["bottom"] - TOLERANCE, {"activity": ap, "nav": pinned["nav"]})
        check(name, "real shadow viewer fits available height", ap["surface"]["bottom"] <= 900 + TOLERANCE and ap["surface"]["height"] > 100, ap)
        check(name, "preview remains right of its single editor", ap["reference"]["left"] > ap["pair"]["left"] + 200, ap)
        actual.get_by_label("Preview zoom", exact=True).select_option("1.25")
        actual.get_by_role("button", name="Next preview page", exact=True).click()
        frames(page)
        before_view = pair_state(snapshot(page), "activity")
        check(name, "actual page navigation advances", before_view["page"].startswith("2 /"), before_view["page"])
        page.locator(ACTIVITY).evaluate("""pair=>{
          const main=document.querySelector('[data-testid="stMain"]');
          main.scrollTop+=pair.getBoundingClientRect().bottom-220;
        }""")
        frames(page)
        boundary = capture(page, name, "actual-forward-boundary")
        old = pair_state(boundary, "activity")
        next_section = pair_state(boundary, "scorecards")
        check(name, "preview releases within its own section", old["reference"]["bottom"] <= old["pair"]["bottom"] + TOLERANCE, old)
        check(name, "next preview arrives in normal section order", next_section["pair"]["top"] >= old["pair"]["bottom"] - TOLERANCE and next_section["reference"]["top"] >= old["reference"]["bottom"] - TOLERANCE, {"previous": old, "next": next_section})
        scroll_pair(page, ACTIVITY)
        current_image(page, ACTIVITY)
        returned = pair_state(capture(page, name, "actual-reverse-boundary"), "activity")
        check(name, "return preserves output page and zoom", (returned["page"], returned["zoom"]) == (before_view["page"], before_view["zoom"]), {"before": before_view, "returned": returned})
        returned_image = actual.locator('figure[data-index="1"] img')
        expect(returned_image).to_be_visible(timeout=30000)
        expect(returned_image).to_have_js_property('complete', True)
        check(name, "returned selected page actually decoded", returned_image.evaluate('n=>n.naturalWidth>0'))

        # Keep one unblurred native input/node alive through all display changes.
        field.click()
        field.fill(long_text + "\nSynthetic unblurred transition marker.")
        field.evaluate("n=>{window.__monthlyActivityNode=n;n.setSelectionRange(6,17)}")
        before = editor_state(field)
        page.set_viewport_size({"width": 1280, "height": 900})
        mode(page, "wide")
        check(name, "unblurred input survives resize", editor_state(field) == before)
        page.set_viewport_size({"width": 1440, "height": 900})
        inject(page, [{"x": 0, "y": 0, "width": 650, "height": 900}, {"x": 690, "y": 0, "width": 750, "height": 900}])
        # The real setup sidebar puts the app at x=380. A 650px first
        # segment leaves less than the required 360px editor width. Its
        # honest compact fallback is required, not a failed book layout.
        mode(page, "compact")
        check(name, "sidebar-constrained segment uses honest fallback", editor_state(field) == before)
        inject(page, [{"x": 0, "y": 0, "width": 820, "height": 900}, {"x": 860, "y": 0, "width": 580, "height": 900}])
        mode(page, "book")
        book = capture(page, name, "actual-book")
        check(name, "unblurred input focus and selection survive book", editor_state(field) == before)
        check(name, "actual book preview clears measured crease", pair_state(book, "activity")["reference"]["left"] >= 860 - TOLERANCE, pair_state(book, "activity"))
        inject(page, [{"x": 0, "y": 0, "width": 1440, "height": 380}, {"x": 0, "y": 410, "width": 1440, "height": 490}])
        mode(page, "tabletop")
        tabletop = capture(page, name, "actual-tabletop")
        check(name, "unblurred input focus and selection survive tabletop", editor_state(field) == before)
        active = [p for p in tabletop["pairs"] if p["active"] == "true"]
        check(name, "tabletop shows matching Activity above lower editor", len(active) == 1 and active[0]["key"] == "monthly_activity" and active[0]["reference"]["bottom"] <= 380 + TOLERANCE, active)
        check(name, "one lower working scroll root", tabletop["root"]["top"] >= 410 - TOLERANCE and tabletop["root"]["bottom"] <= 900 + TOLERANCE, tabletop["root"])
        inject(page, None)
        mode(page, "wide")
        check(name, "unblurred input survives unfolding", editor_state(field) == before)
        field.press("Tab")
        committed = before["value"]
        expect(page.get_by_text("QA durable Activity SHA256: " + hashlib.sha256(committed.encode()).hexdigest(), exact=True)).to_be_visible(timeout=60000)
        current_image(page, ACTIVITY)

        scroll_pair(page, EMPTY)
        frames(page)
        empty = pair_state(capture(page, name, "actual-short-empty-section"), "mbcx")
        check(name, "empty section avoids fabricated screenful padding", empty["pair"]["height"] < 1600, empty)
        page.set_viewport_size({"width": 390, "height": 844})
        mode(page, "compact")
        scroll_pair(page, ACTIVITY, inset=80)
        check(name, "compact still has one current Activity editor", field.count() == 1 and field.input_value() == committed)
        check(name, "compact contains whole-page horizontal overflow", page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+2"))
        page.locator(ACTIVITY).get_by_role("button", name="View preview", exact=True).click()
        current_image(page, ACTIVITY)
        page.locator(ACTIVITY).get_by_role("button", name="Back to editing", exact=True).click()
        check(name, "compact preview returns to same editor", field.is_visible() and field.input_value() == committed)
        capture(page, name, "actual-compact-return")
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        check(name, "zero external browser requests or sharing", not attempts and not page.evaluate("window.__monthlyShareAttempts.length"), attempts)
        check(name, "no uncaught browser errors", not errors, errors)
    except Exception as exc:
        REPORT["browsers"].setdefault(name, {})["failure"] = {"type": type(exc).__name__, "message": str(exc)[:3000], "traceback": traceback.format_exc(), "browser_errors": errors, "blocked_external": attempts}
        try:
            capture(page, name, "failure")
        except Exception as capture_error:
            REPORT["browsers"][name]["capture_failure"] = str(capture_error)[:500]
        raise
    finally:
        context.close()
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    completed = False
    with tempfile.TemporaryDirectory(prefix="monthly-dom-synthetic-") as temp:
        (Path(temp) / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        env = dict(os.environ, EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "tests/fixtures/workspaces/monthly_app.py", "--server.address", "127.0.0.1", "--server.port", "8520", "--server.headless", "true", "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Actual Monthly synthetic fixture stopped during startup")
                    try:
                        with urllib.request.urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Actual Monthly fixture health not ready")
                with sync_playwright() as playwright:
                    for browser_type, name in ((playwright.chromium, "chromium"), (playwright.webkit, "playwright-webkit")):
                        try:
                            exercise(browser_type, name)
                        except Exception as exc:
                            failures.append(name + ": " + type(exc).__name__ + ": " + str(exc)[:300])
                completed = True
            finally:
                process.terminate()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                REPORT["failures"] = failures
                REPORT["result"] = "passed" if completed and not failures else "failed"
                (OUT / "results.json").write_text(json.dumps(REPORT, indent=2))
    if failures:
        raise AssertionError("Actual Monthly DOM failures: " + "; ".join(failures))


if __name__ == "__main__":
    main()
