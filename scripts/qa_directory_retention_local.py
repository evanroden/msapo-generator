"""Loopback-only preflight for #291. Never accepts a remote target or data root.

The production harness and its gates are unchanged. This companion reuses its
native controls/CSV assertions and mirrors only route-dependent orchestration.
A marked temporary root, scrubbed child environment, owned-server nonce,
loopback network gates and fresh cookie are mandatory. No picker shim is used.
A local result is not served-production or 30-day elapsed-time acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_directory_retention_live as live
from scripts.qa_directory_retention_live import (ACTOR, SHEET, CONFIRM, IMPORT_DISCLOSURE,
                                                 STORAGE_DISCLOSURE, SafetyStop, verify_contacts)

ORIGIN = "http://127.0.0.1:8529"
OUT = ROOT / "test-artifacts/directory-retention-local"
MARKER = ".directory-retention-local"
GUARD_LOG = "network-guard.jsonl"
CANARY = b"Synthetic ordinary-root canary: preserve unchanged"
PREFIX = "directory-retention-synthetic-"


def guarded_root(value):
    base = Path(value)
    if (not base.is_absolute() or base.is_symlink() or base.resolve() != base
            or base.parent != Path(tempfile.gettempdir()).resolve()
            or not base.name.startswith(PREFIX)):
        raise SafetyStop("Local preflight requires its own disposable root")
    marker = base / MARKER
    if marker.is_symlink() or not marker.is_file() or not re.fullmatch(r"[0-9a-f]{32}", marker.read_text()):
        raise SafetyStop("Local preflight root marker is missing or invalid")
    return base


def require_clean_configuration():
    for path in (ROOT / ".env", ROOT / ".streamlit/secrets.toml"):
        if path.exists() or path.is_symlink():
            raise SafetyStop("Local preflight refuses repository credential configuration")


def child_environment(base, commit):
    require_clean_configuration()
    base = guarded_root(base)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SafetyStop("A real checkout commit is required")
    home = base / "home"
    home.mkdir(exist_ok=True)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT") if key in os.environ}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), XDG_CACHE_HOME=str(home / "cache"),
               XDG_DATA_HOME=str(home / "data"), EPC_DATA_DIR=str(base),
               APP_GIT_COMMIT=commit, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
               ANTHROPIC_API_KEY="", OPENAI_API_KEY="", SMARTSHEET_API_MODE="disabled")
    return env


def loopback_host(host):
    if host in {None, "localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        return False


def install_outbound_guard(base):
    base = guarded_root(base)
    def audit(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo"}:
            return
        address = args[1] if event == "socket.connect" else args[0]
        host = address[0] if isinstance(address, tuple) else address
        if not loopback_host(host):
            with (base / GUARD_LOG).open("a") as stream:
                stream.write(json.dumps({"blocked": event + ":non-loopback"}) + "\n")
            raise SafetyStop("Local preflight blocked non-loopback server traffic")
    sys.addaudithook(audit)


def validate_route(url, kind):
    parsed = urlsplit(url)
    if (kind not in {"directory", "storage"} or parsed.scheme != "http"
            or parsed.netloc != "127.0.0.1:8529" or parsed.path not in {"", "/"}
            or parsed.fragment or parse_qs(parsed.query, keep_blank_values=True) != {
                "workflow": ["monthly"], "monthly_qa": ["isolated"], "monthly_admin": [kind]}):
        raise SafetyStop("Local preflight left its exact isolated loopback route")


def allowed_url(value, kind, *, top_level=False, websocket=False):
    try:
        if value.startswith("blob:") and not websocket and not top_level:
            target = urlsplit(value[5:])
            return (target.scheme == "http" and target.netloc == "127.0.0.1:8529"
                    and not target.query and not target.fragment
                    and str(UUID(target.path.lstrip("/"))) == target.path.lstrip("/"))
        target = urlsplit(value)
        if target.scheme != ("ws" if websocket else "http") or target.netloc != "127.0.0.1:8529":
            return False
        if websocket:
            return target.path == "/_stcore/stream" and not target.query and not target.fragment
        if top_level:
            validate_route(value, kind)
        return True
    except (ValueError, SafetyStop):
        return False


def validate_identity(cookies, token):
    identities = [item for item in cookies if item.get("name") == "epc_device_id"]
    if (not re.fullmatch(r"[0-9a-f]{32}", token) or len(identities) != 1
            or identities[0].get("value") != token or identities[0].get("domain") != "127.0.0.1"
            or identities[0].get("path") != "/"):
        raise SafetyStop("Local synthetic identity changed or is ambiguous")


@dataclass(frozen=True)
class LocalConfig:
    commit: str
    nonce: str
    origin: str = ORIGIN

    def __post_init__(self):
        if (self.origin != ORIGIN or not re.fullmatch(r"[0-9a-f]{40}", self.commit)
                or not re.fullmatch(r"[0-9a-f]{32}", self.nonce)):
            raise SafetyStop("Invalid loopback-only preflight configuration")

    def address(self, kind):
        url = self.origin + "/?workflow=monthly&monthly_qa=isolated&monthly_admin=" + kind
        validate_route(url, kind)
        return url


class Server:
    def __init__(self, base, output, commit):
        self.base, self.output, self.commit = guarded_root(base), output, commit
        self.process = self.log = None

    def start(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 8529))  # Refuse an already occupied target.
        self.log = (self.output / "server.log").open("w")
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
            cwd=self.base, env=child_environment(self.base, self.commit),
            stdout=self.log, stderr=subprocess.STDOUT)
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self.alive()
            try:
                with opener.open(ORIGIN + "/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        self.alive()
                        return
            except OSError:
                pass
            time.sleep(.05)
        raise SafetyStop("Owned loopback server was not ready")

    def alive(self):
        if self.process is None or self.process.poll() is not None:
            raise SafetyStop("Owned loopback server is not running")

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        if self.log:
            self.log.close()


def serve():
    require_clean_configuration()
    base = guarded_root(os.environ.get("EPC_DATA_DIR", ""))
    install_outbound_guard(base)
    # A local wrapper proves which freshly started server the browser reached.
    # It calls the actual entrypoint without replacing any product handler.
    wrapper = base / "entrypoint.py"
    wrapper.write_text("import runpy\nimport sys\nimport streamlit as st\n"
        + "sys.path.insert(0, " + repr(str(ROOT)) + ")\n"
        + "st.caption(" + repr("Local synthetic server: " + (base / MARKER).read_text()) + ")\n"
        + "runpy.run_path(" + repr(str(ROOT / "run_web.py")) + ", run_name='__main__')\n")
    from streamlit.web import cli
    sys.argv = ["streamlit", "run", str(wrapper), "--server.address", "127.0.0.1",
                "--server.port", "8529", "--server.headless", "true",
                "--server.fileWatcherType", "none", "--browser.gatherUsageStats", "false"]
    cli.main()


class LocalJourney(live.Journey):
    def __init__(self, page, context, token, config, output, base, server, raw):
        super().__init__(page, context, token, config, output)
        self.base, self.server, self.raw = guarded_root(base), server, raw
        identity = sha256(("monthly-qa-v1:" + token).encode("ascii")).hexdigest()[:32]
        self.namespace = self.base / "_enfra_monthly_report_qa_v1" / identity
        self.generation = None
        self.storage_receipts = []

    def transport_boundary(self):
        self.server.alive()
        guarded_root(self.base)
        if (self.base / MARKER).read_text() != self.config.nonce:
            raise SafetyStop("Disposable root nonce changed")
        if self.blocked or (self.base / GUARD_LOG).read_text():
            raise SafetyStop("Network boundary failed; no further local action is allowed")
        validate_route(self.page.url, self.kind)
        validate_identity(self.context.cookies([ORIGIN]), self.token)
        if (self.base / "ordinary-canary").read_bytes() != CANARY:
            raise SafetyStop("Ordinary-root synthetic canary changed")

    def boundary(self):
        self.transport_boundary()
        if (self.base / "monthly_reports").exists():
            raise SafetyStop("Ordinary report storage was touched")
        for path in (self.namespace.parent, self.namespace, self.namespace / ".enfra-qa-namespace"):
            if path.is_symlink() or not path.exists() or not path.resolve().is_relative_to(self.base):
                raise SafetyStop("Synthetic physical namespace was not proven")
        if any(path.is_symlink() for path in self.namespace.rglob("*")):
            raise SafetyStop("Synthetic namespace contains a link")
        value = (self.namespace / ".enfra-qa-namespace").read_text()
        if not re.fullmatch(re.escape(self.namespace.name) + r"\|[0-9a-f]{32}", value):
            raise SafetyStop("Synthetic namespace generation is invalid")
        if self.generation is not None and self.generation != value:
            raise SafetyStop("Synthetic namespace generation changed")
        self.generation = value

    def guard(self):
        from playwright.sync_api import expect
        self.transport_boundary()
        # The wrapper nonce can render before the real app binds its namespace.
        # Wait read-only for the product banner, emitted after storage binding.
        expect(self.page.get_by_text("Local synthetic server: " + self.config.nonce, exact=True)).to_be_visible()
        self.transport_boundary()
        expect(self.page.get_by_text(live.BANNER, exact=True)).to_be_visible()
        self.transport_boundary()
        super().guard()  # Same code/banner/exception gates and final physical boundary.

    def saved_receipt(self, contract, stage):
        value = super().saved_receipt(contract, stage)
        self.guard()
        digest = sha256(self.raw).hexdigest()
        root = self.namespace / "monthly_reports"
        original = root / "directory_sources" / (digest + ".xlsx")
        pooled = root / "objects" / digest[:2] / digest
        for path in (original, pooled):
            if path.is_symlink() or path.read_bytes() != self.raw:
                raise SafetyStop("Local native save did not retain the unchanged workbook")
        history = {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
                   for path in (root / "directory").rglob("*") if path.is_file()}
        if not history:
            raise SafetyStop("Saved directory history is missing")
        if self.storage_receipts and history != self.storage_receipts[0]["history"]:
            raise SafetyStop("Saved directory files changed across reload/storage")
        self.storage_receipts.append({"stage": stage, "original_sha256": digest, "pool_sha256": digest,
                                      "history": history})
        return value

    def run(self, raw, contract):
        from playwright.sync_api import expect
        self.page.goto(self.config.address("directory"), wait_until="domcontentloaded", timeout=65000)
        self.guard()
        self.fill("Directory editor name", ACTOR)
        self.radio("Review saved directory")
        expect(self.page.get_by_text("No directory has been saved yet. Import a workbook to begin.", exact=True)).to_be_visible()
        expect(self.page.get_by_role("combobox", name="Saved contract directory", exact=True)).to_have_count(0)
        self.radio("Import a workbook")
        expect(self.page.get_by_text(IMPORT_DISCLOSURE, exact=True)).to_be_visible()
        self.snapshot("empty-import-disclosure")
        uploader = self.page.get_by_test_id("stFileUploader").filter(has=self.page.get_by_text("Contract / site directory workbook", exact=True))
        self.action("Upload invented workbook", lambda: uploader.locator("input[type=file]").set_input_files({
            "name": "synthetic-directory-retention.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": raw}))
        self.button("Read workbook")
        worksheet = self.page.get_by_test_id("stSelectbox").filter(has=self.page.get_by_text("Contract worksheet", exact=True))
        expect(worksheet).to_contain_text(SHEET)
        self.fill("Contract name", contract)
        expect(self.page.get_by_text("Saving 1 reviewed site records; 0 other saved records remain unchanged. Other workbook tabs are not imported into this contract.", exact=True)).to_be_visible()
        preview = self.expand("All included contacts before saving")
        verify_contacts(self.download_grid(preview, "reviewed-contacts"))
        expect(self.page.get_by_role("button", name="Save contract directory", exact=True)).to_be_disabled()
        self.action("Confirm reviewed synthetic contact", lambda: self.page.get_by_role("checkbox", name=CONFIRM, exact=True).check())
        self.button("Save contract directory")
        expect(self.page.get_by_text("Directory saved. Existing reports and their selected sites were not changed. You can review another tab or return to report setup.", exact=True)).to_be_visible()
        before = self.saved_receipt(contract, "saved")
        self.action("Reload saved synthetic directory", self.page.reload)
        self.fill("Directory editor name", ACTOR)
        reloaded = self.saved_receipt(contract, "reloaded")
        if reloaded != before:
            raise SafetyStop("Saved history/contact receipts changed across reload.")
        self.guard()
        link = self.page.get_by_role("link", name="Storage", exact=True)
        target = self.config.origin + "/" + link.get_attribute("href")
        validate_route(target, "storage")
        self.kind = "storage"
        link.click()
        self.guard()
        self.button("Check available storage")
        expect(self.page.get_by_text(STORAGE_DISCLOSURE, exact=False)).to_be_visible()
        self.snapshot("storage-retention-disclosure")
        self.guard()
        link = self.page.get_by_role("link", name="Directory", exact=True)
        target = self.config.origin + "/" + link.get_attribute("href")
        validate_route(target, "directory")
        self.kind = "directory"
        link.click()
        self.guard()
        self.fill("Directory editor name", ACTOR)
        after = self.saved_receipt(contract, "after-storage")
        if after != before:
            raise SafetyStop("Storage check changed saved directory history/contact receipts.")
        return {"history_sha256": sha256(before["history"]).hexdigest(),
                "contacts_sha256": sha256(before["contacts"]).hexdigest(),
                "history_caption": before["caption"]}


def final_isolation_failure(record):
    failed = bool(record["blocked_requests"] or record["page_errors"] or record["server_guard"]
                  or not record["ordinary_canary_unchanged"])
    if failed:
        record["result"] = "failed final isolation checks"
    return failed


def exercise(*, system_chromium=False):
    # Explicit diagnostic alternative only; CI always uses pinned Playwright.
    if type(system_chromium) is not bool:
        raise SafetyStop("Browser diagnostic selection must be a boolean")
    from playwright.sync_api import sync_playwright
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    OUT.mkdir(parents=True, exist_ok=False)  # Never overwrite first-attempt evidence.
    record = {"result": "not completed", "synthetic_only": True, "origin": ORIGIN,
              "actual_entrypoint": "run_web.py", "commit": commit,
              "tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip(),
              "harness_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "production_harness_sha256": sha256(Path(live.__file__).read_bytes()).hexdigest(),
              "tracked_modifications": subprocess.check_output(
                  ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).splitlines(),
              "worktree_diff_sha256": sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest(),
              "browser_distribution": "system Chromium diagnostic" if system_chromium else "Playwright pinned Chromium",
              "production_acceptance": False, "limits": [
                  "Loopback HTTP secure context, not Render HTTPS/deployment/network behavior.",
                  "Python socket audit and browser route guards, not an OS outbound sandbox.",
                  "No elapsed 30-day or aged hosted deletion claim.",
                  "Single worksheet; no automatic inactive-row filtering claim."]}
    with tempfile.TemporaryDirectory(prefix=PREFIX) as temp:
        base = Path(temp)
        nonce, token = secrets.token_hex(16), secrets.token_hex(16)
        (base / MARKER).write_text(nonce)
        (base / GUARD_LOG).write_text("")
        (base / "ordinary-canary").write_bytes(CANARY)
        config, raw = LocalConfig(commit, nonce), live.workbook()
        record["source_sha256"] = sha256(raw).hexdigest()
        record["source_bytes"] = len(raw)
        server = Server(base, OUT, commit)
        journey = browser = context = page = None
        blocked, errors = [], []
        try:
            server.start()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, env=child_environment(base, commit),
                    **({"executable_path": "/usr/bin/chromium"} if system_chromium else {}))
                record["browser_version"] = browser.version
                context = browser.new_context(accept_downloads=True, service_workers="block",
                                              viewport={"width": 1440, "height": 1000})
                if context.cookies():
                    raise SafetyStop("Fresh local browser context contains cookies")
                context.add_cookies([{"name": "epc_device_id", "value": token, "url": ORIGIN, "sameSite": "Lax"}])
                page = context.new_page()
                page.set_default_timeout(30000)
                journey = LocalJourney(page, context, token, config, OUT, base, server, raw)
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
                    record.update(journey.run(raw, "Synthetic Retention 291 " + secrets.token_hex(5)))
                    journey.guard()
                    if errors:
                        raise SafetyStop("Browser reported an unhandled error")
                    record["result"] = "passed local native upload, save, CSV, history and byte retention"
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
            was_passed = record["result"].startswith("passed")
            server.stop()
            record["events"] = journey.events if journey else []
            record["storage_receipts"] = journey.storage_receipts if journey else []
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
            if was_passed and failed:
                raise SafetyStop("Final local isolation checks failed after shutdown")


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        serve()
    elif not sys.argv[1:]:
        exercise()
    else:
        raise SystemExit("No target URL, data directory or additional arguments are supported")
