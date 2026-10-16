"""Real shared-history UI in the existing marked, cookie-isolated Monthly fixture.

No live route, backend report injection, generation, shared submission or retry.
The controller inventories real files after each read-only action; cached DOM
receipts alone cannot certify that a resize left durable storage unchanged.
"""
from hashlib import sha256
from datetime import datetime, timezone
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
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright, Browser, BrowserContext
from scripts import qa_monthly_live as live
from scripts.qa_browser_diagnostics import observe
from scripts.workspace_history_observations import storage_state
from scripts.workspace_wire_observations import WireObservations

OUT = ROOT / "test-artifacts" / "monthly-history"
PORT = 8542
URL = f"http://127.0.0.1:{PORT}"
RECEIPT = "[data-enfra-history-receipt]"
AUTHOR_ONE = "Synthetic history editor North"
AUTHOR_TWO = "Synthetic history editor South"
ACTIVITY_ONE = "Synthetic history version: strainer inspection completed."
ACTIVITY_TWO = "Synthetic history version: valve inspection completed."
UNSAVED = "Synthetic current draft: follow-up survey remains pending."


def receipt(page):
    return json.loads(page.locator(RECEIPT).last.get_attribute("data-enfra-history-receipt"))


def await_state(page, identity, *, revision=None, author=None, activity=None, photos=None, after=0):
    page.wait_for_function("""wanted => {
      const nodes=document.querySelectorAll('[data-enfra-history-receipt]');
      if(!nodes.length)return false;
      const s=JSON.parse(nodes[nodes.length-1].dataset.enfraHistoryReceipt);
      return s.scope===wanted.scope && s.sequence>wanted.after &&
        (wanted.revision===null||s.saved_revision===wanted.revision) &&
        (wanted.author===null||s.working?.author===wanted.author) &&
        (wanted.activity===null||s.working?.activity===wanted.activity) &&
        (wanted.photos===null||s.working?.photos.length===wanted.photos) &&
        (!s.working||JSON.stringify(s.working)===JSON.stringify(s.durable)) &&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }""", arg={"scope": identity, "revision": revision,
        "author": sha256(author.encode()).hexdigest() if author is not None else None,
        "activity": sha256(activity.encode()).hexdigest() if activity is not None else None,
        "photos": photos, "after": after}, timeout=30000)
    return receipt(page)


def history(page):
    return page.get_by_test_id("stExpander").filter(
        has=page.locator("summary").get_by_text("Shared report history", exact=True))


def set_history(page, opened, identity):
    panel = history(page)
    current = panel.evaluate("node => node.matches('details') ? node.open : node.querySelector('details').open")
    if current != opened:
        before = receipt(page)["sequence"]
        panel.locator("summary").first.click()
        await_state(page, identity, after=before)
    expect(panel.get_by_role("combobox", name="Inspect a saved version", exact=True)).to_have_count(1 if opened else 0)
    return panel


def edit(page, label, value, identity, **expected):
    before = receipt(page)["sequence"]
    control = page.get_by_role("textbox", name=label, exact=True)
    assert control.input_value() != value, "The history journey must deliver an actual edit."
    control.fill(value)
    control.press("Tab")
    await_state(page, identity, after=before, **expected)
    expect(control).to_have_value(value)


def photo(number):
    image = Image.new("RGB", (420, 250), ("#e8edf4" if number == 1 else "#dbe9df"))
    ImageDraw.Draw(image).text((25, 105), f"SYNTHETIC HISTORY PHOTO {number}", fill="black")
    raw = BytesIO()
    image.save(raw, "PNG")
    return raw.getvalue()


def add_photo(page, number, identity):
    activity = page.locator(".st-key-epc_pair_monthly_activity")
    intake = activity.get_by_test_id("stExpander").filter(
        has=page.locator("summary").get_by_text("Add photos", exact=True))
    if not intake.evaluate("node => node.matches('details') ? node.open : node.querySelector('details').open"):
        intake.locator("summary").first.click()
    activity.get_by_test_id("stFileUploader").filter(
        has=page.get_by_text("Progress photos", exact=True)).locator('input[type="file"]').set_input_files(
            {"name": f"synthetic-history-photo-{number}.png", "mimeType": "image/png", "buffer": photo(number)})
    activity.get_by_role("button", name="Add these photos", exact=True).click()
    return await_state(page, identity, photos=number)


def save_version(page, identity, revision, author, activity):
    set_history(page, True, identity)
    history(page).get_by_role("button", name="Save shared version", exact=True).click()
    return await_state(page, identity, revision=revision, author=author, activity=activity)


