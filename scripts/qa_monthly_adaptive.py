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


def exercise_site_selection(page, browser):
    """Real pointer and keyboard input must change the server-selected sites.

    The public Cloud Browser observed a label click with no state transition
    while Space worked. This runs actual Playwright mouse input once in each
    engine; no DOM click(), state injection or retry/fallback can mask failure.
    """
    north = page.get_by_role("checkbox", name="Demo North", exact=True)
    south = page.get_by_role("checkbox", name="Demo South", exact=True)
    activity = page.get_by_role("textbox", name="Activity summary", exact=True)
    original = activity.input_value()
    disclosure = page.get_by_text("Change report sites", exact=True)
    label = south.locator("xpath=ancestor::label[1]")
    if not label.is_visible() and disclosure.count():
        disclosure.click()
    label.scroll_into_view_if_needed()
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
      ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=45000)
    expect(north).to_be_checked()
    expect(south).to_be_checked()
    diagnostics = south.evaluate("""node => {
      const label=node.closest('label'), rect=label.getBoundingClientRect();
      const hit=document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2);
      window.__siteSelectionEvents=[];
      const events=['pointerdown','pointerup','mousedown','mouseup','click','keydown','keyup','focusin'];
      const listener=event=>{
        if(window.__siteSelectionEvents.length<30) window.__siteSelectionEvents.push({
          type:event.type,trusted:event.isTrusted,target:event.target.tagName,
          pointerType:event.pointerType||'',key:event.key||'',checked:node.checked});
      };
      for(const type of events) label.addEventListener(type,listener,true);
      window.__siteSelectionCleanup=()=>{for(const type of events) label.removeEventListener(type,listener,true);};
      return {checked:node.checked,disabled:node.disabled,input:node.getBoundingClientRect().toJSON(),
        label:rect.toJSON(),parentClip:getComputedStyle(node.parentElement).clip,
        hitTag:hit?.tagName,labelOwnsHit:Boolean(hit&&label.contains(hit)),
        pressable:label.getAttribute('data-react-aria-pressable')};
    }""")
    REPORT["browsers"].setdefault(browser, {})["site_selection"] = diagnostics
    try:
        # The disclosure and report/preview reruns can move the label after a
        # saved coordinate is sampled. Click the ACTUAL live label once using
        # Playwright's native pointer actionability/geometry, not DOM click(),
        # not a cached pixel, and never a retry/fallback to keyboard input.
        # An earlier failed main artifact showed the old y=505 sample versus
        # the same site at y=638 in its screenshot, with zero label events.
        expect(label).to_be_visible()
        label.click()
        expect(south).not_to_be_checked()
        expect(page.locator(".st-key-monthly_report_identity_sites")).to_contain_text("Site: Demo North", timeout=45000)
        expect(activity).to_have_count(0)
        check(browser, "native mouse unchecks a site and the server opens its exact single-site selection", True)
        # Move to a genuine unselected widget state using normal browser
        # pointer actions. A single label click must then start that site;
        # no synthetic session-state patch or keyboard fallback is permitted.
        north_label = north.locator("xpath=ancestor::label[1]")
        north_label.click()
        expect(north).not_to_be_checked()
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible(timeout=45000)
        check(browser, "both sites can be deselected by native pointer", True)
        label.click()
        expect(south).to_be_checked()
        expect(north).not_to_be_checked()
        expect(page.locator(".st-key-monthly_report_identity_sites")).to_contain_text("Site: Demo South", timeout=45000)
        check(browser, "one native label click starts from zero selected sites", True)
        north_label.click()
        expect(north).to_be_checked()
        expect(south).to_be_checked()
        expect(page.locator(".st-key-monthly_report_identity_sites")).to_contain_text("Sites: Demo North; Demo South", timeout=45000)
        expect(activity).to_have_value(original, timeout=45000)
        # Deliberately exercise keyboard separately, not as a failed-click
        # fallback. Existing combined-report draft returns after restoration.
        south.press("Space")
        expect(south).not_to_be_checked()
        south.press("Space")
        expect(south).to_be_checked()
        expect(activity).to_have_value(original, timeout=45000)
        check(browser, "keyboard works independently and combined draft returns intact", True)
        capture(page, browser, "site-selection-zero-pointer-keyboard")
    finally:
        diagnostics["events"] = page.evaluate("window.__siteSelectionEvents||[]")
        diagnostics["after"] = south.evaluate("""node=>({checked:node.checked,disabled:node.disabled,
          focused:document.activeElement===node,scriptState:document.querySelector('[data-testid="stApp"]')
          ?.getAttribute('data-test-script-state')})""")
        page.evaluate("window.__siteSelectionCleanup?.()")


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


