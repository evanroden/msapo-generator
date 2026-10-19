"""Native source correction links in the existing isolated Monthly fixture.

Both engines use actual source replay, pointer/keyboard links and normal form
submission. No injected report state, external reading, generation or sharing.
"""
import json
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fingerprint(page):
    from playwright.sync_api import expect
    working = page.get_by_text(re.compile(r"^QA working report SHA256: [0-9a-f]{64}$")).last
    working.wait_for()
    value = working.text_content().split(": ")[-1]
    expect(page.get_by_text("QA durable report SHA256: " + value, exact=True)).to_have_count(1)
    return value


def source_form(page):
    return page.locator('[data-testid="stForm"]').filter(has=
        page.locator('[data-testid="stMultiSelect"]').filter(has_text="Source sites")).filter(visible=True)


def observe_correction_navigation(page):
    """Read native event geometry without submitting, scrolling or moving nodes."""
    page.evaluate("""() => {
        const samples = [], ids = new WeakMap(); let nextId = 1, pressed = null;
        const id = node => {
            if (!node) return null;
            if (!ids.has(node)) ids.set(node, nextId++);
            return ids.get(node);
        };
        const owner = node => {
            for (let p = node.parentElement; p; p = p.parentElement)
                if (p.scrollHeight > p.clientHeight && /auto|scroll/.test(getComputedStyle(p).overflowY)) return p;
            return document.scrollingElement;
        };
        for (const type of ['pointerdown', 'pointerup', 'pointercancel', 'click', 'keydown', 'focusin'])
            document.addEventListener(type, event => {
                const link = event.target.closest?.('a');
                const owned = link && (link.getAttribute('href')?.startsWith('#source-details-') ||
                    link.classList.contains('enfra-source-review-return'));
                if (type === 'pointerdown') pressed = owned ? link : null;
                const observed = owned ? link : (['pointerup', 'pointercancel', 'click'].includes(type) ? pressed : null);
                if (!observed) return;
                const rect = observed.getBoundingClientRect(), scroll = owner(observed);
                const workspace = observed.closest('[class*="st-key-epc_workspace_monthly"]');
                samples.push({type, time:performance.now(), key:event.key || '',
                    node:id(observed), source:observed.getAttribute('href'),
                    eventTarget:id(event.target), targetIsOwnedLink:Boolean(owned),
                    connected:observed.isConnected,
                    handlerReady:Boolean(workspace?._epcWorkspace && workspace?.dataset.epcMode),
                    skeletons:workspace?.querySelectorAll('[data-testid="stSkeleton"]').length || 0,
                    rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
                    scroll:{node:id(scroll),top:scroll.scrollTop,height:scroll.scrollHeight,
                        clientHeight:scroll.clientHeight}, focused:document.activeElement === observed});
                if (type === 'click' || type === 'pointercancel') pressed = null;
            }, {capture:true,passive:true});
        window.__sourceCorrectionNavigationObservations = samples;
    }""")