def history_rows(page):
    grid = history(page).get_by_test_id("stDataFrame")
    expect(grid).to_have_count(1)
    expect(grid).to_be_visible()
    expect(grid.get_by_role("columnheader", name="Version", exact=True)).to_have_count(1)
    rows = grid.get_by_role("row").evaluate_all("""rows => rows.map(row=>
      [...row.querySelectorAll('[role="gridcell"]')].map(cell=>cell.textContent.trim())).filter(cells=>cells.length)""")
    assert [row[0] for row in rows] == ["3", "2", "1"], rows
    assert [row[2] for row in rows] == [AUTHOR_TWO, AUTHOR_ONE, "Synthetic QA Operator"], rows
    assert all(re.fullmatch(r"[A-Z][a-z]{2} \d{2}, \d{4} · \d{2}:\d{2} UTC", row[1]) for row in rows), rows
    actual = {item["revision"]: item["at"] for item in receipt(page)["versions"]}
    assert [row[1] for row in rows] == [datetime.fromisoformat(actual[revision].replace("Z", "+00:00"))
        .astimezone(timezone.utc).strftime("%b %d, %Y · %H:%M UTC") for revision in (3, 2, 1)]
    return rows


def inspect(page, identity, expected_images):
    before = receipt(page)["sequence"]
    panel = history(page)
    panel.get_by_role("combobox", name="Inspect a saved version", exact=True).click()
    page.get_by_role("option", name=re.compile(r"^Version 2 ·")).click()
    await_state(page, identity, after=before)
    expect(panel.get_by_text("Saved version 2 · entered editor: " + AUTHOR_ONE, exact=True)).to_be_visible()
    expect(panel.get_by_role("button", name="Continue with my draft", exact=True)).to_have_count(0)
    comparison = panel.get_by_test_id("stExpander").filter(
        has=page.locator("summary").get_by_text("Activity summary", exact=True))
    comparison.locator("summary").first.click()
    expect(comparison.get_by_text(ACTIVITY_ONE, exact=False)).to_be_visible()
    expect(comparison.get_by_text(UNSAVED, exact=False)).to_be_visible()
    pictures = panel.get_by_test_id("stExpander").filter(
        has=page.locator("summary").get_by_text("Progress photos", exact=True))
    pictures.locator("summary").first.click()
    images = pictures.locator('[data-testid="stImage"] img')
    expect(images).to_have_count(3)
    digests = []
    for image in images.all():
        image.scroll_into_view_if_needed()
        expect(image).to_be_visible()
        assert image.evaluate("async image => {await image.decode();return image.naturalWidth>0;}")
        address = urljoin(URL, image.get_attribute("src"))
        parsed = urlparse(address)
        assert parsed.hostname == "127.0.0.1" and parsed.port == PORT, "Only rendered local synthetic media may be read."
        response = page.request.get(address, max_redirects=0)
        assert response.ok
        digests.append(sha256(response.body()).hexdigest())
    assert digests == expected_images, (digests, expected_images)
    return digests


