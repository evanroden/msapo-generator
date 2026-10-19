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
    try:
        page.goto(qa.URL, wait_until="domcontentloaded")
        live.load_fixture(page, "replay")
        before = fingerprint(page)
        date_warning = page.locator('[data-testid="stAlert"]').filter(has_text=
            "Confirm the reporting date for synthetic-activity.txt; no date has been established.")
        date_link = date_warning.get_by_role("link", name="Correct date", exact=True)
        date_link.scroll_into_view_if_needed()
        link_y = date_link.bounding_box()["y"]
        date_link.click()
        form = source_form(page)
        expect(form).to_have_count(1)
        date_input = form.get_by_test_id("stDateInput").locator("input")
        expect(date_input).to_be_focused()
        assert not date_input.evaluate("node => Boolean(node.closest('[inert]'))")
        assert date_input.input_value() == "", "Opening a correction must not invent a source date."
        qa.capture(page, name, "source-date-link")
        page.get_by_role("link", name="Return to review", exact=True).filter(visible=True).press("Enter")
        expect(date_link).to_be_focused()
        assert abs(date_link.bounding_box()["y"] - link_y) <= qa.TOLERANCE
        assert fingerprint(page) == before, "Display and navigation cannot save source details."

        # Close through the ordinary native summary. The next correction must
        # itself open a closed panel; an earlier date visit cannot mask it.
        disclosure = form.locator("xpath=ancestor::details[1]")
        disclosure.locator(":scope > summary").click()
        assert not disclosure.evaluate("node => node.open")
        live.correct_replay_source_scope(page)
        corrected = fingerprint(page)
        assert corrected != before
        record.update(before=before, corrected=corrected)
        qa.capture(page, name, "source-site-correction-saved")

        # This existing independent comparison includes original source-byte
        # digests. A reviewer choice is never described as extracted evidence.
        page.get_by_role("button", name="Compare fixture facts", exact=True).click()
        expect(page.get_by_text(re.compile(
            r"^QA comparison completed: source replay · 18/18 · action [0-9a-f]{12} · at "
        ))).to_have_count(1, timeout=25000)

        page.set_viewport_size({"width": 390, "height": 844})
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
            qa.capture(page, name, "source-correction-first-failure")
        except Exception as capture_error:
            record["capture_failure"] = str(capture_error)[:500]
        raise
    finally:
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
