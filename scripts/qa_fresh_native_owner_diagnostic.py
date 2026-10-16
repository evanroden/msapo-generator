"""One planned WebKit owner discriminator; never a retry or acceptance repair.

The normal Fresh script is unchanged. This separate process reuses all of its
native actions, durable/source assertions and strict native error checks. Only
the expected derivative-asset observation and artifact destination differ.
"""
from __future__ import annotations

from contextlib import contextmanager
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

from scripts import qa_water_fresh_page_journey as fresh
from scripts.qa_native_owner_assets import build_copy, expected_assets, SINK

OUT = ROOT / "test-artifacts/fresh-native-owner-diagnostic"
REQUEST = "[native-owner-diagnostic-once]"


def requested_once(event_name, attempt, event, message):
    """One deliberate PR249 publication; later heads/main/reruns do not opt in."""
    head = event.get("pull_request", {}).get("head", {}).get("sha", "")
    return (event_name == "pull_request" and str(attempt) == "1" and event.get("number") == 249
            and isinstance(head, str) and re.fullmatch(r"[0-9a-f]{40}", head) is not None
            and REQUEST in message.splitlines())


def emit_gate():
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    head = event.get("pull_request", {}).get("head", {}).get("sha", "")
    message = ""
    if (os.environ.get("GITHUB_EVENT_NAME") == "pull_request" and event.get("number") == 249
            and os.environ.get("GITHUB_RUN_ATTEMPT") == "1" and isinstance(head, str)
            and re.fullmatch(r"[0-9a-f]{40}", head)):
        # Checkout depth2 retains the tested merge's two exact parent commits.
        message = subprocess.check_output(["git", "show", "--no-patch", "--format=%B", head],
                                          cwd=ROOT, text=True)
    enabled = requested_once(os.environ.get("GITHUB_EVENT_NAME"), os.environ.get("GITHUB_RUN_ATTEMPT"), event, message)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write("enabled=" + str(enabled).lower() + "\n")


class DerivativeDelivery:
    """Natural first responses, checked against independently derived bytes."""
    def __init__(self, manifest):
        self.expected = manifest["assets"]
        self.receipts = {name: [] for name in self.expected}

    def observe(self, response):
        parsed = urlparse(response.url)
        name = Path(parsed.path).name
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 8529
                or parsed.path != "/static/js/" + name or name not in self.receipts
                or self.receipts[name]):
            return
        rows = self.receipts[name]
        rows.append({"matches": False, "error": "first derivative response incomplete"})
        try:
            raw = response.body()
            expected = self.expected[name]
            rows[0] = {"entry": name, "status": response.status, "bytes": len(raw),
                       "sha256": sha256(raw).hexdigest(), "expected_sha256": expected["sha256"],
                       "matches": response.status == 200 and len(raw) == expected["bytes"]
                       and sha256(raw).hexdigest() == expected["sha256"]}
        except Exception as exc:
            rows[0] = {"matches": False, "error": type(exc).__name__ + ": " + str(exc)[:300]}

    def require(self):
        for name, rows in self.receipts.items():
            assert len(rows) == 1 and rows[0].get("matches"), "Missing or wrong first diagnostic derivative: " + name


def capture_owners(page, record, stage):
    item = {"stage": stage}
    try:
        item["evidence"] = page.evaluate("() => globalThis." + SINK + "?.state || null")
    except Exception as exc:
        item["capture_error"] = type(exc).__name__ + ": " + str(exc)[:500]
    rows = record.setdefault("native_owner_observations", [])
    if len(rows) < 2:
        rows.append(item)
    else:
        item["capture_overflow"] = True
        rows[-1] = item


def require_owners(record):
    rows = record.get("native_owner_observations", [])
    assert rows and len(rows) <= 2 and rows[-1]["stage"] == "final", "Missing final native owner observation"
    assert all(not row.get("capture_error") and not row.get("capture_overflow") for row in rows), "Native owner capture failed"
    value = rows[-1].get("evidence")
    assert isinstance(value, dict) and value.get("schema") == "enfra-native-owner-observation-v1", "Missing diagnostic sink"
    assert value.get("origin") == "http://127.0.0.1:8529" and value.get("installed") is True, "Wrong diagnostic origin/installation"
    assert value.get("registrationLimit") == 64 and value.get("callbackLimit") == 512, "Unexpected diagnostic limits"
    assert not value.get("diagnosticErrors"), "Diagnostic sink failed"
    assert len(value.get("registrations", [])) <= 64 and len(value.get("callbacks", [])) <= 512, "Unbounded diagnostic buffers"
    # An overflow is retained as an explicit limit on attribution, not hidden by
    # a larger buffer or another attempt. The original strict error still wins.
    assert not value.get("droppedRegistrations") and not value.get("droppedTargets"), "Observer/target limit prevents complete attribution"
    owners = {item.get("owner") for item in value["registrations"]}
    assert {"aria-combobox-input-width", "floating-auto-update"} <= owners, "Required reachable owners were not registered"
    by_id = {item.get("observer"): item.get("owner") for item in value["registrations"]}
    delivered = {by_id.get(item.get("observer")) for item in value["callbacks"] if item.get("phase") == "start"}
    assert {"aria-combobox-input-width", "floating-auto-update"} <= delivered, "Required owners had no captured native delivery"
    record["owner_classes_registered"] = sorted(owners)
    record["popover_trigger_width_registration"] = ("registered" if "aria-popover-trigger-width" in owners
                                                     else "not registered in bounded capture")
    record["attribution_limit"] = ("Callback/target correlation only. Native loop errors can follow callback exit or skipped "
                                   "notifications; a last callback is not causal attribution. Primary native owners are not annotated.")