def scroll_pair(page, selector, inset=130, *, preview=False):
    # Python's notRunning receipt can precede the workspace component mounting
    # its layout classes after reload. A mode receipt alone can precede the
    # requested pair's discovery; require that row's actual CSS and surfaces
    # before this one scroll. In compact mode an
    # open preview follows the editor; moving the SECTION top into view would
    # move that preview back below the viewport.
    page.wait_for_function("""wanted => {""" + DEEP + r"""
      const pair=document.querySelector(wanted.selector);
      const root=pair?.closest('.epc-workspace');
      const mode=root?.dataset.epcMode;
      if(!['wide','book','tabletop','compact'].includes(mode))return false;
      if(!pair.classList.contains('epc-workspace-pair'))return false;
      const editor=pair.querySelector('.epc-workspace-editor');
      const reference=pair.querySelector('.epc-workspace-reference');
      const editColumn=editor?.closest('.epc-editor-column');
      const refColumn=reference?.closest('.epc-reference-column');
      const row=editColumn?.parentElement;
      if(!row||row!==refColumn?.parentElement||!row.classList.contains('epc-workspace-row'))return false;
      const rowStyle=getComputedStyle(row);
      const columns=rowStyle.gridTemplateColumns?.trim().split(/\s+/);
      if(rowStyle.display!=='grid'||columns?.length!==(['compact','tabletop'].includes(mode)?1:2))return false;
      if(!editor.getClientRects().length||editor.getBoundingClientRect().width<=0)return false;
      if(mode==='compact'){
        if(Math.abs(editColumn.getBoundingClientRect().width-row.getBoundingClientRect().width)>2)return false;
        const closed=pair.dataset.epcPreviewOpen!=='true';
        if(closed&&(getComputedStyle(refColumn).display!=='none'||reference.getClientRects().length))return false;
        if(!closed&&!reference.getClientRects().length)return false;
      }
      const scroll=mode==='tabletop'||root.dataset.epcConfined==='true'
        ?root:document.querySelector('[data-testid="stMain"]');
      if(!scroll)return false;
      let target=pair;
      if(wanted.preview&&mode==='compact'){
        if(pair.dataset.epcPreviewOpen!=='true')return false;
        target=deep(pair,'.report-preview')[0];
        if(!target||!target.getClientRects().length)return false;
      }
      const top=scroll===root?root.getBoundingClientRect().top:0;
      scroll.scrollTop+=target.getBoundingClientRect().top-top-wanted.inset;
      return true;
    }""", arg={"selector": selector, "inset": inset, "preview": preview}, timeout=20000)
    frames(page)
    if preview:
        expect(page.locator(selector).locator('.report-preview')).to_be_in_viewport(ratio=0.5)


# A decoded divider can precede the viewer's automatic selected-page mount.
# Check the intended page and its current status in the same browser evaluation.
CURRENT_IMAGE_READY = r"""
 const pair=document.querySelector(wanted.selector);
 if (!pair) return false;
 let images=deep(pair,'.report-preview img');
 if (wanted.selected_page != null) {
   const status=deep(pair,'.report-preview-status')[0]?.textContent || '';
   const position=deep(pair,'.report-preview-position')[0]?.textContent || '';
   if (!/^Current · [1-9]\d* pages?$/.test(status) ||
       !position.startsWith(wanted.selected_page + ' /')) return false;
   images=deep(pair,'.report-preview figure[data-index="' +
     (wanted.selected_page - 1) + '"] img');
 }
 return images.some(n=>n.complete && n.naturalWidth>0);
"""


