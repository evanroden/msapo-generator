"""Native Chromium A62 Review activation and stale-retry synthetic witness.

Tests actual browser viewport/Streamlit callbacks. The renderer is the explicit
two-page synthetic fixture, NOT an authentic DOCX/PDF conversion or served app.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PORT = 8552
URL = f"http://127.0.0.1:{PORT}/"
ARTIFACT = ROOT / "test-artifacts" / "monthly-a62-review"


def settled(page):
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
        ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=45000)


def value_after(page, label):
    return page.get_by_text(label, exact=False).last.inner_text(timeout=30000).split(": ", 1)[-1].strip()


def go_review(page):
    """Scroll Review into view and make sure it stays there.

    Right after the first run a late rerender can leave the page at the top,
    so a single scroll is not proof the person reached Review. Retry the
    ordinary scroll a few times; fail if Review never stays in view.
    """
    from playwright.sync_api import expect
    heading = page.locator("#report-review")
    for _ in range(4):
        heading.scroll_into_view_if_needed(timeout=20000)
        page.wait_for_timeout(400)
        if heading.evaluate("""node => { const r = node.getBoundingClientRect();
                return r.bottom > 0 && r.top < window.innerHeight; }"""):
            return
        settled(page)
    expect(heading).to_be_in_viewport()


def set_checkbox(page, name, selected):
    """Click the visible label, as a person does.

    The locked Streamlit runtime clips the semantic input inside React Aria's
    VisuallyHidden wrapper, so check()/uncheck() on the input is intercepted.
    """
    from playwright.sync_api import expect
    control = page.get_by_role("checkbox", name=name, exact=True)
    expect(control).to_have_count(1)
    if control.is_checked() != selected:
        label = control.locator("xpath=ancestor::label[1]")
        label.scroll_into_view_if_needed()
        label.click()
    expect(control).to_be_checked(checked=selected)


def check():
    from playwright.sync_api import sync_playwright, expect
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    timings = {"mode": "real Chromium visibility, fixture PDF renderer", "user_preview_clicks": 0}
    with tempfile.TemporaryDirectory(prefix="monthly-a62-browser-") as directory:
        environment = dict(os.environ, EPC_DATA_DIR=directory, ANTHROPIC_API_KEY="")
        command = [sys.executable, "-m", "streamlit", "run",
                   str(ROOT / "tests/fixtures/workspaces/monthly_a62_review_app.py"),
                   "--server.address", "127.0.0.1", "--server.port", str(PORT),
                   "--server.headless", "true", "--browser.gatherUsageStats", "false"]
        logs = ARTIFACT / "streamlit.log"
        with logs.open("w") as output:
            server = subprocess.Popen(command, cwd=ROOT, env=environment,
                                      stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise AssertionError("Fixture Streamlit terminated before startup.")
                    try:
                        with closing(urlopen(URL + "_stcore/health", timeout=1)) as response:
                            if response.status == 200:
                                break
                    except (OSError, ValueError):
                        time.sleep(.25)
                else:
                    raise AssertionError("Fixture Streamlit health did not become ready.")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(viewport={"width": 1250, "height": 800})
                        page.goto(URL, wait_until="domcontentloaded", timeout=45000)
                        expect(page.get_by_text("A62 synthetic Review visibility")).to_be_visible(timeout=45000)
                        settled(page)
                        # Review is well below the initial viewport. Never
                        # generate automatically for somebody editing at top.
                        assert value_after(page, "QA ticket revision:") == "none"
                        begin = time.perf_counter()
                        go_review(page)
                        expect(page.get_by_text("Current draft · page 1 of 2", exact=False)).to_be_visible(timeout=45000)
                        timings["cold_first_review_ms"] = round((time.perf_counter() - begin) * 1000, 2)
                        settled(page)  # read the captions that run wrote, not stale copies
                        initial = value_after(page, "QA canonical revision:")
                        assert initial == value_after(page, "QA ticket revision:")
                        assert "Synthetic unvisited last-section fact." in value_after(page, "QA rendered text:")
                        assert page.get_by_role("button", name="Preview current draft").count() == 1

                        # Do not let a view callback erase an unblurred input;
                        # it must be delivered through the native editor first.
                        note = page.get_by_role("textbox", name="QA Activity note")
                        note.scroll_into_view_if_needed()
                        set_checkbox(page, "QA fail next preview", True)
                        settled(page)
                        note = page.get_by_role("textbox", name="QA Activity note")
                        note.fill("Synthetic accepted A62 edited last-section fact.")
                        # Scrolling alone must not mutate the unsent native field.
                        go_review(page)
                        note.scroll_into_view_if_needed()
                        expect(note).to_have_value("Synthetic accepted A62 edited last-section fact.")
                        note.press("Tab")  # commits native on_change, not a bypass
                        # The blur rerun may not have started yet: wait for the
                        # accepted edit to replace the revision, then settle.
                        expect(page.get_by_text("QA canonical revision: " + initial)).to_have_count(0, timeout=30000)
                        settled(page)
                        edited = value_after(page, "QA canonical revision:")
                        assert edited != initial
                        assert value_after(page, "QA ticket revision:") == initial
                        fail_start = time.perf_counter()
                        go_review(page)
                        expect(page.get_by_text("Synthetic Review conversion temporarily unavailable.",
                                                exact=True)).to_be_visible(timeout=45000)
                        timings["failed_refresh_visible_ms"] = round((time.perf_counter() - fail_start) * 1000, 2)
                        expect(page.get_by_text("Older draft · page 1 of 2", exact=False)).to_be_visible()
                        settled(page)
                        assert value_after(page, "QA ticket revision:") == initial
                        assert "Synthetic unvisited last-section fact." in value_after(page, "QA rendered text:")
                        assert "Synthetic accepted A62" in note.input_value()

                        # One explicit retry, after removing the deterministic
                        # fixture failure, replaces old pages without stale claim.
                        set_checkbox(page, "QA fail next preview", False)
                        settled(page)
                        go_review(page)
                        retry_start = time.perf_counter()
                        page.get_by_role("button", name="Preview current draft").click()
                        expect(page.get_by_text("Current draft · page 1 of 2", exact=False)).to_be_visible(timeout=45000)
                        timings["warm_retry_ms"] = round((time.perf_counter() - retry_start) * 1000, 2)
                        settled(page)
                        assert value_after(page, "QA ticket revision:") == value_after(page, "QA canonical revision:")
                        assert "Synthetic accepted A62 edited last-section fact." in value_after(page, "QA rendered text:")
                        timings["user_preview_clicks"] = 1  # explicit failure recovery only
                        page.screenshot(path=str(ARTIFACT / "review-after-retry.png"))
                    except Exception:
                        try:
                            page.screenshot(path=str(ARTIFACT / "first-failure.png"), full_page=True)
                        except Exception:
                            pass
                        raise
                    finally:
                        browser.close()
            finally:
                server.terminate()
                try:
                    server.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        timings["server_child_user_cpu_s"] = round(child.ru_utime, 3)
        timings["server_child_system_cpu_s"] = round(child.ru_stime, 3)
        timings["server_child_max_rss_kib"] = child.ru_maxrss
    (ARTIFACT / "measurements.json").write_text(json.dumps(timings, indent=2), encoding="utf-8")
    print(json.dumps(timings, sort_keys=True))


if __name__ == "__main__":
    check()
