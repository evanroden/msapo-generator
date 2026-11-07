"""Observation-only hosted X11 and AT-SPI diagnostic. Never confirms the native Save dialog.

This is NOT directory-retention acceptance. The unmodified local journey stops
at its first CSV export, after read-only desktop evidence on an owned Xvfb.
It never supplies a destination, saves a directory, or substitutes picker APIs.
"""
from __future__ import annotations

from hashlib import file_digest, sha256
from io import BytesIO
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_directory_retention_local as local
from scripts.qa_directory_retention_local import (CANARY, GUARD_LOG, MARKER, PREFIX,
    ORIGIN, LocalConfig, Server, SafetyStop, allowed_url, child_environment,
    final_isolation_failure, guarded_root, live)

OUT = ROOT / "test-artifacts/directory-retention-atspi-observation"
SCREEN = (1600, 1200)
AUTHORITY = ".owned-xauthority"
BROWSER_MANIFEST = ".pinned-chromium.json"


class ObservationComplete(Exception):
    """Intentional stop before directory confirmation/save, not acceptance."""


from scripts import qa_directory_retention_headed as headed
from scripts.qa_directory_retention_headed import (browser_identity,
    resolve_pinned_browser, verified_browser, desktop_measurement)
from scripts import qa_directory_retention_atspi_bus as bus


def display_environment(base, commit):
    return bus.accessibility_environment(base, commit)


class HeadedJourney(headed.HeadedJourney):
    def capture_desktop(self, stage):
        super().capture_desktop(stage)
        if stage != "settled-after-click":
            return
        self.guard()
        env = display_environment(self.base, self.config.commit)
        before = self.desktop_observations[-1]
        owner = bus.dialog_owner(before, verified_browser(self.base)["path"])
        # Helper observes only the verified PID and only its unique native dialog.
        try:
            data = bus.capture_accessibility(env, owner)
        except bus.AccessibilityDiagnosticFailure as exc:
            after, _ = desktop_measurement(env)
            if bus.dialog_owner(after, verified_browser(self.base)["path"]) != owner:
                raise SafetyStop("Native dialog ownership changed during failed accessibility read")
            self.guard()
            if hasattr(exc, "topology"):
                before["accessibility_failure_topology"] = exc.topology
                before["owned_dialog"] = owner
            raise  # Diagnostic preservation never converts failure into success.
        after, _ = desktop_measurement(env)
        if bus.dialog_owner(after, verified_browser(self.base)["path"]) != owner:
            raise SafetyStop("Native dialog ownership changed during accessibility read")
        self.guard()
        before["accessibility"] = data
        before["owned_dialog"] = owner


def observe_owned_display():
    base = guarded_root(os.environ.get("EPC_DATA_DIR", ""))
    env = display_environment(base, os.environ.get("APP_GIT_COMMIT", ""))
    binary = verified_browser(base)
    from playwright.sync_api import sync_playwright
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if (OUT / "receipt.json").exists():
        raise SafetyStop("Never overwrite first-attempt evidence")
    record = {"result": "not completed", "synthetic_only": True, "origin": ORIGIN,
              "actual_entrypoint": "run_web.py", "commit": commit,
              "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
              "harness_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "production_harness_sha256": sha256(Path(live.__file__).read_bytes()).hexdigest(),
              "tracked_modifications": subprocess.check_output(
                  ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).splitlines(),
              "worktree_diff_sha256": sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
              "browser_distribution": "Playwright pinned Chromium headed",
              "browser_executable": binary,
              "browser_registry_lookup": "playwright.chromium.executable_path before HOME isolation",
              "directory_acceptance": False, "native_dialog_confirmed": False,
              "limits": ["AT-SPI accessibility bridge and --force-renderer-accessibility change environment and timing; not acceptance parity.",
                         "Observation only; no dialog approval, file validation or directory save.",
                         "Headed Xvfb and observation change timing; this does not explain headless behavior."],
              "production_acceptance": False, "inherited_limits": [
                  "Loopback HTTP secure context, not Render HTTPS/deployment/network behavior.",
                  "Python socket audit and browser route guards, not an OS outbound sandbox.",
                  "No elapsed 30-day or aged hosted deletion claim.",
                  "Single worksheet; no automatic inactive-row filtering claim.",
                  "Read-only CSV observations affect timing; success cannot alone explain an earlier failure.",
                  "Overflow clipping is a rectangular estimate; transforms and nonrectangular clipping require separate hit-test evidence.",
                  "Geometry is sampled around native operations, not each internal click retry. Hit tests use the geometric center, not a recorded Playwright click point."]}
    nonce, token = (base / MARKER).read_text(), secrets.token_hex(16)
    config, raw = LocalConfig(commit, nonce), live.workbook()
    record["source_sha256"] = sha256(raw).hexdigest()
    record["source_bytes"] = len(raw)
    server = Server(base, OUT, commit)
    journey = browser = context = page = None
    blocked, errors = [], []
    try:
        server.start()
        with sync_playwright() as playwright:
            if verified_browser(base) != binary:
                raise SafetyStop("Pinned browser identity changed before launch")
            browser = playwright.chromium.launch(headless=False, env=env, executable_path=binary["path"],
                args=["--force-renderer-accessibility"])
            record["browser_version"] = browser.version
            context = browser.new_context(accept_downloads=True, service_workers="block",
                                          viewport={"width": 1440, "height": 1000})
            if context.cookies():
                raise SafetyStop("Fresh local browser context contains cookies")
            context.add_cookies([{"name": "epc_device_id", "value": token, "url": ORIGIN, "sameSite": "Lax"}])
            page = context.new_page()
            page.set_default_timeout(30000)
            journey = HeadedJourney(page, context, token, config, OUT, base, server, raw)
            if journey.namespace.exists():
                raise SafetyStop("New browser namespace was not initially empty")
            journey.blocked = blocked
            def route(route):
                if allowed_url(route.request.url, journey.kind,
                        top_level=route.request.is_navigation_request() and route.request.frame.parent_frame is None):
                    route.continue_()
                else:
                    blocked.append("Unexpected HTTP origin or top-level route")
                    route.abort()
            def websocket(route):
                if allowed_url(route.url, journey.kind, websocket=True):
                    route.connect_to_server()
                else:
                    blocked.append("Unexpected websocket")
                    route.close()
            context.route("**/*", route)
            context.route_web_socket("**/*", websocket)
            page.on("pageerror", lambda exc: errors.append(type(exc).__name__))
            # Observe capabilities without replacing picker, downloads, or JS APIs.
            page.on("domcontentloaded", lambda: record.update(browser_capabilities=page.evaluate(
                "() => ({secureContext: isSecureContext, savePicker: typeof showSaveFilePicker, userAgent: navigator.userAgent})")))
            try:
                journey.run(raw, "Synthetic Retention 291 " + secrets.token_hex(5))
                raise SafetyStop("Observation did not stop before directory save")
            except headed.ObservationComplete:
                journey.guard()
                if errors or journey.storage_receipts:
                    raise SafetyStop("Observation had errors or unexpectedly saved directory history")
                record["result"] = "observation captured; dialog presence requires image review"
            except Exception as exc:
                record["failure_type"] = type(exc).__name__
                record["failure"] = str(exc)
                # Only capture a verified synthetic page, never a drifted target.
                try:
                    journey.snapshot("first-failure")
                except Exception:
                    pass
                raise
            finally:
                context.close()
                browser.close()
    except Exception as exc:
        record["result"] = "failed"
        record.setdefault("failure_type", type(exc).__name__)
        record.setdefault("failure", str(exc))
        raise
    finally:
        was_observed = record["result"].startswith("observation captured")
        server.stop()
        record["events"] = journey.events if journey else []
        record["storage_receipts"] = journey.storage_receipts if journey else []
        record["csv_diagnostics"] = journey.csv_diagnostics if journey else []
        record["desktop_observations"] = journey.desktop_observations if journey else []
        record["blocked_requests"] = blocked
        record["page_errors"] = errors
        try:
            record["server_guard"] = (base / GUARD_LOG).read_text().splitlines()
        except OSError:
            record["server_guard"] = ["Guard log became unreadable"]
        try:
            record["ordinary_canary_unchanged"] = (base / "ordinary-canary").read_bytes() == CANARY
        except OSError:
            record["ordinary_canary_unchanged"] = False
        failed = final_isolation_failure(record)
        (OUT / "receipt.json").write_text(json.dumps(record, indent=2))
        if was_observed and failed:
            raise SafetyStop("Final observation isolation checks failed after shutdown")


