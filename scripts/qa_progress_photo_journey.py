"""One native Progress photos task per engine in the existing isolated fixture.

Real uploader, production guided editor, browser journal and first-attempt QA
generation. No hidden report injection, client material, business sends or retry.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import posixpath
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote, urlparse
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 8530
URL = f"http://127.0.0.1:{PORT}"
OUT = ROOT / "test-artifacts" / "progress-photo-journey"
PAIR = ".st-key-epc_pair_monthly_activity"
CAPTIONS = ("Synthetic strainer inspection before adjustment.",
            "Synthetic valve inspection; follow-up pending.")
MOVED = "Synthetic strainer caption retained through both moves."
ADDED = "Synthetic strainer caption delivered with Add."
THIRD = "Synthetic pump caption delivered with Remove."
ACTIVITY = "Synthetic current-month photo review; pump follow-up remains pending."


def invented_photo(number):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (420, 250), ("#e8edf4", "#dbe9df", "#f0dfc4")[number - 1])
    ImageDraw.Draw(image).text((25, 105), f"SYNTHETIC PROGRESS PHOTO {number}", fill="black")
    stream = BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def expected_assets():
    from app.monthly_report_docx import normalize_report_image
    from app.monthly_report_library import asset_reference
    assets = {}
    for number in (1, 2, 3):
        normalized = normalize_report_image(invented_photo(number), ".png")
        assets[asset_reference(normalized.data, normalized.extension)] = normalized.data
    assert len(assets) == 3, "The invented photos must be distinct."
    return assets


def native_error_init():
    source = (ROOT / "scripts/qa_fresh_native_errors.js").read_text()
    assert source.count("http://127.0.0.1:8529") == 1, "The known passive collector origin changed."
    return source.replace("http://127.0.0.1:8529", URL)


def _photo_pixels(actual, expected):
    """Allow native PDF JPEG noise, retaining photo identity and caption glyphs.

    The converter demonstrably changes pixel bytes. This is a bounded fixture
    comparison: exact aspect, small overall error and center photo color, plus
    bidirectional one-pixel caption-ink containment and close ink count. It is
    neither OCR nor manual readable-scale/all-page acceptance.
    """
    from PIL import Image, ImageChops, ImageFilter, ImageStat
    if not (700 <= actual.width <= 2800 and 770 <= actual.height <= 3080
            and abs(actual.width / actual.height - expected.width / expected.height) < .001):
        return {"matches": False, "geometry": False}
    expected = expected.resize(actual.size, Image.Resampling.LANCZOS)
    means = ImageStat.Stat(ImageChops.difference(actual, expected)).mean
    points = [(int(actual.width * x), int(actual.height * y))
              for x in (.47, .5, .53) for y in (.48, .5, .52)]
    center = max(abs(a - b) for point in points for a, b in zip(actual.getpixel(point), expected.getpixel(point)))
    top = int(actual.height * (1340 / 1540))
    crop = (0, top, actual.width, actual.height)
    ink = lambda image: image.crop(crop).convert("L").point(lambda value: 255 if value < 130 else 0)
    wanted, seen = ink(expected), ink(actual)
    count = lambda image: sum(image.histogram()[1:])
    wanted_count, seen_count = count(wanted), count(seen)
    lost = count(ImageChops.subtract(wanted, seen.filter(ImageFilter.MaxFilter(3))))
    extra = count(ImageChops.subtract(seen, wanted.filter(ImageFilter.MaxFilter(3))))
    return {"matches": max(means) <= .5 and center <= 4 and wanted_count > 0
            and abs(seen_count - wanted_count) <= wanted_count * .02 and not lost and not extra,
            "mae_rgb": means, "center_max_difference": center,
            "caption_expected_ink": wanted_count, "caption_actual_ink": seen_count,
            "caption_lost_outside_one_pixel": lost, "caption_extra_outside_one_pixel": extra}


def assert_outputs(word, pdf, references, captions, assets):
    """Exact synthetic photo-page raster/caption/order proof, not visual approval."""
    from lxml import etree
    from PIL import Image
    import pymupdf
    from app.monthly_report_model import ResolvedBlock, profile_sections
    from app.monthly_report_visuals import photo_page
    from app.monthly_report_qa_fixture import profile
    block = ResolvedBlock("improvements", "This month", asset_hashes=tuple(references),
                          asset_captions=tuple(captions), photos_per_page=1)
    pages = [photo_page(block, assets.__getitem__, index) for index in range(len(references))]
    blank = replace(block, asset_captions=tuple("" for _ in captions))
    assert all(raw != photo_page(blank, assets.__getitem__, index) for index, raw in enumerate(pages)), "Caption pixels must affect each expected photo page."
    digests = [sha256(raw).hexdigest() for raw in pages]
    assert len(set(digests)) == len(digests)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    sections = profile_sections(profile())
    activity = next(section for section in sections if section.key == "activity")
    heading = f"{activity.number}. {activity.title}"
    next_section = sections[sections.index(activity) + 1]
    next_heading = f"{next_section.number}. {next_section.title}"
    with ZipFile(BytesIO(word)) as package:
        body = etree.fromstring(package.read("word/document.xml")).find("w:body", ns)
        assert body is not None
        rels = {item.get("Id"): item for item in etree.fromstring(package.read("word/_rels/document.xml.rels"))}
        actual, active, matched = [], False, 0
        pictures = []
        for child in body:
            style = child.find("w:pPr/w:pStyle", ns)
            if style is not None and style.get("{" + ns["w"] + "}val") == "Heading1":
                active = "".join(node.text or "" for node in child.findall(".//w:t", ns)) == heading
                matched += int(active)
            if active:
                pictures.extend(child.findall(".//a:blip", ns))
        assert matched == 1, "The fixture Activity heading must occur once."
        for blip in pictures:
            link = rels[blip.get("{" + ns["r"] + "}embed")]
            if not link.get("Type", "").endswith("/image"):
                continue
            assert link.get("TargetMode") != "External"
            target = urlparse(link.get("Target", ""))
            assert not target.scheme and not target.netloc
            path = posixpath.normpath(posixpath.join("word", unquote(target.path)))
            assert not path.startswith("../") and path in package.namelist()
            digest = sha256(package.read(path)).hexdigest()
            actual.append(digest)
        assert actual == digests, "Actual DOCX photo-page media/order/captions differ from the expected edited report."
    expected_images = []
    for raw in pages:
        with Image.open(BytesIO(raw)) as image:
            expected_images.append(image.convert("RGB"))
    actual, comparisons, active, found = [], [], False, False
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        for page in document:
            words = " ".join(page.get_text().split())
            if next_heading in words or "Section " + str(next_section.number) in words:
                active = False
            elif heading in words:
                active = found = True
            if not active:
                continue
            for info in page.get_image_info(xrefs=True):
                if not (info["xref"] and 700 <= info["width"] <= 2800 and 770 <= info["height"] <= 3080
                        and abs(info["width"] / info["height"] - 1400 / 1540) < .001):
                    continue
                pixmap = pymupdf.Pixmap(document, info["xref"])
                assert pixmap.n == 3, "An actual PDF Activity photo page has an unexpected color model."
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                matches = [_photo_pixels(image, expected) for expected in expected_images]
                indexes = [index for index, item in enumerate(matches) if item["matches"]]
                assert len(indexes) == 1, "An actual PDF Activity photo page is unexpected, changed or ambiguous."
                actual.append(indexes[0])
                comparisons.append(matches[indexes[0]])
        assert found, "The PDF fixture Activity content heading is missing."
        assert actual == list(range(len(pages))), "Actual PDF displayed photo-page pixel order/captions differ from the expected edited report."
        count = len(document)
    return {"photo_page_sha256": digests, "pdf_pages": count, "pdf_photo_comparisons": comparisons,
        "scope": "Exact DOCX photo-page rasters; bounded native-PDF photo/caption-pixel/order comparison. No manual all-page, native Word or authentic-master approval."}


def receipt(page):
    return json.loads(page.locator("[data-enfra-progress-receipt]").last.get_attribute("data-enfra-progress-receipt"))


def action_delivery(rows, start, label, text=None):
    """Require one real full-editor action and report its native text batching.

    Normal blur can commit the text before the click packet. That is recorded
    separately and never mislabelled as browser proof of a same-packet path.
    """
    labels = {row["id_hash"]: row["label"] for row in rows if row.get("direction") == "received"
              and "id_hash" in row and "label" in row}
    packets = [row for row in rows[start:] if row.get("direction") == "sent" and row.get("kind") == "rerun_script"]
    pressed = [index for index, row in enumerate(packets) if any(item.get("pressed")
        and labels.get(item["id_hash"]) == label for item in row["widgets"])]
    assert len(pressed) == 1, "The native photo action must be delivered exactly once: " + label
    action = pressed[0]
    assert packets[action]["fragment"] == "", "A photo action must reach the full editor."
    result = {"label": label, "action_packets": 1, "full_editor": True}
    if text is not None:
        digest = sha256(text.encode()).hexdigest()
        delivered = [index for index, row in enumerate(packets) if any(item.get("sha256") == digest
            and labels.get(item["id_hash"]) in {"Caption", "Activity summary"} for item in row["widgets"])]
        assert any(index <= action for index in delivered), "The intended native text never reached the server before/with the photo action."
        result.update(text_sha256=digest, text_in_action_packet=action in delivered,
                      text_in_prior_packet=any(index < action for index in delivered))
    return result


def await_state(page, expected, *, after=0):
    page.wait_for_function("""wanted => {
        const nodes=document.querySelectorAll('[data-enfra-progress-receipt]');
        if(!nodes.length)return false;
        const s=JSON.parse(nodes[nodes.length-1].dataset.enfraProgressReceipt);
        return s.sequence>wanted.after && JSON.stringify(s.working)===JSON.stringify(s.durable) &&
          Object.entries(wanted.state).every(([key,value])=>JSON.stringify(s.working[key])===JSON.stringify(value)) &&
          document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={"state": expected, "after": after}, timeout=30000)
    return receipt(page)