def current_image(page, selector, *, selected_page=None):
    pair = page.locator(selector)
    status = pair.locator(".report-preview-status")
    expect(status).to_have_text(re.compile(r"^Current · [1-9]\d* pages?$"), timeout=120000)
    image_selector = (".report-preview img" if selected_page is None else
                      f'.report-preview figure[data-index="{selected_page - 1}"] img')
    image = pair.locator(image_selector).first
    image.wait_for(state="visible", timeout=45000)
    expect(image).to_have_js_property("complete", True, timeout=20000)
    wanted = {"selector": selector}
    if selected_page is not None:
        wanted["selected_page"] = selected_page
    page.wait_for_function("wanted => {" + DEEP + CURRENT_IMAGE_READY + "}",
                           arg=wanted, timeout=20000)
    return pair


def editor_state(field):
    return field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd,focused:document.activeElement===n,identity:n===window.__monthlyActivityNode})")


def exercise_section_navigation(page, browser, field):
    """One native selector, including the otherwise confined Review boundary.

    select_option exercises the real HTML select's change path. This is not a
    physical device/native popup claim; the served keyboard check stays distinct.
    """
    selector = page.get_by_role("combobox", name="Jump to section", exact=True)
    expect(selector).to_have_count(1)
    expect(selector).to_be_enabled()
    labels = page.locator(".epc-workspace-pair [data-epc-title]").evaluate_all(
        "nodes=>nodes.map(n=>n.dataset.epcTitle)")
    check(browser, "one selector uses every editor heading in report order",
          selector.locator("option").all_text_contents() == labels + ["Review and download"])
    inject(page, [{"x": 0, "y": 0, "width": 1440, "height": 380},
                  {"x": 0, "y": 410, "width": 1440, "height": 490}])
    mode(page, "tabletop")
    # Place the section marker across the selector's actual reading line.
    # The former 110px inset left Activity below that line in the lower pane;
    # its current-section assertion described a different visible section.
    nav_height = selector.evaluate("n=>n.closest('.epc-section-navigation').getBoundingClientRect().height")
    scroll_pair(page, ACTIVITY, inset=max(0, nav_height - 4))
    expect(selector).to_be_in_viewport(ratio=1)
    expect(selector).to_have_value("monthly_activity")
    field.evaluate("n=>{window.__monthlyNavigationNode=n;}")
    before_field = field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd})")
    before_offset = page.locator(ACTIVITY).evaluate("n=>n.getBoundingClientRect().top-n.closest('.epc-workspace').getBoundingClientRect().top")
    before_runtime = page.evaluate(CLIENT_SNAPSHOT)["server"]
    selector.select_option("report_review")
    mode(page, "compact")
    expect(page.locator("#report-review")).to_be_in_viewport()
    check(browser, "Review exits only the confined display and stays reachable", page.evaluate("""() => {
      const root=document.querySelector('.epc-workspace'), main=document.querySelector('[data-testid="stMain"]');
      return root.dataset.epcReviewOpen==='true' && root.dataset.epcReason==='review-navigation' &&
        root.dataset.epcConfined!=='true' && !main.classList.contains('epc-workspace-scroll-owner');
    }"""))
    expect(selector).to_be_in_viewport()
    capture(page, browser, "selector-tabletop-review")
    selector.select_option("monthly_activity")
    mode(page, "tabletop")
    after_offset = page.locator(ACTIVITY).evaluate("n=>n.getBoundingClientRect().top-n.closest('.epc-workspace').getBoundingClientRect().top")
    check(browser, "section selection restores actual lower-editor reading position", abs(after_offset-before_offset) <= TOLERANCE,
          {"before": before_offset, "after": after_offset})
    check(browser, "selector preserves the same native Activity input and pending selection",
          field.evaluate("n=>n===window.__monthlyNavigationNode") and
          field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd})") == before_field)
    after_runtime = page.evaluate(CLIENT_SNAPSHOT)["server"]
    check(browser, "section navigation avoids full reruns and report changes",
          before_runtime["full_runs"] == after_runtime["full_runs"] and
          before_runtime["draft_hashes"] == after_runtime["draft_hashes"],
          {"before": before_runtime, "after": after_runtime})
    capture(page, browser, "selector-tabletop-return")
    inject(page, None)
    mode(page, "wide")


