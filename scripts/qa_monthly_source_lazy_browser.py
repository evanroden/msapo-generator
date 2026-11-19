"""Native 50-source Streamlit A30 regression with actual browser form buffers.

Runs only an isolated synthetic localhost fixture on both Chromium and WebKit.
No test fixture bypasses native Streamlit widgets or submits a form in Python.
The legacy manager finishes source selection on its NEXT full rerun; this
fixture explicitly performs one neutral rerun to exercise that handoff.
"""
from contextlib import contextmanager
import json
import os
import re
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from google.protobuf.message import DecodeError
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "test-artifacts" / "a30-source-lazy-browser"
PORT = 8552
URL = f"http://127.0.0.1:{PORT}"
PANEL = 'div[class*="_source_manager_panel"]'
SOURCE_A = "synthetic-source-00.pdf"
SOURCE_B = "synthetic-source-49.pdf"


def settled(page):
    page.wait_for_function("""() => document.querySelector('[data-testid="stApp"]')
      ?.getAttribute('data-test-script-state')==='notRunning'""", timeout=60000)


def receipt(page):
    marker = page.locator("[data-a30-receipt]")
    expect(marker).to_have_count(1)
    return json.loads(marker.get_attribute("data-a30-receipt"))


def visible_dates(page):
    return page.locator('[data-testid="stDateInput"]').filter(visible=True)


def date_for(page, filename):
    source = page.locator('[class*="st-key-a30_managed_source_"]').filter(has_text=filename)
    expect(source).to_have_count(1)
    disclosure = source.locator('[data-testid="stExpander"]').first
    if disclosure.count() and not disclosure.locator("details").first.get_attribute("open") == "":
        disclosure.locator("summary").first.click()
    field = source.get_by_test_id("stDateInputField")
    expect(field).to_be_visible()
    return field


def refresh(page):
    page.get_by_role("button", name="Refresh synthetic source view", exact=True).click()
    settled(page)


def select_file(page, name):
    control = page.get_by_role("combobox", name="File to review", exact=True)
    control.click()
    # Fifty files form a virtualized option list; typing filters this file
    # into view, as a person would, before choosing it.
    control.press_sequentially(name)
    page.get_by_role("option", name=name, exact=True).click()
    settled(page)
    # The current manager commits the previous file's delivered page inputs
    # before moving its active source. This read-only rerun completes it.
    refresh(page)


def same_date(value):
    """The typed date in any separator the field displays.

    Source date uses format="YYYY-MM-DD". Typing shows the keyed separators,
    and a rerender redraws the same unsent value with the mask's own
    separator ("2026\u201309\u201321"); both are the same native value.
    """
    year, month, day = re.split(r"\D", value)
    return re.compile(rf"^{year}\D{month}\D{day}$")


def type_date(page, field, value, stage):
    """Type a Source date with the keyboard and leave it unsent in the form.

    The Training date helper asserts its own YYYY/MM/DD display; this field
    redraws the same date with its mask separator once it loses focus.
    """
    field.click()
    field.press("ControlOrMeta+A")
    field.press("Backspace")
    expect(field).to_have_value("")
    field.press_sequentially(value)
    field.press("Tab")
    expect(field).to_have_value(same_date(value))


def wait_receipt(page, check, what, timeout=30):
    """Poll the fixture receipt: a settled page can still precede the rerun."""
    deadline = time.monotonic() + timeout
    while True:
        settled(page)
        value = receipt(page)
        if check(value):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(what + ": " + json.dumps(value, sort_keys=True))
        page.wait_for_timeout(100)