@contextmanager
def diagnostic_journey(manifest, output):
    """Adapt only evidence dependencies in this standalone diagnostic process."""
    original = (fresh.OUT, fresh.observe_frontend_delivery, fresh.require_frontend_delivery,
                fresh.capture_native_window_errors)
    delivery = DerivativeDelivery(manifest)
    def observe(page, record, *, static_dir=None):
        assert static_dir is None
        sink = (ROOT / "scripts/qa_native_owner_sink.js").read_bytes()
        assert sha256(sink).hexdigest() == manifest["sink_sha256"], "Diagnostic sink differs from its intended manifest"
        page.add_init_script(sink.decode("utf-8"))
        record["diagnostic_sink_sha256"] = manifest["sink_sha256"]
        page.on("response", delivery.observe)
        record["diagnostic_derivative_delivery"] = delivery.receipts
    def require(record):
        delivery.require()
    def capture(page, record, stage):
        result = original[3](page, record, stage)
        capture_owners(page, record, stage)
        return result
    try:
        fresh.OUT, fresh.observe_frontend_delivery, fresh.require_frontend_delivery = output, observe, require
        fresh.capture_native_window_errors = capture
        yield delivery
    finally:
        (fresh.OUT, fresh.observe_frontend_delivery, fresh.require_frontend_delivery,
         fresh.capture_native_window_errors) = original


def main():
    import streamlit
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    record = {"diagnostic_only": True, "acceptance": False, "attempt_count": 1,
              "claim": "Owner correlation, not an application repair or causal attribution",
              "timing_limit": "Bounded logging adds CPU overhead. No added scheduling/layout/action/wait; a single nonreproduction proves no repair."}
    static_source = Path(streamlit.__file__).parent / "static"
    before, _ = expected_assets(static_source)
    failures = []
    with tempfile.TemporaryDirectory(prefix="fresh-native-owner-") as temporary:
        owned = Path(temporary)
        data, copied = owned / "data", owned / "static"
        data.mkdir()
        (data / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
        manifest = build_copy(static_source, copied)
        manifest_path = owned / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        (OUT / "diagnostic-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        artifact_assets = OUT / "annotated-assets"
        artifact_assets.mkdir(exist_ok=True)
        for name, row in manifest["assets"].items():
            if row["annotated"]:
                (artifact_assets / name).write_bytes((copied / "static/js" / name).read_bytes())
        record["server_scope"] = {"data": str(data), "static": str(copied), "installed_static": str(static_source),
                                   "bootstrap": "separate subprocess; temporary copy only; no live/static fallback"}
        env = {**os.environ, "EPC_DATA_DIR": str(data), "EPC_MONTHLY_DOM_FIXTURE": "1",
               "EPC_MONTHLY_FRESH_TASK": "1", "SMARTSHEET_API_MODE": "disabled", "ANTHROPIC_API_KEY": "test-key-not-used"}
        with (OUT / "playwright-webkit-streamlit.log").open("w") as log:
            process = subprocess.Popen([sys.executable, "scripts/qa_native_owner_server.py", "--static-dir", str(copied),
                                        "--manifest", str(manifest_path)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            record["server_scope"]["pid"] = process.pid
            try:
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError("Native owner diagnostic server stopped")
                    try:
                        with urlopen("http://127.0.0.1:8529/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Native owner diagnostic server did not start")
                with diagnostic_journey(manifest, OUT) as delivery:
                    with sync_playwright() as playwright:
                        browser = playwright.webkit.launch(headless=True)
                        try:
                            fresh.exercise(browser, "playwright-webkit", data, record)
                        finally:
                            browser.close()
                    delivery.require()
            except Exception as exc:
                failures.append({"kind": "unchanged-fresh-journey", "type": type(exc).__name__, "error": str(exc)[:2000]})
            finally:
                cleanup = fresh.stop_server(process, record)
                record["server_scope"]["exit_code"] = process.poll()
                if cleanup:
                    failures.append({"kind": "diagnostic-server-cleanup", "error": cleanup})
                try:
                    after, _ = expected_assets(static_source)
                    assert before == after, "Installed ordinary assets changed during the diagnostic"
                    record["installed_static_unchanged"] = True
                    require_owners(record)
                except Exception as exc:
                    failures.append({"kind": "diagnostic-evidence", "type": type(exc).__name__, "error": str(exc)[:2000]})
    record["reused_fresh_result"] = record.pop("result", "not completed")
    record["diagnostic_result"] = "failed or inconclusive" if failures else "one diagnostic journey complete; no acceptance claim"
    record["failures"] = failures
    (OUT / "results.json").write_text(json.dumps(record, indent=2) + "\n")
    if failures:
        raise AssertionError("Native owner diagnostic retained failures: " + json.dumps(failures))
    print("Completed one diagnostic-only WebKit journey; no repair or acceptance claim")


if __name__ == "__main__":
    if sys.argv[1:] == ["--emit-gate"]:
        emit_gate()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("Use no arguments for the one diagnostic, or --emit-gate for CI selection")