def launch():
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
            or os.environ.get("GITHUB_REPOSITORY") != "evanroden/msapo-generator"):
        raise SafetyStop("This observation launcher requires the hosted PR workflow")
    for command in ("xvfb-run", "Xvfb", "xauth", "xwininfo", "xprop", "dbus-daemon", "dbus-run-session"):
        if shutil.which(command) is None:
            raise SafetyStop("Required owned-display tool is missing: " + command)
    from PIL import features
    if not features.check_feature("xcb"):
        raise SafetyStop("Pillow X11 capture support is required")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    binary = resolve_pinned_browser()
    OUT.mkdir(parents=True, exist_ok=False)
    result = {"result": "not completed", "observation_only": True, "production_acceptance": False}
    with tempfile.TemporaryDirectory(prefix=PREFIX) as temp:
        base = Path(temp)
        (base / MARKER).write_text(secrets.token_hex(16))
        (base / GUARD_LOG).write_text("")
        (base / "ordinary-canary").write_bytes(CANARY)
        (base / BROWSER_MANIFEST).write_text(json.dumps({
            "root_nonce": (base / MARKER).read_text(), "browser": binary}))
        bus_config = bus.prepare_bus(base)
        authority = base / AUTHORITY
        authority.touch(mode=0o600, exist_ok=False)
        env = bus.launch_environment(base, commit)  # Never inherit desktop/session state.
        process = None
        try:
            process = subprocess.Popen(["xvfb-run", "--auto-servernum", "--auth-file", str(authority),
                "--server-args", "-screen 0 1600x1200x24 -nolisten tcp",
                "dbus-run-session", "--config-file=" + str(bus_config), "--",
                sys.executable, str(Path(__file__).resolve()), "--observe-owned-display"],
                cwd=base, env=env, start_new_session=True)
            code = process.wait(timeout=240)
            result.update(returncode=code, result="child completed" if code == 0 else "child failed")
            if code:
                raise SafetyStop("Owned headed observation failed; inspect its preserved receipt")
        except Exception as exc:
            result.update(result="failed", failure_type=type(exc).__name__, failure=str(exc))
            raise
        finally:
            if process is not None:
                # Kill only this launcher's new process group, including Xvfb.
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(process.pid, sig)
                    except ProcessLookupError:
                        break
                    if sig == signal.SIGTERM:
                        time.sleep(.2)
                process.wait(timeout=5)
            (OUT / "launcher.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    if not sys.argv[1:]:
        launch()
    elif sys.argv[1:] == ["--observe-owned-display"]:
        observe_owned_display()
    else:
        raise SystemExit("No target, display, data root or dialog action arguments are supported")