@contextmanager
def fixture_server(engine):
    with tempfile.TemporaryDirectory(prefix="a30-source-native-") as root:
        environment = dict(os.environ, EPC_DATA_DIR=root, ANTHROPIC_API_KEY="",
                           SMARTSHEET_API_MODE="disabled", PYTHONDONTWRITEBYTECODE="1")
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / (engine + "-streamlit.log")).open("w") as output:
            process = subprocess.Popen([
                sys.executable, "-m", "streamlit", "run",
                "tests/fixtures/workspaces/monthly_source_lazy_app.py",
                "--server.address", "127.0.0.1", "--server.port", str(PORT),
                "--server.headless", "true", "--browser.gatherUsageStats", "false",
                "--server.fileWatcherType", "none",
            ], cwd=ROOT, env=environment, stdout=output, stderr=subprocess.STDOUT)
            try:
                start = time.monotonic()
                while time.monotonic() - start < 35:
                    if process.poll() is not None:
                        raise RuntimeError("Synthetic A30 server exited before startup")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("A30 localhost fixture startup timed out")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def exercise(browser, label):
    record = {"engine": label, "synthetic": True, "source_count": 50, "steps": {},
              "actual_client_document": False, "live_deployment": False}
    with fixture_server(label):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.tracing.start(screenshots=False, snapshots=True, sources=False)
        page = context.new_page()
        page.set_default_timeout(45000)
        errors, external = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Aggregate real Streamlit WebSocket deltas, never upload/source values.
        wire = {"frames": 0, "deltas": 0, "bytes": 0}
        def received(raw):
            if not isinstance(raw, bytes):
                return
            wire["frames"] += 1
            wire["bytes"] += len(raw)
            packet = ForwardMsg()
            try:
                packet.ParseFromString(raw)
            except DecodeError:
                return
            wire["deltas"] += packet.WhichOneof("type") == "delta"
        page.on("websocket", lambda socket: socket.on("framereceived", received))

        def routing(route):
            uri = urlparse(route.request.url)
            if uri.scheme in ("blob", "data") or (uri.hostname == "127.0.0.1" and uri.port == PORT):
                route.continue_()
            else:
                external.append(uri.hostname)
                route.abort_()
        context.route("**/*", routing)
        try:
            start = time.monotonic()
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            settled(page)
            record["steps"]["cold_s"] = round(time.monotonic() - start, 3)
            record["steps"]["cold_wire"] = dict(wire)
            record["steps"]["cold_panel_elements"] = page.locator(PANEL).locator("[data-testid]").count()
            expect(page.locator(PANEL)).not_to_be_visible()
            assert receipt(page)["sources"] == 50
            assert receipt(page)["residents"] == 0
            assert len(page.locator('[data-testid="stDateInput"]').all()) == 0
            begin = time.monotonic()
            page.get_by_role("button", name="Manage source files", exact=True).click()
            settled(page)
            record["steps"]["open_s"] = round(time.monotonic() - begin, 3)
            record["steps"]["open_wire_delta"] = {key: wire[key] - record["steps"]["cold_wire"][key]
                                                    for key in wire}
            record["steps"]["open_panel_elements"] = page.locator(PANEL).locator("[data-testid]").count()
            expect(page.locator(PANEL)).to_be_visible()
            wait_receipt(page, lambda r: r["residents"] == 1, "opening mounts one visited source form")
            expect(page.locator('[data-testid="stDateInput"]')).to_have_count(1)
            assert page.get_by_role("combobox", name="File to review", exact=True).count() == 1
            first = date_for(page, SOURCE_A)
            type_date(page, first, "2026/09/21", "a30-first-unsubmitted")
            # The new Date is in the native unsent form and is NOT yet canonical.
            assert receipt(page)["dates"][SOURCE_A] != "2026-09-21"
            begin = time.monotonic()
            select_file(page, SOURCE_B)
            record["steps"]["switch_s"] = round(time.monotonic() - begin, 3)
            wait_receipt(page, lambda r: r["residents"] == 2, "switching keeps both visited forms")
            assert receipt(page)["dates"][SOURCE_A] != "2026-09-21"
            expect(first).to_have_value(same_date("2026/09/21"))
            second = date_for(page, SOURCE_B)
            type_date(page, second, "2026/09/22", "a30-second-submission")
            second_panel = page.locator('[class*="st-key-a30_managed_source_"]').filter(has_text=SOURCE_B)
            second_panel.get_by_role("button", name="Use these source details").click()
            wait_receipt(page, lambda r: r["dates"][SOURCE_B] == "2026-09-22", "second source date saved")
            assert receipt(page)["dates"][SOURCE_A] != "2026-09-21"
            select_file(page, SOURCE_A)
            first = date_for(page, SOURCE_A)
            expect(first).to_have_value(same_date("2026/09/21"))
            page.get_by_role("button", name="Done with source files", exact=True).click()
            settled(page)
            expect(page.locator(PANEL)).not_to_be_visible()
            wait_receipt(page, lambda r: r["residents"] == 2 and not r["opened"], "Done hides both visited forms")
            page.get_by_role("button", name="Manage source files", exact=True).click()
            settled(page)
            first = date_for(page, SOURCE_A)
            expect(first).to_have_value(same_date("2026/09/21"))
            source = page.locator('[class*="st-key-a30_managed_source_"]').filter(has_text=SOURCE_A)
            source.get_by_role("button", name="Use these source details").click()
            wait_receipt(page, lambda r: r["dates"][SOURCE_A] == "2026-09-21", "first source's unsent date saved")
            assert receipt(page)["dates"][SOURCE_B] == "2026-09-22"
            refresh(page)
            assert receipt(page)["dates"][SOURCE_A] == "2026-09-21"
            assert receipt(page)["dates"][SOURCE_B] == "2026-09-22"
            page.set_viewport_size({"width": 390, "height": 844})
            settled(page)
            assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2")
            expect(date_for(page, SOURCE_A)).to_be_visible()
            record["steps"]["narrow_width_px"] = 390
            record["steps"]["visited_metadata_forms"] = receipt(page)["residents"]
            record["steps"]["full_wire"] = dict(wire)
            record["steps"]["saved_dates"] = [receipt(page)["dates"][SOURCE_A], receipt(page)["dates"][SOURCE_B]]
            assert not errors and not external, {"javascript_errors": errors, "external_attempts": external}
            record["result"] = "passed"
        except Exception as exc:
            record["result"] = "failed"
            record["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1500]}
            try:
                page.screenshot(path=str(OUT / (label + "-first-failure.png")), full_page=False)
            except Exception:
                pass
            raise
        finally:
            record["javascript_errors"] = errors[:10]
            record["external_attempts"] = external[:10]
            (OUT / (label + ".json")).write_text(json.dumps(record, indent=2) + "\n")
            context.tracing.stop(path=str(OUT / (label + "-trace.zip")))
            context.close()
    return record


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    failed = []
    with sync_playwright() as playwright:
        for label, engine in (("chromium", playwright.chromium), ("webkit", playwright.webkit)):
            browser = engine.launch(headless=True)
            try:
                try:
                    results.append(exercise(browser, label))
                except Exception as exc:
                    failed.append({"engine": label, "error": type(exc).__name__ + ": " + str(exc)[:400]})
            finally:
                browser.close()
    (OUT / "results.json").write_text(json.dumps({"synthetic": True, "engines": results, "failures": failed}, indent=2) + "\n")
    if failed:
        raise AssertionError("A30 native browser regressions failed: " + ", ".join(f["engine"] for f in failed))
    print("A30 passed: 50 synthetic files, native unsent date forms, switch/save, Done/reopen, narrow view in both engines")


if __name__ == "__main__":
    main()