def exercise_natural_review_navigation(page, browser, field, layout):
    """Observe ordinary page scrolling across Review, without choosing its option."""
    selector = page.get_by_role("combobox", name="Jump to section", exact=True)
    field.evaluate("n=>{window.__monthlyNaturalNavigationNode=n;}")
    before_field = field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd})")
    before_runtime = page.evaluate(CLIENT_SNAPSHOT)["server"]
    page.evaluate("""() => {
      const main=document.querySelector('[data-testid="stMain"]');
      const review=document.querySelector('#report-review');
      const nav=document.querySelector('.epc-section-navigation');
      const header=document.querySelector('[data-testid="stHeader"]');
      const line=Math.max(main.getBoundingClientRect().top,header?.getBoundingClientRect().bottom||0)+nav.getBoundingClientRect().height+12;
      main.scrollTop+=review.getBoundingClientRect().top-line+16;
    }""")
    page.wait_for_function("document.querySelector('.epc-workspace')?.dataset.epcReviewOpen==='true'")
    frames(page)
    expect(selector).to_be_in_viewport()
    expect(selector).to_have_value("report_review")
    capture(page, browser, "selector-natural-review-" + layout)
    scroll_pair(page, ACTIVITY, inset=130)
    page.wait_for_function("document.querySelector('.epc-workspace')?.dataset.epcReviewOpen==='false'")
    expect(selector).to_be_in_viewport()
    expect(selector).to_have_value("monthly_activity")
    after_runtime = page.evaluate(CLIENT_SNAPSHOT)["server"]
    check(browser, layout + " natural Review and reverse scroll retain navigation and native input",
          field.evaluate("n=>n===window.__monthlyNaturalNavigationNode") and
          field.evaluate("n=>({value:n.value,start:n.selectionStart,end:n.selectionEnd})") == before_field and
          before_runtime["full_runs"] == after_runtime["full_runs"] and
          before_runtime["draft_hashes"] == after_runtime["draft_hashes"],
          {"before": before_runtime, "after": after_runtime})