def browser_task(engine, name, base):
    token = secrets.token_hex(16)
    identity = sha256(("monthly-qa-v1:" + token).encode()).hexdigest()[:32]
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    live.ROOT = out
    live.EVIDENCE = {"synthetic_only": True, "browser": name, "events": [], "checks": {}, "artifacts": {}}
    browser = engine.launch(headless=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    context.add_cookies([{"name": "epc_device_id", "value": token, "url": URL}])
    attempts, errors = [], []
    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"data", "blob"} or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            attempts.append(parsed.hostname)
            request.abort()
    context.route("**/*", route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("pageerror", lambda error: errors.append(str(error)[:500]))
    wire = WireObservations(PORT)
    wire.attach(page)
    evidence = {"tested_checkout": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "synthetic_only": True, "observations": []}
    def capture(stage, baseline=None):
        evidence["phase"] = stage
        current = await_state(page, identity, revision=3, author=AUTHOR_TWO, activity=UNSAVED, photos=2)
        state = {key: current[key] for key in ("scope", "generation", "saved_revision", "working", "durable", "versions", "memory_assets")}
        state["storage"] = storage_state(base, token)
        assert state["storage"]["live_library_absent"], "The synthetic test must never create a live library."
        evidence["observations"].append({"stage": stage, **state})
        if baseline is not None:
            assert state == baseline, "Read-only history/display action changed report, assets, versions or standing files."
        return state
    try:
        evidence["phase"] = "cookie-bound-empty"
        page.goto(URL, wait_until="domcontentloaded")
        initial = await_state(page, identity, revision=0)
        assert initial["working"] is None
        evidence["phase"] = "load-known-fixture"
        live.load_fixture(page, "prefill")
        await_state(page, identity, revision=1)
        evidence["phase"] = "first-author-and-wording"
        edit(page, "Prepared by", AUTHOR_ONE, identity, author=AUTHOR_ONE)
        edit(page, "Activity summary", ACTIVITY_ONE, identity, activity=ACTIVITY_ONE)
        evidence["phase"] = "first-normal-photo-upload"
        first = add_photo(page, 1, identity)
        evidence["phase"] = "save-first-shared-version"
        save_version(page, identity, 2, AUTHOR_ONE, ACTIVITY_ONE)
        evidence["phase"] = "second-author-and-wording"
        edit(page, "Prepared by", AUTHOR_TWO, identity, author=AUTHOR_TWO)
        edit(page, "Activity summary", ACTIVITY_TWO, identity, activity=ACTIVITY_TWO)
        evidence["phase"] = "second-normal-photo-upload"
        second = add_photo(page, 2, identity)
        evidence["phase"] = "save-second-shared-version"
        save_version(page, identity, 3, AUTHOR_TWO, ACTIVITY_TWO)
        set_history(page, False, identity)
        evidence["phase"] = "keep-distinct-unsaved-draft"
        edit(page, "Activity summary", UNSAVED, identity, activity=UNSAVED)
        from scripts.qa_cover_photo_controls import exercise_cover_photo
        exercise_cover_photo(page, identity, base, token, evidence, receipt=receipt, await_state=await_state,
            storage_state=storage_state, url=URL, port=PORT, author=AUTHOR_TWO, activity=UNSAVED, output=out)
        baseline = capture("before-history")
        set_history(page, True, identity)
        evidence["rows"] = history_rows(page)
        expected_images = [first["working"]["photos"][0].split(".")[0],
                           *[ref.split(".")[0] for ref in second["working"]["photos"]]]
        evidence["rendered_picture_hashes"] = inspect(page, identity, expected_images)
        capture("inspect-version-and-pictures", baseline)
        page.screenshot(path=str(out / "desktop-history.png"), full_page=False)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='compact'")
        capture("narrow-history", baseline)
        page.screenshot(path=str(out / "narrow-history.png"), full_page=False)
        set_history(page, False, identity)
        capture("closed-history", baseline)
        page.set_viewport_size({"width": 1365, "height": 900})
        page.wait_for_function("() => document.querySelector('.epc-workspace')?.dataset.epcMode==='wide'")
        capture("wide-return", baseline)
        page.reload(wait_until="domcontentloaded")
        capture("reload-current-unsaved-draft", baseline)
        set_history(page, True, identity)
        assert history_rows(page) == evidence["rows"]
        inspect(page, identity, expected_images)
        capture("saved-version-still-accessible-after-reload", baseline)
        other = browser.new_context()
        other_token = secrets.token_hex(16)
        other_identity = sha256(("monthly-qa-v1:" + other_token).encode()).hexdigest()[:32]
        other.add_cookies([{"name": "epc_device_id", "value": other_token, "url": URL}])
        other.route("**/*", route)
        try:
            other_page = other.new_page()
            other_page.on("pageerror", lambda error: errors.append(str(error)[:500]))
            other_page.goto(URL, wait_until="domcontentloaded")
            isolated = await_state(other_page, other_identity, revision=0)
            assert isolated["working"] is None and isolated["versions"] == []
            expect(other_page.get_by_text("Shared report history", exact=True)).to_have_count(0)
            assert storage_state(base, token) == baseline["storage"]
        finally:
            other.close()
        expect(page.get_by_text("Monthly DOM blocked external attempts: 0", exact=True)).to_be_visible()
        assert not errors and not attempts, {"browser_errors": errors, "external_requests": attempts}
        evidence["result"] = "passed"
    except Exception as exc:
        evidence["failure"] = {"type": type(exc).__name__, "message": str(exc)[:2000]}
        try:
            evidence["first_failure_receipt"] = receipt(page)
            page.screenshot(path=str(out / "first-failure.png"), full_page=False)
        except Exception:
            pass
        raise
    finally:
        evidence.update(browser_errors=errors, external_requests=attempts)
        (out / "results.json").write_text(json.dumps(evidence, indent=2) + "\n")
        (out / "wire.json").write_text(json.dumps(wire.snapshot(), indent=2) + "\n")
        context.close()
        browser.close()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    completed = False
    with tempfile.TemporaryDirectory(prefix="monthly-history-synthetic-") as temp:
        base = Path(temp)
        (base / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
        # The controller's pure inventory uses the same explicit root guard.
        os.environ.update(EPC_DATA_DIR=temp, EPC_MONTHLY_DOM_FIXTURE="1", EPC_MONTHLY_HISTORY_TASK="1")
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
                        raise RuntimeError("Guarded history fixture stopped during startup")
                    try:
                        with urlopen(URL + "/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("Guarded history fixture did not become healthy")
                with observe(OUT / "diagnostics", Browser, BrowserContext), sync_playwright() as playwright:
                    for name, engine in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
                        try:
                            browser_task(engine, name, base)
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
                (OUT / "results.json").write_text(json.dumps({"synthetic_only": True,
                    "failures": failures, "result": "passed" if completed and not failures else "failed"}, indent=2) + "\n")
    if failures:
        raise AssertionError("Shared-history browser task failed: " + "; ".join(failures))


if __name__ == "__main__":
    main()
