"""Actual Water upload/review/removal/reload journey inside existing synthetic QA.

Reuses qa_monthly_adaptive's guarded localhost server and browser geometry.
No production route, paid reader, live storage, hidden state injection or retry.
"""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import posixpath
import re
from zipfile import ZipFile
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf
from playwright.sync_api import expect

WATER = ".st-key-epc_pair_monthly_water"
CAPTION = "Synthetic conductivity check; follow-up remains pending."
NAME = "Synthetic water treatment - long source name for the September review.pdf"


def assert_docx_water_pages(word, expected_pages):
    """Check real inline picture references and caption adjacency, not media alone.

    This is the synthetic journey's OOXML order/content assertion. It does not
    establish Microsoft Word pagination, rendered legibility or PDF image order.
    """
    from collections import Counter
    from lxml import etree
    from urllib.parse import unquote, urlsplit

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    expected = [item["asset"].split(".")[0] for item in expected_pages]
    assert expected and len(set(expected)) == len(expected), "Water fixture needs distinct expected page images"

    def text(paragraph):
        parts = []
        for node in paragraph.iter():
            if node.tag == "{" + ns["w"] + "}t":
                parts.append(node.text or "")
            elif node.tag == "{" + ns["w"] + "}tab":
                parts.append("\t")
            elif node.tag == "{" + ns["w"] + "}cr" or (
                    node.tag == "{" + ns["w"] + "}br"
                    and node.get("{" + ns["w"] + "}type") not in ("page", "column")):
                parts.append("\n")
        return "".join(parts)

    with ZipFile(BytesIO(word)) as package:
        xml = etree.fromstring(package.read("word/document.xml"))
        body = xml.find("w:body", ns)
        assert body is not None, "DOCX has no document body"
        relationships = etree.fromstring(package.read("word/_rels/document.xml.rels"))
        links = {item.get("Id"): item for item in relationships}
        occurrences = []
        for blip in body.findall(".//a:blip", ns):
            identity = blip.get("{" + ns["r"] + "}embed")
            assert identity in links, "DOCX picture has no embedded image relationship"
            link = links[identity]
            assert (link.get("Type", "").endswith("/image")
                    and link.get("TargetMode") != "External"), "DOCX picture is not an internal image"
            target = urlsplit(link.get("Target", ""))
            assert not target.scheme and not target.netloc, "DOCX picture target is external"
            path = unquote(target.path)
            part = posixpath.normpath(path.lstrip("/") if path.startswith("/") else posixpath.join("word", path))
            assert not part.startswith("../") and part in package.namelist(), "DOCX picture target is missing"
            digest = sha256(package.read(part)).hexdigest()
            if digest not in expected:
                continue
            assert blip.xpath("ancestor::wp:inline", namespaces=ns), "Water page picture must be inline"
            assert not blip.xpath("ancestor::wp:anchor", namespaces=ns), "Water page picture is floating"
            paragraph = next((node for node in blip.iterancestors() if node.tag == "{" + ns["w"] + "}p"), None)
            assert paragraph is not None, "Water page picture has no paragraph"
            assert not any(item["paragraph"] is paragraph for item in occurrences), "Water pages share one picture paragraph"
            following = paragraph.getnext()
            caption = ""
            if following is not None and following.tag == "{" + ns["w"] + "}p":
                style = following.find("w:pPr/w:pStyle", ns)
                style_name = style.get("{" + ns["w"] + "}val", "") if style is not None else ""
                if (not following.findall(".//w:drawing", ns)
                        and not following.findall(".//w:sectPr", ns)
                        and not style_name.startswith(("Heading", "Title"))):
                    caption = text(following)
            occurrences.append({"asset_sha256": digest, "relationship": identity,
                                "part": part, "caption_sha256": sha256(caption.encode()).hexdigest(),
                                "paragraph": paragraph})
        assert [item["asset_sha256"] for item in occurrences] == expected, "DOCX Water inline page order/count differs from the working report"
        for actual, wanted in zip(occurrences, expected_pages):
            assert actual["caption_sha256"] == wanted["caption_sha256"], "DOCX Water caption is missing, changed or attached to the wrong page"
        # A moved/duplicated caption elsewhere cannot satisfy the adjacent
        # check or hide behind one correct copy next to its intended image.
        blank = sha256(b"").hexdigest()
        wanted_captions = Counter(item["caption_sha256"] for item in expected_pages if item["caption_sha256"] != blank)
        paragraph_captions = Counter(sha256(text(p).encode()).hexdigest() for p in body.findall(".//w:p", ns))
        assert all(paragraph_captions[digest] == count for digest, count in wanted_captions.items()), "DOCX Water caption occurrence count differs from the working report"
        return [{key: value for key, value in item.items() if key != "paragraph"} for item in occurrences]


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