def reading_state(field):
    return field.evaluate("""node => {
      const rect=node.getBoundingClientRect();
      let owner=node.parentElement;
      while(owner && !(owner.scrollHeight>owner.clientHeight && /auto|scroll/.test(getComputedStyle(owner).overflowY)))
        owner=owner.parentElement;
      owner=owner||document.scrollingElement;
      return {y:rect.y,height:rect.height,scrollTop:node.scrollTop,scrollLeft:node.scrollLeft,
        start:node.selectionStart,end:node.selectionEnd,focused:document.activeElement===node,
        sameNode:node===window.__monthlyActivityNode,
        owner:{testid:owner.dataset.testid||'',top:owner.scrollTop,height:owner.clientHeight}};
    }""")


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
    from workspace_wire_observations import WireObservations
    wire = WireObservations(8520)
    wire.attach(page)
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
        exercise_site_selection(page, name)

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
        manager = page.locator(ACTIVITY).get_by_role("button", name="Manage source files", exact=True)
        manager.click()
        expect(page.locator(ACTIVITY).get_by_text("Read source files, check their pages, or match spreadsheet columns.", exact=True)).to_be_visible()
        check(name, "native source-manager button opens the broad file tools", True)
        check(name, "vendor pages have no competing Activity checkbox",
              page.locator(ACTIVITY).get_by_role("checkbox", name="Add reviewed vendor service pages", exact=True).count() == 0)
        scroll_pair(page, ACTIVITY)
        actual = current_image(page, ACTIVITY, selected_page=2)
        baseline = capture(page, name, "actual-activity-current")
        activity = pair_state(baseline, "activity")
        check(name, "actual generated Activity imagery is mounted", bool(activity["surface"]) and any(i["loaded"] for i in activity["images"]), activity)
        check(name, "Activity preview is its section output", all(activity["heading"] in i["alt"] for i in activity["images"]), activity["images"])
        check(name, "long text produced real multiple preview pages", int(activity["page"].split("/")[1]) >= 2, activity["page"])
        check(name, "first real Activity preview opens after its identified title divider",
              activity["page"].startswith("2 /"), activity["page"])
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
        # All pages belong to a single normal scrollport: no page, zoom,
        # fit or enlarge application controls should exist in any workflow.
        controls = actual.locator(
            '.report-preview-tools, [data-action="previous"], [data-action="next"], '
            '[data-action="enlarge"], select[aria-label="Preview zoom"]')
        check(name, "no preview page/zoom/enlarge toolbar", controls.count() == 0)
        preview_scroll = actual.locator(".report-preview-scroll")
        preview_scroll.press("Home")
        expect(actual.locator(".report-preview-position")).to_have_text(re.compile(r"^1 /"))
        divider_image = actual.locator('figure[data-index="0"] img')
        expect(divider_image).to_be_visible(timeout=30000)
        expect(divider_image).to_have_js_property('complete', True)
        check(name, "native keyboard still reaches the retained divider page",
              divider_image.evaluate('node=>node.naturalWidth>0'))
        distance = preview_scroll.evaluate("""node => {
          const second=node.querySelector('figure[data-index="1"]');
          if (!second) throw Error('The real report has no second preview page');
          return second.offsetTop-node.offsetTop+16-node.scrollTop;
        }""")
        preview_scroll.hover()
        page.mouse.wheel(0, distance)
        expect(actual.locator(".report-preview-position")).to_have_text(
            re.compile(r"^2 /"), timeout=20000)
        before_view = pair_state(snapshot(page), "activity")
        check(name, "natural continuous preview scroll advances to page two",
              before_view["page"].startswith("2 /"), before_view["page"])
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
        check(name, "return preserves output reading page", returned["page"] == before_view["page"],
              {"before": before_view, "returned": returned})
        returned_image = actual.locator('figure[data-index="1"] img')
        expect(returned_image).to_be_visible(timeout=30000)
        expect(returned_image).to_have_js_property('complete', True)
        check(name, "returned selected page actually decoded", returned_image.evaluate('n=>n.naturalWidth>0'))
        updates = page.evaluate(CLIENT_SNAPSHOT)['server']
        previous_updates = baseline['runtime_observations']['server']
        check(name, "preview scrolling and section scrolling avoid full-app reruns",
              updates['full_runs'] == previous_updates['full_runs'],
              {'before':previous_updates,'after':updates})
        check(name, "actual Monthly preview requests run inside fragments",
              updates['preview_fragment_runs'] > previous_updates['preview_fragment_runs'],
              {'before':previous_updates['preview_fragment_runs'],'after':updates['preview_fragment_runs']})

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
        # A layout acknowledgment alone can precede the visible raster receipt.
        # The selected actual page must survive/recover without blurring input.
        book_image = actual.locator('figure[data-index="1"] img')
        expect(book_image).to_be_visible(timeout=30000)
        expect(book_image).to_have_js_property('complete', True)
        check(name, "book selected native page actually decoded", book_image.evaluate('n=>n.naturalWidth>0'))
        book = capture(page, name, "actual-book")
        check(name, "unblurred input focus and selection survive book", editor_state(field) == before)
        check(name, "actual book preview clears measured crease", pair_state(book, "activity")["reference"]["left"] >= 860 - TOLERANCE, pair_state(book, "activity"))
        inject(page, [{"x": 0, "y": 0, "width": 1440, "height": 380}, {"x": 0, "y": 410, "width": 1440, "height": 490}])
        mode(page, "tabletop")
        current_image(page, ACTIVITY)
        expect(actual.locator('figure[data-index="1"] img')).to_be_visible(timeout=30000)
        expect(actual.locator('figure[data-index="1"] img')).to_have_js_property('complete', True)
        check(name, "tabletop selected native page actually decoded",
              actual.locator('figure[data-index="1"] img').evaluate('n=>n.naturalWidth>0'))
        title = actual.locator('.epc-context-title')
        expect(title).to_have_text('Monthly Activity Summary')
        check(name, "tabletop title is clear of persistent chrome", title.evaluate('''n=>{
            const r=n.getBoundingClientRect(), hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return Boolean(hit&&n.contains(hit));
        }'''))
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
        exercise_section_navigation(page, name, field)
        exercise_natural_review_navigation(page, name, field, "wide")

        scroll_pair(page, EMPTY)
        frames(page)
        empty = pair_state(capture(page, name, "actual-short-empty-section"), "mbcx")
        check(name, "empty section avoids fabricated screenful padding", empty["pair"]["height"] < 1600, empty)
        page.set_viewport_size({"width": 390, "height": 844})
        mode(page, "compact")
        scroll_pair(page, ACTIVITY, inset=80)
        expect(page.get_by_role("combobox", name="Jump to section", exact=True)).to_be_in_viewport()
        check(name, "compact still has one current Activity editor", field.count() == 1 and field.input_value() == committed)
        check(name, "compact contains whole-page horizontal overflow", page.evaluate("document.documentElement.scrollWidth<=document.documentElement.clientWidth+2"))
        navigation_runs = page.evaluate(CLIENT_SNAPSHOT)['server']['full_runs']
        for action in ("pointer", "keyboard"):
            field.click()
            field.press("Control+End")
            frames(page)
            prior_reading = reading_state(field)
            check(name, action + " return starts in the existing scrolled native editor",
                  prior_reading['sameNode'] and prior_reading['focused'] and prior_reading['scrollTop'] > 0,
                  prior_reading)
            open_preview = page.locator(ACTIVITY).get_by_role("button", name="View preview", exact=True)
            if action == "pointer":
                open_preview.click()
            else:
                open_preview.press("Enter")
            current_image(page, ACTIVITY)
            back = page.locator(ACTIVITY).get_by_role("button", name="Back to editing", exact=True)
            if action == "pointer":
                back.click()
            else:
                back.press("Enter")
            frames(page)
            returned_reading = reading_state(field)
            check(name, action + " preview return keeps native node, caret and inner reading position",
                  returned_reading['sameNode'] and field.input_value() == committed
                  and (returned_reading['start'], returned_reading['end']) == (prior_reading['start'], prior_reading['end'])
                  and abs(returned_reading['scrollTop'] - prior_reading['scrollTop']) <= TOLERANCE
                  and abs(returned_reading['scrollLeft'] - prior_reading['scrollLeft']) <= TOLERANCE,
                  {'before':prior_reading,'returned':returned_reading})
            check(name, action + " preview return restores the editing field reading position",
                  abs(returned_reading['y'] - prior_reading['y']) <= TOLERANCE,
                  {'before':prior_reading,'returned':returned_reading})
            check(name, action + " preview return uses the intended native focus",
                  returned_reading['focused'] == (action == "keyboard"), returned_reading)
        check(name, "preview entry and return do not submit the unchanged report",
              page.evaluate(CLIENT_SNAPSHOT)['server']['full_runs'] == navigation_runs)
        capture(page, name, "actual-compact-return")
        exercise_natural_review_navigation(page, name, field, "compact")
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
        (OUT / (name + "-wire.json")).write_text(json.dumps(wire.snapshot(), indent=2))
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