def browser_task(browser_type, name):
    from playwright.sync_api import expect
    from scripts import qa_monthly_adaptive as qa, qa_monthly_live as live
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16), "url": qa.URL}])
    context.add_init_script(qa.CLIENT_INIT)
    errors, external = [], []

    def route(request):
        address = urlparse(request.request.url)
        if address.scheme in {"data", "blob"} or (address.hostname == "127.0.0.1" and address.port == 8520):
            request.continue_()
        else:
            external.append(address.hostname)
            request.abort()

    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    record = {"synthetic_only": True, "errors": errors, "external": external}
    out = qa.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    # Hold the unchanged local native v2 module so the initial warning is
    # exercised before its navigation adapter can exist. This changes only
    # delivery timing; no source, input, event or page geometry is injected.
    component_module = re.compile(re.escape(qa.URL) + r"/static/js/BidiComponent\.[^/?]+\.js$")
    held = []
    page.route(component_module, lambda route: held.append(route))
    try:
        record["stage"] = "cold source warning before the native adapter"
        with page.expect_request(component_module, timeout=20000):
            page.goto(qa.URL, wait_until="domcontentloaded")
            live.load_fixture(page, "replay")
        before = fingerprint(page)
        observe_correction_navigation(page)
        date_warning = page.locator('[data-testid="stAlert"]').filter(has_text=
            "Confirm the reporting date for synthetic-activity.txt; no date has been established.")
        date_link = date_warning.get_by_role("link", name="Correct date", exact=True)
        expect(date_warning.get_by_text("Loading correction controls…", exact=True)).to_be_visible()
        expect(date_link).to_have_count(0)
        expect(page.get_by_role("button", name="Create Word and PDF", exact=True)).to_be_disabled()
        record["cold_navigation"] = {"held_requests": len(held), "warning_visible": True,
            "inactive_link_count": date_link.count(), "before": before}
        assert len(held) == 1, "Hold the one original BidiComponent module, not a replacement."
        record["cold_navigation"]["module"] = held[0].request.url.rsplit("/", 1)[-1]
        held.pop().continue_()
        page.unroute(component_module)
        source_marker = date_link.get_attribute("href").rsplit("--", 1)[0].removeprefix("#")
        assert re.fullmatch(r"source-details-[0-9a-f]{64}", source_marker)
        source_panel = page.locator('[class*="st-key-source_detail_editor_"]').filter(
            has=page.locator('[id="' + source_marker + '"]'))
        record["stage"] = "first date link and native focus"
        date_link.scroll_into_view_if_needed()
        record["warning_before_pointer_action"] = date_link.bounding_box()
        date_link.click()
        pointer_samples = page.evaluate("window.__sourceCorrectionNavigationObservations").copy()
        pointer = next(sample for sample in reversed(pointer_samples)
                       if sample["type"] == "pointerdown" and sample["source"].endswith("--date"))
        record["warning_at_native_pointer_action"] = pointer
        assert pointer["handlerReady"], "A displayed correction link needs its owned native handler."
        clicks = [sample for sample in pointer_samples if sample["type"] == "click" and
                  sample["source"] == pointer["source"]]
        releases = [sample for sample in pointer_samples if sample["type"] == "pointerup" and
                    sample["source"] == pointer["source"]]
        assert len(clicks) == len(releases) == 1, "The first intended pointer action must deliver once."
        assert clicks[0]["node"] == releases[0]["node"] == pointer["node"]
        assert clicks[0]["targetIsOwnedLink"] and releases[0]["targetIsOwnedLink"]
        link_y = pointer["rect"]["y"]
        assert 0 <= link_y < 900, "The native pointer must reach the visible warning."
        form = source_form(page)
        expect(form).to_have_count(1)
        date_input = form.get_by_test_id("stDateInput").locator("input")
        expect(date_input).to_be_focused()
        assert not date_input.evaluate("node => Boolean(node.closest('[inert]'))")
        assert date_input.input_value() == "", "Opening a correction must not invent a source date."
        qa.capture(page, name, "source-date-link")
        record["stage"] = "return to the same warning without saving"
        page.get_by_role("link", name="Return to review", exact=True).filter(visible=True).press("Enter")
        expect(date_link).to_be_focused()
        record["warning_after_return"] = date_link.bounding_box()
        record["navigation_samples"] = page.evaluate("window.__sourceCorrectionNavigationObservations")
        assert abs(date_link.bounding_box()["y"] - link_y) <= qa.TOLERANCE
        assert fingerprint(page) == before, "Display and navigation cannot save source details."

        # Close through the ordinary native summary. The next correction must
        # itself open a closed panel; an earlier date visit cannot mask it.
        record["stage"] = "close the native source panel"
        disclosure = source_panel.locator("details")
        expect(disclosure).to_have_count(1)
        disclosure.locator(":scope > summary").click()
        # Native details.open stays true until the closing animation ends.
        # Observe the same panel independently of its now-hidden form.
        expect(disclosure).not_to_have_attribute("open", re.compile(r".*"))
        expect(source_form(page)).to_have_count(0)
        record["stage"] = "deliberate site correction and linked evidence"
        live.correct_replay_source_scope(page)
        corrected = fingerprint(page)
        assert corrected != before
        record.update(before=before, corrected=corrected)
        qa.capture(page, name, "source-site-correction-saved")

        # This existing independent comparison includes original source-byte
        # digests. A reviewer choice is never described as extracted evidence.
        record["stage"] = "independent fixture comparison"
        page.get_by_role("button", name="Compare fixture facts", exact=True).click()
        expect(page.get_by_text(re.compile(
            r"^QA comparison completed: source replay · 18/18 · action [0-9a-f]{12} · at "
        ))).to_have_count(1, timeout=25000)

        page.set_viewport_size({"width": 390, "height": 844})
        record["stage"] = "narrow reload and keyboard date re-entry"
        page.reload(wait_until="domcontentloaded")
        expect(page.get_by_text("QA durable report SHA256: " + corrected, exact=True)).to_have_count(1, timeout=30000)
        assert fingerprint(page) == corrected
        expect(page.get_by_text(re.compile(r"^Establish the site scope of synthetic-activity.txt"))).to_have_count(0)
        date_link = page.locator('[data-testid="stAlert"]').filter(has_text=
            "Confirm the reporting date for synthetic-activity.txt; no date has been established."
        ).get_by_role("link", name="Correct date", exact=True)
        date_link.press("Enter")
        form = source_form(page)
        date_input = form.get_by_test_id("stDateInput").locator("input")
        expect(date_input).to_be_focused()
        expect(form.get_by_text("Demo North", exact=True)).to_be_visible()
        assert not date_input.evaluate("node => Boolean(node.closest('[inert]'))")
        assert date_input.input_value() == ""
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2")
        assert fingerprint(page) == corrected
        qa.capture(page, name, "source-correction-narrow-reload")
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        assert not errors and not external
        record["result"] = "passed"
        qa.check(name, "Source links reach native fields; deliberate correction survives narrow reload", True)
    except Exception as exc:
        record.update(result="failed", failure={"type": type(exc).__name__, "message": str(exc)[:3000]})
        try:
            record["navigation_samples_at_failure"] = page.evaluate(
                "window.__sourceCorrectionNavigationObservations || []")
        except Exception as observation_error:
            record["navigation_observation_failure"] = str(observation_error)[:500]
        try:
            qa.capture(page, name, "source-correction-first-failure")
        except Exception as capture_error:
            record["capture_failure"] = str(capture_error)[:500]
        raise
    finally:
        for request in held:
            request.continue_()
        page.unroute(component_module)
        (out / "source-corrections.json").write_text(json.dumps(record, indent=2))
        context.close()
        browser.close()


def main():
    from scripts import qa_monthly_adaptive as qa
    from playwright.sync_api import Browser, BrowserContext
    from scripts.qa_browser_diagnostics import observe
    qa.OUT = ROOT / "test-artifacts" / "source-corrections"
    qa.REPORT = {"synthetic_only": True, "physical_device": False,
                 "actual_workflow": "native source correction links and form",
                 "browsers": {}, "checks": []}
    qa.exercise = browser_task
    with observe(qa.OUT / "diagnostics", Browser, BrowserContext):
        qa.main()


if __name__ == "__main__":
    main()