def close_session(context, browser):
    errors = []
    for label, surface in (("context", context), ("browser", browser)):
        try:
            surface.close()
        except Exception as exc:
            errors.append({"surface": label, "type": type(exc).__name__, "message": str(exc)[:500]})
    return errors


def stop_server(process):
    """Bound cleanup independently so it cannot replace the primary failure."""
    errors = []
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        errors.append("Synthetic Progress server did not stop within20 seconds")
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:500])
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc)[:500])
    return errors


def browser_task(engine, name, base):
    from playwright.sync_api import expect
    from scripts import qa_monthly_live as live
    from scripts.qa_fresh_native_error_checks import capture_native_window_errors, require_no_native_window_errors
    from scripts.workspace_history_observations import storage_state, photograph_storage_paths
    from app.monthly_report_model import ResolvedBlock
    from app.monthly_report_asset_review import preserve_asset_reviews
    from scripts.qa_water_fresh_page_journey import observe_frontend_delivery, require_frontend_delivery
    from scripts.qa_water_widget_delivery import WaterWidgetDelivery

    output = OUT / name
    output.mkdir(parents=True, exist_ok=True)
    live.ROOT = output
    live.EVIDENCE = {"synthetic_only": True, "checks": {}, "events": [], "artifacts": {}}
    record = {"engine": name, "result": "failed", "steps": [], "browser_errors": [], "external_requests": [],
        "tested_checkout": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "fixture": "known-value prefill then native browser uploader; no injected photo draft",
        "review_scope": "Native uploaded photos with empty provenance; source-linked page review is a separate journey.",
        "physical_device": False}
    token = secrets.token_hex(16)
    browser = engine.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": token, "url": URL}])
    context.add_init_script(native_error_init())
    context.add_init_script((ROOT / "scripts/qa_photo_action_observations.js").read_text())
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: record["browser_errors"].append(str(error)))
    delivery = []
    WaterWidgetDelivery(delivery.append, ports=(PORT,),
        labels={"Caption", "Activity summary", "Add these photos", "Move earlier", "Move later", "Remove photo", "Done editing photos"},
        widget_types={"button", "text_area"}).attach(page)
    record["action_delivery"] = []

    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"blob", "data"} or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            record["external_requests"].append({"host": parsed.hostname, "type": request.request.resource_type})
            request.abort()
    context.route("**/*", route)
    native_documents = []
    assets = expected_assets()
    refs = tuple(assets)
    block = ResolvedBlock("improvements", "This month", asset_hashes=refs[:2], asset_captions=("", ""))
    baseline = None
    retained_files = {}

    def expected(current):
        # Same production data schema, but expected content comes from the
        # task's explicit source/order/caption decisions, never the UI receipt.
        from app.monthly_report_asset_review import asset_context, asset_fingerprint, asset_reviewed
        return {"source": current.source, "photos_per_page": current.photos_per_page,
            "photo_context": sha256(repr((current.text, current.rows, current.extra_tables, current.references)).encode()).hexdigest(),
            "images": [{"asset": reference,
                "caption": sha256((current.asset_captions[index] if index < len(current.asset_captions) else "").encode()).hexdigest(),
                "provenance": list(asset_context(current, index)), "review": asset_fingerprint(current, index),
                "reviewed": asset_reviewed(current, index)} for index, reference in enumerate(current.asset_hashes)]}

    def capture(stage, current=None, *, after=0, activity=None):
        nonlocal baseline
        record["phase"] = stage
        wanted = expected(current) if current is not None else {"images": []}
        if activity is not None:
            wanted["activity"] = sha256(activity.encode()).hexdigest()
        state = await_state(page, wanted, after=after)
        state["storage"] = storage_state(base, token)
        record["steps"].append({"stage": stage, **state})
        (output / "task.json").write_text(json.dumps(record, indent=2))
        assert state["storage"]["live_library_absent"]
        if baseline is None:
            baseline = state
            assert state["saved_revision"] == 1
        else:
            assert (state["scope"], state["generation"], state["saved_revision"]) == (baseline["scope"], baseline["generation"], 1)
            for field in ("unrelated", "sources", "omitted"):
                assert state["working"][field] == baseline["working"][field], "Photo action changed unrelated report " + field
            for group in ("standing", "history"):
                assert state["storage"]["groups"][group] == baseline["storage"]["groups"][group], "Photo action wrote shared " + group
        for asset in state["assets"]:
            assert assets[asset["asset"]] and asset["sha256"] == sha256(assets[asset["asset"]]).hexdigest()
            assert asset["bytes"] == len(assets[asset["asset"]])
        entries = state["storage"]["entries"]
        for path, previous in retained_files.items():
            assert entries.get(path) == previous, "A photo action removed, changed or rewrote an already retained normalized photo."
        for asset in state["assets"]:
            paths = photograph_storage_paths(base, token, asset["asset"])
            for role in ("photo", "object", "object_lock"):
                item = entries[paths[role]]
                assert item["bytes"] == (0 if role == "object_lock" else asset["bytes"])
                assert item["sha256"] == (sha256(b"").hexdigest() if role == "object_lock" else asset["sha256"])
                retained_files.setdefault(paths[role], item)
        return state

    def native_geometry(stage):
        native_actions = page.evaluate("window.__enfraPhotoActionObservations()")
        record["photo_native_actions"] = native_actions
        last_down = max(index for index, event in enumerate(native_actions) if event["type"] == "pointerdown")
        gesture = native_actions[last_down:]
        assert [event["type"] for event in gesture] == ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]
        first = gesture[0]
        assert all(event["trusted"] and event["connected"] and event["target"] == first["action"] for event in gesture)
        assert all(abs(event["button"]["y"]-first["button"]["y"]) <= 1 for event in gesture), gesture
        status = page.locator('.enfra-browser-save-status').bounding_box()
        assert status and all(event["status"] and abs(event["status"]["height"]-status["height"]) <= 1 for event in gesture), gesture
        record.setdefault("save_status_geometry", []).append({"stage":stage,"viewport":page.viewport_size,
            "acknowledged_status":status,"native_gesture":gesture})

    def panel(number):
        item = page.locator(PAIR).get_by_test_id("stExpander").filter(has=page.locator("summary").get_by_text("Photo " + str(number), exact=True))
        expect(item).to_have_count(1)
        if not item.evaluate("node => node.matches('details') ? node.open : node.querySelector('details').open"):
            item.locator("summary").first.click()
        return item

    def upload(numbers):
        pair = page.locator(PAIR)
        intake = pair.get_by_test_id("stExpander").filter(has=page.locator("summary").get_by_text("Add photos", exact=True))
        if not intake.evaluate("node => node.matches('details') ? node.open : node.querySelector('details').open"):
            intake.locator("summary").first.click()
        intake.locator('input[type="file"]').set_input_files([
            {"name": f"synthetic-progress-photo-{number}.png", "mimeType": "image/png", "buffer": invented_photo(number)} for number in numbers])

    def review(current):
        from app.monthly_report_asset_review import pending_asset_indexes, approve_asset
        # Exactly one decision for each explicitly expected pending picture;
        # a failed acknowledgment stops before any next business action.
        for index in pending_asset_indexes(current):
            before = receipt(page)["sequence"]
            page.get_by_role("button", name="This page is ready to include", exact=True).click()
            current = approve_asset(current, index)
            capture("review-photo-" + str(index + 1), current, after=before)
        return current

    try:
        observe_frontend_delivery(page, record)
        page.goto(URL, wait_until="domcontentloaded")
        live.load_fixture(page, "prefill")
        initial = capture("empty-progress-before-native-upload")
        assert initial["working"]["source"] == "This month"
        assert not initial["working"]["sources"]
        require_frontend_delivery(record)
        upload((1, 2))
        page.locator(PAIR).get_by_role("button", name="Add these photos", exact=True).click()
        capture("two-native-photos-added", block)
        for index, caption in enumerate(CAPTIONS):
            control = panel(index + 1).get_by_role("textbox", name="Caption", exact=True)
            control.fill(caption)
            control.press("Tab")
            block = preserve_asset_reviews(block, replace(block, asset_captions=tuple(CAPTIONS[n] if n <= index else "" for n in range(2))))
            capture("caption-" + str(index + 1), block)
        block = review(block)
        page.locator(PAIR).get_by_role("button", name="Edit photos or captions", exact=True).click()
        expect(panel(1).get_by_role("button", name="Move earlier", exact=True)).to_be_disabled()
        expect(panel(2).get_by_role("button", name="Move later", exact=True)).to_be_disabled()
        control = panel(1).get_by_role("textbox", name="Caption", exact=True)
        control.fill(MOVED)
        control.press("Tab")
        block = preserve_asset_reviews(block, replace(block, asset_captions=(MOVED, CAPTIONS[1])))
        capture("ordinary-caption-blur", block)
        panel(1).get_by_role("button", name="Move later", exact=True).click()
        block = preserve_asset_reviews(block, replace(block, asset_hashes=(refs[1], refs[0]), asset_captions=(CAPTIONS[1], MOVED)))
        capture("desktop-move-later", block)
        panel(2).get_by_role("button", name="Move earlier", exact=True).click()
        block = preserve_asset_reviews(block, replace(block, asset_hashes=refs[:2], asset_captions=(MOVED, CAPTIONS[1])))
        capture("desktop-reverse-earlier", block)
        # Streamlit 1.61.1 labels both the scalar thumb and its group. The
        # native thumb's aria-labelledby joins those two labels, so its name
        # is "Photos per page Photos per page" in the retained first failure.
        # Locate the user's labelled group and its one native slider instead
        # of treating a failed exact-name match as missing density state.
        density = page.locator(PAIR).get_by_role("group", name="Photos per page", exact=True)
        expect(density).to_have_count(1)
        density.scroll_into_view_if_needed()
        expect(density).to_be_in_viewport()
        slider = density.get_by_role("slider")
        expect(slider).to_have_count(1)
        expect(slider).to_be_enabled()
        record["density_accessibility"] = {
            "before_keyboard": density.aria_snapshot(),
            "labelledby": slider.get_attribute("aria-labelledby"),
            "value_text": slider.get_attribute("aria-valuetext"),
        }
        slider.press("End")
        block = replace(block, photos_per_page=6)
        capture("desktop-density-six", block)
        slider.press("Home")
        block = replace(block, photos_per_page=1)
        capture("desktop-density-one", block)
        for value in range(2, 7):
            slider.press("ArrowRight")
            block = replace(block, photos_per_page=value)
            capture("desktop-density-keyboard-" + str(value), block)
            expect(slider).to_have_attribute("aria-valuetext", str(value))
        slider.press("Home")
        block = replace(block, photos_per_page=1)
        capture("desktop-density-return-one", block)
        block = review(block)
        upload((3,))
        start = len(delivery)
        panel(1).get_by_role("textbox", name="Caption", exact=True).fill(ADDED)
        page.locator(PAIR).get_by_role("button", name="Add these photos", exact=True).click()
        block = preserve_asset_reviews(block, replace(block, asset_hashes=refs, asset_captions=(ADDED, CAPTIONS[1], "")))
        capture("caption-delivered-with-add-old-reviews-retained", block)
        native_geometry("caption-with-add")
        record["action_delivery"].append(action_delivery(delivery, start, "Add these photos", ADDED))
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='compact'")
        panel(2)  # Establish the one normal action before editing another caption.
        start = len(delivery)
        panel(3).get_by_role("textbox", name="Caption", exact=True).fill(THIRD)
        panel(2).get_by_role("button", name="Remove photo", exact=True).click()
        block = preserve_asset_reviews(block, replace(block, asset_hashes=(refs[0], refs[2]), asset_captions=(ADDED, THIRD)))
        capture("narrow-later-caption-delivered-with-remove", block)
        native_geometry("390-caption-with-remove")
        record["action_delivery"].append(action_delivery(delivery, start, "Remove photo", THIRD))
        start = len(delivery)
        page.get_by_role("textbox", name="Activity summary", exact=True).fill(ACTIVITY)
        page.locator(PAIR).get_by_role("button", name="Done editing photos", exact=True).click()
        capture("narrow-activity-delivered-with-done", block, activity=ACTIVITY)
        native_geometry("390-activity-with-done")
        record["action_delivery"].append(action_delivery(delivery, start, "Done editing photos", ACTIVITY))
        expect(page.locator(PAIR).get_by_role("button", name="Move earlier", exact=True)).to_have_count(0)
        block = review(block)
        capture("narrow-reviewed-ready", block, activity=ACTIVITY)
        page.screenshot(path=str(output / "narrow-progress-ready.png"), full_page=False)
        page.locator(PAIR).get_by_role("button", name="Edit photos or captions", exact=True).click()
        density = page.locator(PAIR).get_by_role("group", name="Photos per page", exact=True)
        density.scroll_into_view_if_needed()
        expect(density).to_be_in_viewport()
        expect(density.get_by_role("slider")).to_have_count(1)
        expect(panel(1).get_by_role("textbox", name="Caption", exact=True)).to_have_value(ADDED)
        expect(panel(2).get_by_role("textbox", name="Caption", exact=True)).to_have_value(THIRD)
        record["density_accessibility"]["narrow_reentry"] = density.aria_snapshot()
        density.get_by_role("slider").press("End")
        block = replace(block, photos_per_page=6)
        capture("narrow-reentry-density-six", block, activity=ACTIVITY)
        density.get_by_role("slider").press("Home")
        block = replace(block, photos_per_page=1)
        capture("narrow-reentry-density-one", block, activity=ACTIVITY)
        page.set_viewport_size({"width": 545, "height": 757})
        page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='compact'")
        page.locator(PAIR).get_by_role("button", name="Done editing photos", exact=True).click()
        capture("narrow-reentry-done", block, activity=ACTIVITY)
        native_geometry("545-reentry-done")
        native = {}
        capture_native_window_errors(page, native, "final")
        native_documents.append(native["native_window_errors"])
        page.reload(wait_until="domcontentloaded")
        capture("reload-exact-photos-captions-and-activity", block, activity=ACTIVITY)
        live.request_qa_generation(page, "progress-photo-journey")
        word = live.download(page, "Download isolated QA DOCX", "progress-photos.docx")
        pdf = live.download(page, "Download isolated QA PDF", "progress-photos.pdf")
        record["outputs"] = assert_outputs(word, pdf, block.asset_hashes, block.asset_captions, assets)
        capture("first-generation-keeps-shared-history-and-standing", block, activity=ACTIVITY)
        assert not record["browser_errors"] and not record["external_requests"]
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        record["result"] = "passed"
    except Exception as exc:
        record["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            record["last_receipt"] = receipt(page)
            page.screenshot(path=str(output / "first-failure.png"), full_page=False)
        except Exception:
            pass
        raise
    finally:
        primary = sys.exc_info()[0] is not None
        if "photo_native_actions" not in record:
            try:
                record["photo_native_actions"] = page.evaluate("window.__enfraPhotoActionObservations?.() || []")
            except Exception as exc:
                record["photo_observation_error"] = type(exc).__name__
        native = {}
        capture_native_window_errors(page, native, "final")
        native_documents.append(native["native_window_errors"])
        record["native_window_documents"] = native_documents
        record["generation"] = live.EVIDENCE
        failure = None
        if not primary:
            try:
                for snapshots in native_documents:
                    require_no_native_window_errors(snapshots, expected_origin=URL)
                assert not record["browser_errors"] and not record["external_requests"]
            except AssertionError as exc:
                failure = exc
                record["result"] = "failed"
                record["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        cleanup = close_session(context, browser)
        if cleanup:
            record["cleanup_errors"] = cleanup
            if not primary and failure is None:
                failure = AssertionError("Synthetic Progress browser cleanup failed: " + str(cleanup))
                record["result"] = "failed"
        try:
            (output / "widget-delivery.json").write_text(json.dumps(delivery, indent=2))
        except OSError as exc:
            record["delivery_write_error"] = type(exc).__name__ + ": " + str(exc)[:500]
            if not primary and failure is None:
                failure = exc
                record["result"] = "failed"
        try:
            (output / "task.json").write_text(json.dumps(record, indent=2))
        except OSError as exc:
            print("Progress task evidence write failed: " + type(exc).__name__ + ": " + str(exc)[:500], flush=True)
            if not primary and failure is None:
                failure = exc
        if failure:
            raise failure


def main():
    from playwright.sync_api import Browser, BrowserContext, sync_playwright
    from scripts.qa_browser_diagnostics import observe
    OUT.mkdir(parents=True, exist_ok=True)
    failures, completed = [], False
    with tempfile.TemporaryDirectory(prefix="monthly-progress-synthetic-") as temp:
        base = Path(temp)
        (base / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        os.environ.update(EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", EPC_MONTHLY_PROGRESS_TASK="1")
        env = dict(os.environ, ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        env.pop("EPC_MONTHLY_DOM_APPTEST", None)
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "tests/fixtures/workspaces/monthly_app.py",
                "--server.address", "127.0.0.1", "--server.port", str(PORT), "--server.headless", "true",
                "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Guarded Progress fixture stopped during startup")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Guarded Progress fixture did not become healthy")
                with observe(OUT / "diagnostics", Browser, BrowserContext, widget_ports=(PORT,)), sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                        try:
                            browser_task(engine, name, base)
                        except Exception as exc:
                            failures.append(name + ": " + type(exc).__name__ + ": " + str(exc)[:300])
                completed = True
            finally:
                primary = sys.exc_info()[0] is not None
                cleanup = stop_server(process)
                if cleanup:
                    failures.append("server cleanup: " + str(cleanup))
                try:
                    (OUT / "results.json").write_text(json.dumps({"synthetic_only": True,
                        "failures": failures, "cleanup_errors": cleanup,
                        "result": "passed" if completed and not failures else "failed"}, indent=2))
                except OSError as exc:
                    print("Progress results write failed: " + type(exc).__name__ + ": " + str(exc)[:500], flush=True)
                    if not primary:
                        raise
    if failures:
        raise AssertionError("Progress photo browser task failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
