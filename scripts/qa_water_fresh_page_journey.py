"""Fresh optional Water placeholder through the real ordinary Monthly UI.

Run only in CI's independently permitted synthetic browser harness. Each engine
gets an empty, marked EPC_DATA_DIR and a guarded process. Ordinary native actions
create an empty October design, then open unsaved September: no snapshot/import
is hydrated into that month. No browser or server state is injected. The existing
known-value Water journey still owns its complete caption/order/mobile/export tail.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymupdf
from app.contracts import RRH_CONTRACT as CONTRACT
from scripts.workspace_water_observations import water_state

OUT = ROOT / "test-artifacts" / "water-fresh-page-journey"
PORT = 8529
URL = f"http://127.0.0.1:{PORT}/?workflow=monthly"
WATER = ".st-key-epc_pair_monthly_water"
FIRST = "United Memorial Medical Center"
ACTOR = "Synthetic Fresh Water Reviewer"
NAME = "TEST ONLY invented fresh Water first-page review.pdf"


def source_pdf():
    with pymupdf.open() as pdf:
        for number in (1, 2):
            page = pdf.new_page()
            page.insert_text((45, 65), "TEST ONLY - ALL RECORDS INVENTED", fontsize=18)
            page.insert_text((45, 110), "Water treatment")
            page.insert_text((45, 140), "Facility: " + FIRST)
            page.insert_text((45, 170), "Service date: 2026-09-17")
            page.insert_text((45, 200), "Vendor: Synthetic Chemical Vendor")
            page.insert_text((45, 240), f"Synthetic page {number}: conductivity inspected.")
            page.insert_text((45, 275), "Follow-up sample remains pending.")
        return pdf.tobytes()


def durable_receipt(base):
    """Read an acknowledged ordinary journal; never write or seed app state."""
    from app.monthly_report_library import draft_from_dict
    journals = list((Path(base) / "monthly_reports" / "active_work").glob("**/2026-09/working.json"))
    if not journals:
        return None
    assert len(journals) == 1, "The fresh task must have one September browser journal"
    value = json.loads(journals[0].read_bytes())
    assert value["kind"] == "browser_active_work_v1"
    draft = draft_from_dict(value["draft"])
    assert draft.period.key == "2026-09" and draft.profile.contract == CONTRACT
    assert len(draft.profile.facilities) == 1 and draft.profile.facilities[0].title == FIRST
    assert draft.prepared_by == ACTOR
    assert value["fingerprint"] == draft.fingerprint
    block = next(b for b in draft.blocks if b.key == "water_reports")
    state = water_state(draft)
    originals = []
    for source in draft.sources:
        assert source.classification == "Water treatment"
        paths = list((Path(base) / "monthly_reports" / "library").glob(
            "**/sources/" + source.sha256 + source.suffix))
        assert len(paths) == 1
        raw = paths[0].read_bytes()
        assert sha256(raw).hexdigest() == source.sha256, "A retained synthetic original failed its digest"
        originals.append({"id": source.id, "size": len(raw), "sha256": sha256(raw).hexdigest()})
    return {"state": state, "water_source": block.source,
            "water_fingerprint": block.fingerprint, "draft_fingerprint": draft.fingerprint,
            "period": draft.period.key, "revision": value["revision"],
            "originals": originals, "base_snapshot_revision": value["base_snapshot_revision"]}


def wait_durable(page, base, order, *, source=None, reviewed=None, excluded=None):
    deadline = time.monotonic() + 45
    last = None
    while time.monotonic() < deadline:
        last = durable_receipt(base)
        if last:
            state = last["state"]
            numbers = [p["source_pages"][0][1] if len(p["source_pages"]) == 1 else None
                       for p in state["pages"]]
            ready = (numbers == order and (source is None or last["water_source"] == source)
                     and not state["pending"])
            if reviewed is not None:
                ready = ready and len(state["sources"]) == 1 and state["sources"][0]["reviewed"] == reviewed
            if excluded is not None:
                ready = ready and len(state["sources"]) == 1 and state["sources"][0]["excluded"] == excluded
            if ready and page.locator('[data-testid="stApp"]').get_attribute("data-test-script-state") == "notRunning":
                return last
        page.wait_for_timeout(100)
    raise AssertionError("Fresh Water durable state did not match the explicit page decisions: " + json.dumps(last))


def select(page, name, value):
    from playwright.sync_api import expect
    control = page.get_by_role("combobox", name=name, exact=True)
    control.click()
    page.get_by_role("option", name=value, exact=True).click()
    expect(control).to_have_value(value)


def exercise(browser, name, base, record):
    from playwright.sync_api import expect
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    tracing = False
    try:
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        tracing = True
    except Exception as exc:
        record["trace_start_error"] = str(exc)[:500]
    page = context.new_page()
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        parsed = urlparse(request.request.url)
        if parsed.scheme in {"blob", "data"} or parsed.hostname == "127.0.0.1" and parsed.port == PORT:
            request.continue_()
        else:
            external.append({"host": parsed.hostname, "type": request.request.resource_type})
            request.abort()
    page.route("**/*", route)
    record.update({"engine": name, "browser_errors": errors, "external_requests": external,
                   "steps": [], "storage": "new disposable root per engine",
                   "native_output": "not requested; existing full Water journey unchanged"})

    def capture(stage, receipt=None):
        record["steps"].append({"stage": stage, "receipt": receipt})
        page.screenshot(path=str(out / (stage + ".png")), full_page=False)
        (out / "task.json").write_text(json.dumps(record, indent=2))

    try:
        record["phase"] = "zero selected sites"
        assert not list(Path(base).glob("monthly_reports/library/**/manifest.json"))
        page.goto(URL, wait_until="domcontentloaded")
        page.get_by_role("button", name=CONTRACT, exact=True).click()
        site = page.get_by_role("checkbox", name=FIRST, exact=True)
        expect(site).not_to_be_checked()
        expect(page.get_by_text("Select at least one site to continue.", exact=True)).to_be_visible()
        capture("zero-sites")
        site.locator("xpath=ancestor::label[1]").click()
        expect(site).to_be_checked(timeout=45000)
        expect(page.locator(".st-key-monthly_report_identity_sites")).to_have_text("Site: " + FIRST, timeout=45000)
        capture("one-native-site-action")

        record["phase"] = "ordinary empty design then unsaved earlier month"
        select(page, "Reporting month", "October")
        select(page, "Reporting year", "2026")
        page.get_by_role("button", name="Use ENFRA template", exact=True).click()
        actor = page.get_by_role("textbox", name="Your name", exact=True)
        actor.fill(ACTOR)
        actor.press("Tab")
        page.get_by_role("button", name="Start this report", exact=True).click()
        expect(page.locator(WATER)).to_be_attached(timeout=45000)
        select(page, "Reporting month", "September")
        prepared = page.get_by_role("textbox", name="Prepared by", exact=True)
        prepared.fill(ACTOR)
        prepared.press("Tab")
        initial = wait_durable(page, base, [], source="Omit")
        from app.monthly_report_model import ResolvedBlock
        assert initial["water_fingerprint"] == ResolvedBlock("water_reports", "Omit").fingerprint
        assert initial["originals"] == [] and initial["state"]["sources"] == []
        assert initial["base_snapshot_revision"] == 0
        assert not list(Path(base).glob("monthly_reports/snapshots/**/2026-09.json"))
        manifests = list(Path(base).glob("monthly_reports/library/**/manifest.json"))
        assert len(manifests) == 1
        design = json.loads(manifests[0].read_bytes())
        assert design["revision"] == 1 and design["bootstrap"]["period"] == {"year": 2026, "month": 10}
        for standing in ("directory", "capacity", "training"):
            assert not list((Path(base) / "monthly_reports" / standing).glob("**/manifest.json"))
        baseline = initial["state"]["unrelated_sha256"]
        capture("fresh-empty-omitted-water", initial)

        record["phase"] = "native binary upload and first-page review"
        raw = source_pdf()
        digest = sha256(raw).hexdigest()
        (out / "unchanged-synthetic-source.pdf").write_bytes(raw)
        record["source"] = {"size": len(raw), "sha256": digest}
        water = page.locator(WATER)
        water.get_by_role("button", name="Add files", exact=True).click()
        uploader = page.locator('[data-testid="stFileUploader"]').filter(
            has=page.get_by_text("Water-treatment files", exact=True))
        uploader.locator('input[type="file"]').set_input_files(
            {"name": NAME, "mimeType": "application/pdf", "buffer": raw})
        expect(water.get_by_text("Reviewing " + NAME, exact=True)).to_be_visible(timeout=45000)
        include = water.get_by_role("button", name="Include page and continue", exact=True)
        expect(include).to_be_enabled()
        include.click()
        expect(water.get_by_role("combobox", name="Page to review", exact=True)).to_have_value(re.compile(r"^Page 2(?: ·|$)"))
        first = wait_durable(page, base, [], source="Omit", reviewed=[1])
        assert first["water_fingerprint"] == initial["water_fingerprint"]
        assert first["state"]["unrelated_sha256"] == baseline
        assert first["originals"] == [{"id": digest, "size": len(raw), "sha256": digest}]
        capture("first-page-approved-nothing-included-yet", first)

        record["phase"] = "explicit page-two exclusion then atomic one-page inclusion"
        water.get_by_role("button", name="Leave page out and continue", exact=True).click()
        final = wait_durable(page, base, [1], reviewed=[1], excluded=[2])
        assert final["water_source"] != "Omit"
        assert final["state"]["sources"][0]["selected"] == [1]
        assert final["state"]["unrelated_sha256"] == baseline
        assert final["originals"] == first["originals"]
        expect(water.get_by_text("Report pages (1)", exact=True)).to_be_visible(timeout=45000)
        expect(water.get_by_role("button", name="Add reviewed pages", exact=True)).to_have_count(0)
        capture("canonical-one-page-only", final)
        expect(page.get_by_text("Fresh Monthly blocked external attempts: 0", exact=True)).to_have_count(1)
        assert not errors and not external
        record["result"] = "pass"
    except Exception as exc:
        record.update({"result": "fail", "error_type": type(exc).__name__, "error": str(exc)[:2000]})
        try:
            page.screenshot(path=str(out / "first-failure.png"), full_page=False)
        except Exception:
            pass
        raise
    finally:
        if tracing:
            try:
                context.tracing.stop(path=str(out / "trace.zip"))
            except Exception as exc:
                record["trace_stop_error"] = str(exc)[:500]
        (out / "task.json").write_text(json.dumps(record, indent=2))
        context.close()


def stop_server(process, record):
    """Bound cleanup independently; never replace the first task failure."""
    errors = []
    try:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        errors.append("Synthetic server did not terminate within 15 seconds")
        try:
            process.kill()
            process.wait(timeout=5)
        except Exception as exc:
            errors.append(type(exc).__name__ + ": " + str(exc)[:500])
    except Exception as exc:
        errors.append(type(exc).__name__ + ": " + str(exc)[:500])
    if errors:
        record["cleanup_errors"] = errors
    return errors


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"synthetic": True, "ordinary_route": True, "physical_device": False,
              "checks": [], "failures": []}
    with sync_playwright() as playwright:
        for name, browser_type in (("chromium", playwright.chromium), ("playwright-webkit", playwright.webkit)):
            record = {"engine": name}
            result["checks"].append(record)
            with tempfile.TemporaryDirectory(prefix="monthly-fresh-water-") as directory:
                base = Path(directory)
                (base / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1", encoding="ascii")
                env = {**os.environ, "EPC_DATA_DIR": directory, "EPC_MONTHLY_DOM_FIXTURE": "1",
                       "EPC_MONTHLY_FRESH_TASK": "1", "SMARTSHEET_API_MODE": "disabled",
                       "ANTHROPIC_API_KEY": "test-key-not-used"}
                with (OUT / (name + "-streamlit.log")).open("w") as log:
                    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run",
                        "tests/fixtures/workspaces/monthly_fresh_app.py", "--server.address", "127.0.0.1",
                        "--server.port", str(PORT), "--server.headless", "true", "--browser.gatherUsageStats", "false"],
                        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                    try:
                        for _ in range(150):
                            if process.poll() is not None:
                                raise RuntimeError("Fresh ordinary Monthly server stopped")
                            try:
                                with urlopen(f"http://127.0.0.1:{PORT}/_stcore/health", timeout=1) as status:
                                    if status.status == 200:
                                        break
                            except OSError:
                                pass
                            time.sleep(.1)
                        else:
                            raise RuntimeError("Fresh ordinary Monthly server did not start")
                        browser = browser_type.launch(headless=True)
                        try:
                            exercise(browser, name, base, record)
                        finally:
                            browser.close()
                    except Exception as exc:
                        record.setdefault("result", "fail")
                        record.setdefault("error", str(exc)[:2000])
                        result["failures"].append({"engine": name, "phase": record.get("phase", "server startup"),
                                                   "error": record["error"]})
                    finally:
                        cleanup = stop_server(process, record)
                        if cleanup and record.get("result") != "fail":
                            record.update(result="fail", error_type="ServerCleanupError", error="; ".join(cleanup))
                            result["failures"].append({"engine": name, "phase": "server shutdown",
                                                       "error": record["error"]})
    (OUT / "results.json").write_text(json.dumps(result, indent=2))
    if result["failures"]:
        raise AssertionError("Fresh ordinary Water page task failed: " + json.dumps(result["failures"]))
    print("PASS two ordinary native fresh-Water tasks; first page approved, second excluded, one canonical page")


if __name__ == "__main__":
    main()