def wait_pages(page, order, *, pending=None, reviewed=None):
    page.wait_for_function("""wanted => {
      const nodes=document.querySelectorAll('[data-enfra-water-receipt]');
      if(!nodes.length)return false;
      const s=JSON.parse(nodes[nodes.length-1].dataset.enfraWaterReceipt);
      const numbers=part=>part.pages.map(p=>p.source_pages.length===1?p.source_pages[0][1]:null);
      return JSON.stringify(numbers(s.working))===JSON.stringify(wanted.order) &&
        JSON.stringify(s.working)===JSON.stringify(s.durable) &&
        s.working_fingerprint===s.durable_fingerprint &&
        (!wanted.check_pending||JSON.stringify(s.working.pending)===JSON.stringify(wanted.pending)) &&
        (!wanted.check_reviewed||(s.working.sources.length===1 &&
          JSON.stringify(s.working.sources[0].reviewed)===JSON.stringify(wanted.reviewed))) &&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={"order": order, "check_pending": pending is not None,
            "pending": pending if pending is not None else [],
            "check_reviewed": reviewed is not None,
            "reviewed": reviewed if reviewed is not None else []}, timeout=45000)
    return receipt(page)


def current_water_preview(page, qa, *, inset=130):
    # Completing review collapses the source editor, which can move the viewport
    # into the next section. On compact screens View preview opens a surface
    # BELOW the editor. Scroll that actual open surface, not the section header;
    # preserve the production viewer's visibility-driven work boundary.
    qa.scroll_pair(page, WATER, inset=inset, preview=True)
    qa.current_image(page, WATER)


def open_water_with_cold_tables(page, qa, observations):
    """Exercise the recorded late-table shift without waiting it away.

    Open the already-saved draft in a fresh browser context and hold only its
    real local DataFrame module on the first navigation,
    measure the loading page, then release its unchanged response. The button
    and scroll position must stay put as the three preceding editors mount.
    No report state, input, geometry or control event is injected.
    """
    assert page.url == "about:blank", "Cold table coverage requires an unused browser page."
    pattern = re.compile(re.escape(qa.URL) + r"/static/js/DataFrame\.[^/?]+\.js$")
    held = []

    def hold(route):
        held.append(route)

    sample = """wanted => {
      const pair=document.querySelector(wanted.water),root=pair.closest('.epc-workspace');
      const button=pair.querySelector('.epc-compact-open');
      const boxes=wanted.keys? wanted.keys.map(key=>root.querySelector('.'+CSS.escape(key))) :
        [...root.querySelectorAll('[data-testid="stElementContainer"]')].filter(node=>
          [...node.classList].some(key=>/^st-key-report_guided_.+_edit_(work_orders|thermal_capacity|service_calls)_imported_0_/.test(key)) &&
          node.querySelector(':scope > [data-testid="stSkeleton"]') &&
          (node.compareDocumentPosition(pair)&Node.DOCUMENT_POSITION_FOLLOWING) &&
          node.getBoundingClientRect().height>0);
      const b=button.getBoundingClientRect();
      // Passive first-failure context for late content above the three grids.
      // Keep the original scroll/button assertions; never restore their values.
      const preceding=[...root.querySelectorAll('[data-testid="stElementContainer"]')]
        .filter(node=>(node.compareDocumentPosition(pair)&Node.DOCUMENT_POSITION_FOLLOWING)
          && node.getBoundingClientRect().height>0).slice(0,200)
        .map((node,index)=>{const r=node.getBoundingClientRect();return {
          key:[...node.classList].find(key=>key.startsWith('st-key-'))||'element-'+index,
          type:node.firstElementChild?.getAttribute('data-testid')||node.firstElementChild?.tagName,
          top:r.top,left:r.left,width:r.width,height:r.height,
          images:[...node.querySelectorAll('img')].slice(0,4).map(image=>({
            complete:image.complete,width:image.naturalWidth,height:image.naturalHeight}))};});
      return {button:{x:b.x,y:b.y,width:b.width,height:b.height},
        viewport:{width:document.documentElement.clientWidth,height:window.innerHeight},
        scrollTop:document.querySelector('[data-testid="stMain"]').scrollTop,
        fullRender:root.dataset.epcFullRender,preceding,fontStatus:document.fonts.status,
        grids:boxes.map(node=>({key:[...node.classList].find(k=>k.startsWith('st-key-')),
          height:node.getBoundingClientRect().height,
          loading:!!node.querySelector(':scope > [data-testid="stSkeleton"]'),
          mounted:!!node.querySelector('[data-testid="stDataFrameResizable"]')}))};
    }"""
    result = observations["cold_table_layout"] = {}
    page.route(pattern, hold)
    try:
        with page.expect_request(pattern, timeout=20000):
            page.goto(qa.URL, wait_until="domcontentloaded")
            state = wait_pages(page, [2, 1], pending=[])
        qa.scroll_pair(page, WATER, inset=90)
        before = result["before"] = page.evaluate(sample, {"water": WATER, "keys": None})
        result["held_module_requests"] = len(held)
        button, viewport = before["button"], before["viewport"]
        assert (button["width"] > 0 and button["height"] > 0 and button["x"] >= 0 and button["y"] >= 0
                and button["x"] + button["width"] <= viewport["width"]
                and button["y"] + button["height"] <= viewport["height"]), (
                    "Water's actual preview action must be in view before releasing the held module.", before)
        assert len(held) == 1, "Expected one held DataFrame module request: " + str(len(held))
        assert len(before["grids"]) == 3, "Observe all three imported editors preceding Water."
        keys = [item["key"] for item in before["grids"]]
        assert all(keys) and all(item["loading"] for item in before["grids"])
        result["module"] = held[0].request.url.rsplit("/", 1)[-1]
        held.pop().continue_()
        page.wait_for_function("""keys => keys.every(key=>{
          const node=document.querySelector('.'+CSS.escape(key));
          return node && !node.querySelector(':scope > [data-testid="stSkeleton"]') &&
            node.querySelector('[data-testid="stDataFrameResizable"]')?.getBoundingClientRect().height>0;
        })""", arg=keys, timeout=20000)
        qa.frames(page)
        after = result["after"] = page.evaluate(sample, {"water": WATER, "keys": keys})
        assert after["fullRender"] == before["fullRender"]
        assert after["scrollTop"] == before["scrollTop"], "Do not hide a shift by restoring scroll."
        assert all(item["mounted"] for item in after["grids"])
        for old, current in zip(before["grids"], after["grids"]):
            assert abs(current["height"] - old["height"]) <= 2, (old, current)
        for axis in ("x", "y", "width", "height"):
            assert abs(after["button"][axis] - before["button"][axis]) <= 2, result
        return state
    finally:
        # A failing assertion still releases the original request and handler.
        for route in held:
            route.continue_()
        page.unroute(pattern, hold)


def open_water_preview(page, water, qa, observations):
    """Observe the one compact action without repairing it or changing its wait."""
    control = water.get_by_role("button", name="View preview", exact=True)
    probe = observations["compact_preview_activation"] = {}
    try:
        probe["before"] = control.evaluate("""(node, selector) => {
            window.__enfraWaterPreviewActivation?.finish();
            const pair=node.closest(selector), root=pair?.closest('.epc-workspace');
            const reference=pair?.querySelector('.st-key-epc_reference_monthly_water');
            const events=[],mutations=[];let droppedEvents=0,droppedMutations=0;
            const brief=()=>{const currentPair=document.querySelector(selector);
                const currentButton=currentPair?.querySelector('.epc-compact-open');
                const currentReference=currentPair?.querySelector('.st-key-epc_reference_monthly_water');
                const currentRoot=currentPair?.closest('.epc-workspace');
                return {buttonConnected:node.isConnected,pairConnected:pair?.isConnected??false,
                    referenceConnected:reference?.isConnected??false,
                    currentPairIsOriginal:currentPair===pair,currentButtonIsOriginal:currentButton===node,
                    currentReferenceIsOriginal:currentReference===reference,currentRootIsOriginal:currentRoot===root,
                    onclickType:typeof node.onclick,
                    expanded:node.getAttribute('aria-expanded'),pairOpen:pair?.getAttribute('data-epc-preview-open')??null,
                    currentExpanded:currentButton?.getAttribute('aria-expanded')??null,
                    currentPairOpen:currentPair?.getAttribute('data-epc-preview-open')??null,
                    fullRender:root?.dataset.epcFullRender??null,mode:root?.dataset.epcMode??null,
                    currentFullRender:currentRoot?.dataset.epcFullRender??null,currentMode:currentRoot?.dataset.epcMode??null,
                    focused:document.activeElement===node,
                    scriptState:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')??null};};
            const snapshot=()=>{const r=node.getBoundingClientRect();return {...brief(),
                rect:{x:r.x,y:r.y,width:r.width,height:r.height},
                events:events.slice(),mutations:mutations.slice(),droppedEvents,droppedMutations};};
            const observe=event=>{if(!event.isTrusted)return;
                if(events.length<24)events.push({type:event.type,at:performance.now(),trusted:true,
                    phase:event.eventPhase,x:Number.isFinite(event.clientX)?event.clientX:null,
                    y:Number.isFinite(event.clientY)?event.clientY:null,targetIsOriginal:event.target===node,
                    targetInOriginal:node.contains(event.target),targetTag:event.target?.tagName??null,...brief()});
                else droppedEvents++;};
            const collect=records=>{const changes=records.filter(r=>
                r.target===node&&r.attributeName==='aria-expanded'||
                r.target===pair&&r.attributeName==='data-epc-preview-open');
                for(let i=0;i<changes.length;i++){const change=changes[i];
                    const next=changes.slice(i+1).find(r=>r.target===change.target&&r.attributeName===change.attributeName);
                    const after=next?next.oldValue:change.target.getAttribute(change.attributeName);
                    if(mutations.length<24)mutations.push({at:performance.now(),
                        target:change.target===node?'original-button':'original-pair',
                        attribute:change.attributeName,before:change.oldValue,after,...brief()});
                    else droppedMutations++;}};
            const observer=new MutationObserver(collect);
            observer.observe(pair,{attributes:true,subtree:true,
                attributeFilter:['aria-expanded','data-epc-preview-open'],attributeOldValue:true});
            const kinds=['pointerdown','pointerup','mousedown','mouseup','click','focusin','focusout'];
            for(const kind of kinds){document.addEventListener(kind,observe,{capture:true,passive:true});
                document.addEventListener(kind,observe,{capture:false,passive:true});}
            window.__enfraWaterPreviewActivation={snapshot,finish:()=>{
                try{collect(observer.takeRecords());return snapshot();}
                finally{observer.disconnect();
                    for(const kind of kinds){document.removeEventListener(kind,observe,true);
                        document.removeEventListener(kind,observe,false);}
                    delete window.__enfraWaterPreviewActivation;}}};
            return snapshot();
        }""", WATER)
    except Exception as exc:
        probe["setup_error"] = str(exc)[:500]
    try:
        control.click()
        if "before" in probe:
            try:
                probe["after_click"] = page.evaluate("window.__enfraWaterPreviewActivation.snapshot()")
            except Exception as exc:
                probe["after_click_error"] = str(exc)[:500]
        current_water_preview(page, qa, inset=90)
    finally:
        try:
            probe["final"] = page.evaluate("window.__enfraWaterPreviewActivation?.finish()??null")
        except Exception as exc:
            probe["cleanup_error"] = str(exc)[:500]


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
    expect(page.locator(WATER).get_by_text(NAME, exact=True)).to_be_visible(timeout=45000)
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
        state = wait_pages(page, [], reviewed=[1])
        unchanged(state)
        record("desktop-first-page-reviewed", state)
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        state = wait_pages(page, [1, 2], pending=[])
        unchanged(state)
        assert len(state["working"]["sources"]) == 1
        expect(water.get_by_role("button", name="Add reviewed pages", exact=True)).to_have_count(0)
        expect(water.get_by_role("button", name="View or change pictures", exact=True)).to_have_count(0)
        current_water_preview(page, qa)
        record("desktop-included", state)

        water.get_by_role("button", name="Edit pages", exact=True).click()
        choose_page(page, 1)
        caption = water.get_by_role("textbox", name="Page caption", exact=True)
        assert caption.input_value(), "The Done regression must clear an actual caption."
        caption.fill("")
        water.get_by_role("button", name="Done reviewing pages", exact=True).click()
        state = wait_pages(page, [1, 2], pending=[0])
        assert state["working"]["pages"][0]["caption_sha256"] == sha256(b"").hexdigest()
        expect(caption).to_have_value("")
        unchanged(state)
        record("desktop-clear-caption-with-done", state)
        # Closing does not approve changed wording. Use the normal page review
        # before continuing the existing caption/Tab, ordering and omission task.
        water.get_by_role("button", name="Include page and continue", exact=True).click()
        wait_pages(page, [1, 2], pending=[])
        # Done closed editing; completing the outstanding review now returns
        # to the normal summary. Open the real editor for the next edit.
        expect(water.get_by_role("combobox", name="Page to review", exact=True)).to_have_count(0)
        water.get_by_role("button", name="Edit pages", exact=True).click()
        choose_page(page, 1)
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
        upload(page, raw)  # Same bytes after an ordinary reload of this browser page.
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
        open_water_preview(page, water, qa, observations)
        record("narrow-current-preview", state)
        water.get_by_role("button", name="Back to editing", exact=True).click()

        from scripts import qa_monthly_live as live
        live.ROOT = out
        live.EVIDENCE = {"checks": {}, "events": [], "artifacts": {}, "synthetic_only": True}
        live.request_qa_generation(page, "water-page-journey")
        word = live.download(page, "Download isolated QA DOCX", "water-pages.docx")
        pdf = live.download(page, "Download isolated QA PDF", "water-pages.pdf")
        observations["output_docx_water_pages"] = assert_docx_water_pages(word, state["working"]["pages"])
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
        return state
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
    device_cookie = {"name": "epc_device_id", "value": secrets.token_hex(16), "url": qa.URL}
    context.add_cookies([device_cookie])
    attempts, errors = [], []
    def route(request):
        address = urlparse(request.request.url)
        if address.scheme in {"data", "blob"} or (address.hostname == "127.0.0.1" and address.port == 8520):
            request.continue_()
        else:
            attempts.append(address.hostname)
            request.abort()
    share_guard = """window.__waterShareAttempts=[];
      Object.defineProperty(navigator,'share',{configurable:true,value:()=>{
        window.__waterShareAttempts.push('share');
        return Promise.reject(new Error('Sharing is forbidden in synthetic QA'));
      }});"""
    context.route("**/*", route)
    context.add_init_script(share_guard)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    from scripts.qa_water_widget_delivery import WaterWidgetDelivery
    delivery = []
    WaterWidgetDelivery(lambda row: delivery.append({"at": time.monotonic(), **row})).attach(page)
    out = qa.OUT / (name + "-water")
    out.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(qa.URL, wait_until="domcontentloaded")
        page.get_by_role("button", name="Load known-value report", exact=True).click()
        expect(page.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=90000)
        expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_be_visible(timeout=45000)
        expected = exercise(page, name, qa)
        qa.check(name, "Water task has no external request, browser error or sharing",
                 not attempts and not errors and not page.evaluate("window.__waterShareAttempts.length"),
                 {"external": attempts, "errors": errors})
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()

        # Both retained WebKit traces reuse the original module response across
        # reload, including the attempt with no-store. Preserve ordinary reload
        # above and test a cold mount separately. Only the same synthetic device
        # cookie crosses contexts: the app must read the real durable draft.
        context.close()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_cookies([device_cookie])
        context.route("**/*", route)
        context.add_init_script(share_guard)
        page = context.new_page()
        page.set_default_timeout(20000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        WaterWidgetDelivery(lambda row: delivery.append({"at": time.monotonic(), **row})).attach(page)
        cold = {"entry": "fresh browser context; same synthetic device cookie; saved draft",
                "expected_fingerprint": expected["durable_fingerprint"]}
        try:
            state = open_water_with_cold_tables(page, qa, cold)
            assert state == expected, "Fresh session must restore the exact UI-saved report and originals."
            cold["receipt"] = state
            open_water_preview(page, page.locator(WATER), qa, cold)
            qa.capture(page, name, "water-cold-session-current-preview")
            assert not attempts and not errors and not page.evaluate("window.__waterShareAttempts.length")
            expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
            cold["result"] = "passed"
            qa.check(name, "Cold saved Water session keeps all three table heights and one preview click", True)
        except Exception as exc:
            cold["result"] = "failed"
            cold["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
            try:
                qa.capture(page, name, "water-cold-session-first-failure")
            except Exception as capture_error:
                cold["capture_failure"] = str(capture_error)[:500]
            raise
        finally:
            (out / "cold-session.json").write_text(json.dumps(cold, indent=2))
    finally:
        (out / "widget-delivery.json").write_text(json.dumps(delivery, indent=2))
        (out / "browser.json").write_text(json.dumps({"external": attempts, "errors": errors}, indent=2))
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
    # The same observer used by the existing Monthly tasks records optional
    # tracing failures without masking the actual Water journey result.
    from playwright.sync_api import Browser, BrowserContext
    from scripts.qa_browser_diagnostics import observe
    with observe(qa.OUT / "diagnostics", Browser, BrowserContext):
        qa.main()


if __name__ == "__main__":
    # Direct script invocation also needs the repository on sys.path.
    main()
