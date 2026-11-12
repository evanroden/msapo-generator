"""Two genuine browser sessions, one synthetic Training store and native recovery.

This does not use AppTest, hidden widget writes, a stub renderer or production
storage. Chromium contexts have separate Streamlit sessions but intentionally
share the SAME synthetic device identity and isolated store. Assertions inspect
the independent on-disk standing head, native conflict/reload UI, immutable
snapshot and the real DOCX/PDF. It does not claim physical-device acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
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
from urllib.request import urlopen

from docx import Document
import pymupdf
from playwright.sync_api import expect, sync_playwright, TimeoutError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "training-two-browser"
PORT = 8548
URL = f"http://127.0.0.1:{PORT}"
REQUIREMENTS = ("Synthetic requirement from editor A", "Synthetic requirement from editor B")


def settled(page):
    page.wait_for_function("""() =>
      document.querySelector('[data-testid="stApp"]')
        ?.getAttribute('data-test-script-state') === 'notRunning'""", timeout=40000)


def snapshot_store(token):
    """Inspect the real shared disk head independently of both browser sessions."""
    from app import monthly_report_training as training
    from app import monthly_report_library as library
    from app.monthly_report_qa_fixture import CONTRACT, PERIOD, profile
    from app.monthly_report_testing import isolated
    with isolated(token):
        stored = training.load_training(CONTRACT)
        saved = library.load_snapshot(CONTRACT, profile().key, PERIOD)
    names = set()
    containers = [stored.get("sites", {})]
    containers.extend(year.get("sites", {}) for year in stored.get("years", {}).values())
    for sites in containers:
        for data in sites.values():
            names.update(data.get("columns", ()))
    return stored["revision"], names, saved


def until_store(token, revision, names=()):
    deadline = time.monotonic() + 35
    last = None
    while time.monotonic() < deadline:
        last = snapshot_store(token)
        if last[0] == revision and set(names).issubset(last[1]):
            return last
        time.sleep(.2)
    raise AssertionError(f"Shared Training did not reach revision {revision}: {last[0] if last else 'unavailable'}")


def add_requirement_form(page, name):
    # Open the panel via the button-visibility loop, not a single read of
    # the <details> open attribute: under the repeated reruns in the
    # conflict phase that read can catch a fresh render and toggle a
    # pre-opened panel shut. (Helper is defined below; resolved at call time.)
    ensure_requirement_panel_open(page)
    field = page.get_by_role("textbox", name="Requirement name", exact=True)
    expect(field).to_be_visible()
    field.fill(name)
    field.press("Tab")  # Deliver the native input before its button becomes enabled.
    expect(field).to_have_value(name)
    expect(page.get_by_role("button", name="Add requirement", exact=True)).to_be_enabled(timeout=20000)
    # The button renders enabled while the rerun the Tab commit started is
    # still going (the rest of the page -- matrix grid, monthly sessions --
    # renders after it). Returning now lets a later click start mid-rerun;
    # on a slow runner the rerun then replaces the button node under
    # Playwright's actionability wait and the click times out detached.
    # Wait the rerun out before the caller does anything with the page.
    settled(page)
    return field


def ensure_requirement_panel_open(page):
    """Make the Add requirement button visible, however the panel got there.

    Do NOT decide from the <details> open attribute: this page reruns every
    few seconds in the conflict phase, and a single instantaneous read can
    catch a fresh closed render of an open panel (or vice versa) and toggle
    a pre-opened panel shut -- which removes the button from the DOM until
    someone reopens it. Instead loop on the button itself: on a settled
    page, a missing button means the panel is closed, so click the summary
    once and re-check. A wrong-way toggle self-corrects on the next pass
    because the check is the button, not the attribute.
    """
    button = page.get_by_role("button", name="Add requirement", exact=True)
    for _ in range(4):
        settled(page)
        if button.count() and button.is_visible():
            return
        panel = page.locator('[data-testid="stExpander"] summary').filter(
            has=page.get_by_text("Add requirement", exact=True))
        expect(panel).to_have_count(1, timeout=30000)
        panel.click()
    settled(page)
    if not (button.count() and button.is_visible()):
        raise AssertionError("Add requirement button never became visible")


def perform_add(page):
    # Never start the click while a rerun is in flight: a rerun that
    # finishes mid-click replaces the button node and Playwright times out
    # detached. One retry covers a rerun that lands after the first click
    # attempt started.
    ensure_requirement_panel_open(page)
    settled(page)
    button = page.get_by_role("button", name="Add requirement", exact=True)
    expect(button).to_be_visible(timeout=30000)
    expect(button).to_be_enabled(timeout=30000)
    try:
        button.click(timeout=30000)
    except TimeoutError:
        ensure_requirement_panel_open(page)
        settled(page)
        button = page.get_by_role("button", name="Add requirement", exact=True)
        expect(button).to_be_visible(timeout=30000)
        expect(button).to_be_enabled(timeout=30000)
        button.click(timeout=30000)
    settled(page)


def open_training(page):
    settled(page)
    preparer = page.get_by_role("textbox", name="Prepared by", exact=True)
    # After a reload + recovery the full page can take well over the 5s
    # default to render on a slow runner; same 40s margin as elsewhere.
    expect(preparer).to_be_visible(timeout=40000)
    if not preparer.input_value():
        preparer.fill("Synthetic two-browser reviewer")
        preparer.press("Tab")
    expect(page.get_by_text("Staff training requirements", exact=True)).to_be_visible(timeout=40000)


def download(page, label, name):
    with page.expect_download(timeout=60000) as request:
        page.get_by_role("button", name=label, exact=True).click()
    target = OUT / name
    request.value.save_as(str(target))
    raw = target.read_bytes()
    return raw, {"file": name, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def verify_output(word, pdf):
    document = Document(BytesIO(word))
    word_text = "\n".join(
        [paragraph.text for paragraph in document.paragraphs] +
        [cell.text for table in document.tables for row in table.rows for cell in row.cells])
    with pymupdf.open(stream=pdf, filetype="pdf") as opened:
        pdf_text = " ".join(" ".join(page.get_text().split()) for page in opened)
    for requirement in REQUIREMENTS:
        assert word_text.count(requirement) == 1, ("DOCX requirement missing or repeated", requirement)
        assert requirement in pdf_text, ("PDF requirement missing", requirement)
    assert word_text.count("Synthetic safety refresher") == 1
    assert pdf_text.count("Synthetic safety refresher") == 1


def browser_context(browser, token):
    context = browser.new_context(viewport={"width": 1365, "height": 900},
                                  accept_downloads=True)
    context.add_cookies([{"name": "epc_device_id", "value": token, "url": URL}])
    def guarded(request):
        parsed = urlparse(request.request.url.removeprefix("blob:"))
        if parsed.scheme == "data" or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            request.abort()
            raise AssertionError("Synthetic browser attempted external network access")
    context.route("**/*", guarded)
    return context


@contextmanager
def server():
    with tempfile.TemporaryDirectory(prefix="monthly-two-browser-") as directory:
        base = Path(directory)
        (base / "monthly-dom-synthetic-only.marker").write_text(
            "synthetic-monthly-dom-v1", encoding="ascii")
        previous = os.environ.get("EPC_DATA_DIR")
        os.environ["EPC_DATA_DIR"] = directory
        environment = dict(os.environ, EPC_MONTHLY_DOM_FIXTURE="1",
                           ANTHROPIC_API_KEY="", SMARTSHEET_API_MODE="disabled",
                           PYTHONDONTWRITEBYTECODE="1")
        with (OUT / "streamlit.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run",
                 "tests/fixtures/workspaces/monthly_app.py", "--server.address",
                 "127.0.0.1", "--server.port", str(PORT), "--server.headless",
                 "true", "--browser.gatherUsageStats", "false"],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("Isolated synthetic server exited")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError("Isolated synthetic server did not become healthy")
                yield
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                if previous is None:
                    os.environ.pop("EPC_DATA_DIR", None)
                else:
                    os.environ["EPC_DATA_DIR"] = previous


def journey():
    evidence = {"synthetic": True, "same_disk_store": True,
                "browser_sessions": 2, "stages": [], "outputs": []}
    token = secrets.token_hex(16)
    with server(), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_a = browser_context(browser, token)
        context_b = browser_context(browser, token)
        a, b = context_a.new_page(), context_b.new_page()
        errors = []
        a.on("pageerror", lambda error: errors.append("A: " + str(error)[:300]))
        b.on("pageerror", lambda error: errors.append("B: " + str(error)[:300]))
        try:
            a.goto(URL, wait_until="domcontentloaded")
            a.get_by_role("button", name="Load known-value report", exact=True).click()
            expect(a.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=45000)
            open_training(a)
            baseline_revision, baseline_names, baseline = snapshot_store(token)
            assert baseline is not None and baseline.revision == 1
            evidence["stages"].append({"stage": "baseline", "standing": baseline_revision,
                                       "snapshot": baseline.revision})

            b.goto(URL, wait_until="domcontentloaded")
            open_training(b)
            # Both independent native editors capture the same old standing
            # revision before either user commits.
            field_b = add_requirement_form(b, REQUIREMENTS[1])
            add_requirement_form(a, REQUIREMENTS[0])
            assert snapshot_store(token)[0] == baseline_revision
            perform_add(a)
            first_revision, first_names, _ = until_store(
                token, baseline_revision + 1, (REQUIREMENTS[0],))
            assert REQUIREMENTS[1] not in first_names
            evidence["stages"].append({"stage": "A commits first", "standing": first_revision})

            perform_add(b)
            expect(b.locator('[data-testid="stAlert"]').filter(has_text="Training was updated elsewhere").first).to_be_visible(timeout=30000)
            expect(field_b).to_have_value(REQUIREMENTS[1])
            assert snapshot_store(token)[0] == first_revision, "Stale B overwrote the shared revision"
            expect(b.get_by_role("button", name="Reload saved training matrix", exact=True)).to_be_visible()
            evidence["stages"].append({"stage": "B blocked", "standing": first_revision,
                                       "pending_input_retained": True})
            b.get_by_role("button", name="Reload saved training matrix", exact=True).click()
            settled(b)
            # Reload legitimately re-renders the Add requirement expander
            # collapsed. Reopen it with a real pointer action BEFORE checking
            # retained native input. Do not refill the textbox or turn a lost
            # value into a false passing recovery. The helper loops on the
            # button itself instead of one read of the <details> open
            # attribute, which can misread under the repeated reruns here
            # and toggle a pre-opened panel shut.
            ensure_requirement_panel_open(b)
            # The retained pending value is checked, not refilled.
            expect(b.get_by_role("textbox", name="Requirement name", exact=True)).to_have_value(
                REQUIREMENTS[1])
            perform_add(b)
            final_revision, final_names, _ = until_store(token, first_revision + 1, REQUIREMENTS)
            assert final_names.issuperset(baseline_names)
            evidence["stages"].append({"stage": "B explicit reload and retry", "standing": final_revision,
                                       "both_changes": True})

            # One deliberate shared save, not the background browser journal,
            # establishes durable report history for downloaded section output.
            disclosure = b.locator('[data-testid="stExpander"] summary').filter(
                has=b.get_by_text("Shared report history", exact=True))
            expect(disclosure).to_have_count(1)
            if disclosure.get_attribute("aria-expanded") != "true":
                disclosure.click()
            b.get_by_role("button", name="Save shared version", exact=True).click()
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                saved = snapshot_store(token)[2]
                if saved and saved.revision == baseline.revision + 1:
                    break
                time.sleep(.2)
            else:
                raise AssertionError("Two-session corrected report was not saved")
            matrix = next(table for block in saved.draft.blocks
                          if block.key == "training_summary"
                          for table in block.extra_tables
                          if table.columns[:2] == ("Team member", "Site"))
            assert set(REQUIREMENTS).issubset(matrix.columns)
            event_rows = [row for block in saved.draft.blocks if block.key == "training_summary"
                          for table in block.extra_tables if table.reference == "training:events:v1"
                          for row in table.rows]
            assert len(event_rows) == 1 and event_rows[0][0] == "Synthetic safety refresher"
            assert saved.draft.prepared_by
            evidence["stages"].append({"stage": "shared save", "snapshot": saved.revision,
                                       "requirements": len(matrix.columns) - 2,
                                       "monthly_events": len(event_rows)})

            b.reload(wait_until="domcontentloaded")
            settled(b)
            # Both real contexts intentionally share a recovery identity. An
            # interrupted older browser journal may now be based on snapshot 1.
            # The UI must offer a deliberate choice; never silently replace
            # snapshot 2 or accept its old draft as a new completion.
            # The recovery prompt renders on a later run than the landing
            # view, so a single count() right after settled() can miss it:
            # wait for whichever state the page reaches -- the prompt or the
            # editor -- instead of assuming the first settled render is final.
            # While the prompt is up the editor below it does not render, so
            # the two are mutually exclusive.
            deadline = time.monotonic() + 60
            review = b.get_by_role("button", name="Review draft changes", exact=True)
            preparer = b.get_by_role("textbox", name="Prepared by", exact=True)
            while time.monotonic() < deadline:
                if review.count() or preparer.count():
                    break
                time.sleep(.5)
            else:
                raise AssertionError(
                    "After reload neither the draft-recovery prompt nor the "
                    "report editor appeared within 60s")
            if review.count():
                review.click()
                expect(b.get_by_role("button", name="Open saved report", exact=True)).to_be_visible()
                b.get_by_role("button", name="Open saved report", exact=True).click()
                evidence["stages"].append({"stage": "explicit saved-version recovery", "chosen": "saved"})
                settled(b)
            open_training(b)
            b.get_by_role("button", name="Generate QA Word and PDF", exact=True).click()
            expect(b.get_by_role("button", name="Download isolated QA DOCX", exact=True)).to_be_visible(timeout=180000)
            expect(b.get_by_role("button", name="Download isolated QA PDF", exact=True)).to_be_visible(timeout=60000)
            word, word_receipt = download(b, "Download isolated QA DOCX", "corrected.docx")
            pdf, pdf_receipt = download(b, "Download isolated QA PDF", "corrected.pdf")
            verify_output(word, pdf)
            evidence["outputs"].extend((word_receipt, pdf_receipt))
            assert not errors, errors
            evidence["passed"] = True
        except Exception:
            evidence["passed"] = False
            evidence["error"] = traceback.format_exc()[:4000]
            for label, page in (("A", a), ("B", b)):
                try:
                    page.screenshot(path=str(OUT / f"{label}-first-failure.png"))
                except Exception:
                    pass
            raise
        finally:
            (OUT / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
            context_b.close()
            context_a.close()
            browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    journey()


if __name__ == "__main__":
    main()
