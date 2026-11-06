"""Synthetic localhost DOM qualification for failed fixture installation (#292).

No remote URL, existing data root or credentials are accepted. The real
run_web.py renders Start/Reset. Faults wrap storage boundaries only. Shelf setup
uses the storage API (not native upload); aging/corruption/quota are test setup.
A passing run is neither production-disk durability nor a bounded-recovery claim.
"""
from __future__ import annotations

from hashlib import sha256
import json
import ipaddress
import os
import re
from pathlib import Path
import secrets
import socket
import uuid
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_shared_fixture_testing as shared

OUT = ROOT / "test-artifacts" / "fixture-cleanup"
ORIGIN, URL = shared.ORIGIN, shared.URL
SCENARIOS = ("source-failure", "return-during-rollback", "partial-crash", "corrupt-journal", "quota")
CONTROL = "_cleanup_harness"
SOURCE = Path("_enfra_fixture_start_v1/starting-report/source.docx")
QA_BUCKET = "_enfra_monthly_report_qa_v1"
ADMISSION = "_enfra_fixture_run_admission_v1"
JOURNAL = "pending-install.json"
SENTINEL = ".enfra-qa-namespace"


def guarded_root(value):
    path = Path(value)
    if (not path.is_absolute() or path.is_symlink() or path.resolve() != path
            or path.parent != Path(tempfile.gettempdir()).resolve()
            or not path.name.startswith("shared-fixture-dom-synthetic-")
            or (path / shared.MARKER).is_symlink()
            or (path / shared.MARKER).read_text() != "shared-fixture-dom-v1"):
        raise ValueError("Cleanup QA requires its own marked disposable root")
    return path


def allowed_url(value, *, websocket=False):
    """Exact isolated server only. WebSockets are restricted to Streamlit."""
    try:
        if value.startswith("blob:") and not websocket:
            inner = urlsplit(value[5:])
            return (allowed_url(value[5:]) and not inner.query and not inner.fragment
                    and str(uuid.UUID(inner.path.lstrip("/"))) == inner.path.lstrip("/"))
        parsed = urlsplit(value)
        if (parsed.scheme != ("ws" if websocket else "http")
                or parsed.hostname != "127.0.0.1" or parsed.port != 8521
                or parsed.username is not None or parsed.password is not None):
            return False
        return not websocket or parsed.path == "/_stcore/stream"
    except ValueError:
        return False


def require_clean_configuration():
    # Application config calls load_dotenv on this exact path. Never allow a
    # developer's local credentials to enter even this synthetic runtime.
    for path in (ROOT / ".env", ROOT / ".streamlit/secrets.toml"):
        if path.exists() or path.is_symlink():
            raise ValueError("Cleanup QA refuses local credential configuration")


def install_outbound_guard(base):
    base = guarded_root(base)
    def audit(event, args):
        if event not in {"socket.connect", "socket.getaddrinfo"}:
            return
        address = args[1] if event == "socket.connect" else args[0]
        host = address[0] if isinstance(address, tuple) else address
        if host in {None, "localhost", "127.0.0.1", "::1"}:
            return
        try:
            if ipaddress.ip_address(str(host)).is_loopback:
                return
        except ValueError:
            pass
        with (base / shared.GUARD_LOG).open("a") as stream:
            stream.write(json.dumps({"blocked": event + ":non-loopback"}) + "\n")
        raise AssertionError("Cleanup QA blocked non-loopback network")
    sys.addaudithook(audit)


def child_environment(base):
    require_clean_configuration()
    base = guarded_root(base)
    home = base / CONTROL / "home"
    home.mkdir(parents=True, exist_ok=True)
    # Deliberately do not inherit HOME, EPC_DATA_DIR, API keys, proxy variables,
    # cloud identity, GitHub credentials or application settings from the runner.
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT") if key in os.environ}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), EPC_DATA_DIR=str(base),
               PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1",
               ANTHROPIC_API_KEY="", OPENAI_API_KEY="", SMARTSHEET_API_MODE="disabled")
    return env


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def inventory(path):
    return {str(item.relative_to(path)): digest(item) for item in sorted(path.rglob("*")) if item.is_file()}


def new_cookie():
    from app.device_identity import device_token
    cookie = secrets.token_hex(16)
    assert device_token({"epc_device_id": cookie}) == cookie
    return cookie


def namespace(base, cookie):
    return shared.run_directory(guarded_root(base), cookie)


def poll_generation(base, cookie):
    """Only the marker is racy during native Reset; never inventory mid-delete."""
    root = namespace(base, cookie)
    try:
        value = (root / SENTINEL).read_text()
    except FileNotFoundError:
        return None
    return value if re.fullmatch(re.escape(root.name) + r"\|[0-9a-f]{32}", value) else None


def snapshot(base, cookie):
    base = guarded_root(base)
    root = namespace(base, cookie)
    index = base / ADMISSION / "reservations.json"
    return {"scope": root.name, "exists": root.exists(),
            "generation_marker": (root / SENTINEL).read_text() if (root / SENTINEL).is_file() else None,
            "source_sha256": digest(root / SOURCE) if (root / SOURCE).is_file() else None,
            "namespace_files": inventory(root),
            "pending_entries": [str(p.relative_to(root)) for p in root.rglob(".pending-*")],
            "installed_payload_bytes": sum(p.stat().st_size for p in (root / SOURCE).parent.iterdir() if p.is_file()) if (root / SOURCE).is_file() else 0,
            "reservations": json.loads(index.read_text())["reservations"] if index.exists() else [],
            "journal": (base / ADMISSION / JOURNAL).exists(),
            "index_sha256": digest(index) if index.exists() else None,
            "journal_sha256": digest(base / ADMISSION / JOURNAL) if (base / ADMISSION / JOURNAL).exists() else None,
            "tombstones": {p.name: inventory(p) for p in sorted((base / QA_BUCKET).glob(".reclaimed-*"))},
            "discarding": {p.name: inventory(p) for p in sorted((base / QA_BUCKET).glob(".discarding-*"))},
            "originals": inventory(base / "_enfra_shared_fixtures_v1"),
            "live_canary": digest(base / "synthetic-live-canary")}


def append(base, name, value):
    with (guarded_root(base) / CONTROL / name).open("a") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def arm(base, cookie, mode):
    if mode not in {"source-failure", "pause-fail-index", "crash-partial"}:
        raise ValueError("Unknown synthetic fault")
    control = guarded_root(base) / CONTROL
    value = {"scope": namespace(base, cookie).name, "mode": mode}
    (control / "fault.json").write_text(json.dumps(value))
    append(base, "events.jsonl", {"armed": value})


def install_faults(base):
    """One-shot, exact-scope fault boundaries; production modules unchanged."""
    base = guarded_root(base)
    from app import monthly_report_fixture_admission as admission
    from app import monthly_report_fixture_vault as vault
    from app import monthly_report_testing as testing
    control = base / CONTROL

    def claim(mode):
        path = control / "fault.json"
        if not path.exists():
            return False
        value = json.loads(path.read_text())
        if value != {"mode": mode, "scope": testing.scope()}:
            return False
        path.rename(control / "consumed-fault.json")
        append(base, "events.jsonl", {"triggered": value})
        return True

    original_save, original_write = admission._save, vault._write_file

    def save(directory, selected):
        if claim("pause-fail-index"):
            (control / "paused").write_text("paused before index save")
            deadline = time.monotonic() + 180
            while not (control / "release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Synthetic pause was not released")
                time.sleep(.02)
            raise OSError("SYNTHETIC pre-index failure")
        return original_save(directory, selected)

    def write(directory, name, data):
        if name == "source.docx" and claim("source-failure"):
            raise OSError("SYNTHETIC source-write failure")
        if name == "source.docx" and claim("crash-partial"):
            (control / "crashed").write_text("native source write entered")
            os._exit(23)
        return original_write(directory, name, data)

    admission._save, vault._write_file = save, write
    # Observe restoration before the subsequent distinct admission may reclaim
    # the still-idle copy again. This observer never changes age or decisions.
    original_recover = testing.recover_set_aside

    def recover(root, reserved):
        original_recover(root, reserved)
        restored = []
        for scope, generation in reserved:
            target = Path(root) / QA_BUCKET / scope
            if ((target / SENTINEL).is_file() and (target / SOURCE).is_file()
                    and (target / SENTINEL).read_text() == scope + "|" + generation):
                restored.append({"scope": scope, "generation": generation,
                                 "source_sha256": digest(target / SOURCE)})
        append(base, "restored.jsonl", {"restored": restored})
    testing.recover_set_aside = recover


def seed(base):
    require_clean_configuration()
    base = guarded_root(base)
    from app import monthly_report_fixture_vault as vault
    from app.monthly_report_shared_fixtures import SharedFixtureLibrary
    source = shared.synthetic_docx()
    identity = vault.ReportIdentity("Synthetic Testing Contract", ("synthetic-site-a",), "2026-10", ("Synthetic Site A",))
    metadata = vault.FixtureMetadata("Synthetic cleanup DOM", identity, identity, "AUTH03",
        "Preserve synthetic incomplete work.", (vault.ExpectedSection("Activity", includes=("synthetic pump",)),),
        "2026-11-06T00:00:00+00:00", True)
    receipt = SharedFixtureLibrary(base).upload(source, metadata)
    (base / "synthetic-live-canary").write_text("Synthetic ordinary-root record must remain unchanged")
    return {"original_sha256": sha256(source).hexdigest(), "fixture_id": receipt.fixture_id,
            "original_size": len(source)}


def age(base, cookie):
    root = namespace(base, cookie)
    stamp = time.time() - 25 * 3600
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        os.utime(path, (stamp, stamp), follow_symlinks=False)
    os.utime(root, (stamp, stamp))


def fill_budget(base):
    from app import memory, monthly_report_testing as testing
    from app import monthly_report_fixture_admission as admission
    from app.monthly_report_fixture_runs import FixtureRunContext
    before = os.environ.get("EPC_DATA_DIR")
    os.environ["EPC_DATA_DIR"] = str(guarded_root(base))
    try:
        index = base / ADMISSION / "reservations.json"
        used = sum(item["added_bytes"] for item in json.loads(index.read_text())["reservations"])
        with testing.isolated("e" * 32):
            path = memory._data_dir()
            context = FixtureRunContext(testing.scope(), testing.generation(), path)
            with admission.admit_run_copy(context, admission.MAX_ACTIVE_COPY_BYTES - used):
                (path / "SYNTHETIC-accounting-only").write_bytes(b"S")
        return {"reserved_bytes": admission.MAX_ACTIVE_COPY_BYTES - used, "physical_bytes": 1}
    finally:
        if before is None:
            os.environ.pop("EPC_DATA_DIR", None)
        else:
            os.environ["EPC_DATA_DIR"] = before


def wait_until(condition, seconds=60, *, dispatch_events=None, label="observation"):
    """Bound an observation without starving routed browser messages.

    Synchronous Playwright dispatches WebSocket/HTTP callbacks only inside its
    API calls. A Python sleep after a native click can prevent that very click
    from reaching Streamlit. Browser callers therefore provide wait_for_timeout
    as an event-dispatch tick; the filesystem predicate, not elapsed sleep,
    decides success. No native action is repeated and no guard is removed.
    Server startup, before there is a browser, uses the ordinary sleep path.
    """
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        if condition():
            return
        interval = min(.05, remaining)
        if dispatch_events is None:
            time.sleep(interval)
        else:
            dispatch_events(interval * 1000)
    raise AssertionError("Synthetic observation deadline exceeded: " + label)


class Server:
    def __init__(self, base, output):
        self.base, self.output, self.process = base, output, None
        self.log = None

    def start(self):
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", 8521))  # Refuse an already occupied target.
        self.log = (self.output / "server.log").open("a")
        self.process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
            cwd=ROOT, env=child_environment(self.base), stdout=self.log, stderr=subprocess.STDOUT)
        def healthy():
            if self.process.poll() is not None:
                raise RuntimeError("Synthetic server exited before readiness")
            try:
                with urlopen(ORIGIN + "/_stcore/health", timeout=1) as response:
                    return response.status == 200
            except OSError:
                return False
        wait_until(healthy)

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


def exercise(engine, name, scenario, output):
    from playwright.sync_api import expect
    record = {"engine": name, "scenario": scenario, "steps": [], "failures": [],
              "network_attempts": [], "page_errors": [], "frontend": []}
    with tempfile.TemporaryDirectory(prefix="shared-fixture-dom-synthetic-") as temp:
        base = Path(temp)
        (base / shared.MARKER).write_text("shared-fixture-dom-v1")
        (base / shared.GUARD_LOG).write_text("")
        (base / CONTROL).mkdir()
        record["fixture"] = seed(base)
        cookies = {key: new_cookie() for key in "abc"}
        original = snapshot(base, cookies["a"])
        server = Server(base, output)
        browser = None
        contexts = []
        page_keys = {}
        page = None
        expected = shared._expected_frontend()
        try:
            server.start()
            browser = engine.launch(headless=True)

            def session(key, *, recovering=False):
                context = browser.new_context(viewport={"width": 1440, "height": 1000},
                                              accept_downloads=True, service_workers="block")
                contexts.append(context)
                context.tracing.start(screenshots=True, snapshots=True, sources=True)
                context.add_cookies([{"name": "epc_device_id", "value": cookies[key], "url": ORIGIN}])
                def route(route):
                    if allowed_url(route.request.url):
                        route.continue_()
                    else:
                        record["network_attempts"].append({"kind": "http", "url": route.request.url})
                        route.abort()
                def websocket(route):
                    if allowed_url(route.url, websocket=True):
                        route.connect_to_server()
                    else:
                        record["network_attempts"].append({"kind": "websocket", "url": route.url})
                        route.close()
                context.route("**/*", route)
                context.route_web_socket("**/*", websocket)
                current = context.new_page()
                page_keys[current] = key
                current.set_default_timeout(30000)
                current.on("pageerror", lambda error: record["page_errors"].append(str(error)))
                def response(value):
                    if urlsplit(value.url).path == "/static/js/" + expected[0]:
                        record["frontend"].append(shared._frontend_response_receipt(value, expected))
                current.on("response", response)
                current.goto(URL, wait_until="domcontentloaded")
                text = "awaiting fixture cleanup recovery" if recovering else "Shared report testing"
                expect(current.get_by_text(text, exact=not recovering)).to_be_visible(timeout=60000)
                shared.idle(current)
                return current

            def capture(label, current):
                shared.idle(current)
                current.screenshot(path=str(output / (label + ".png")), full_page=True)
                record["steps"].append({"label": label, "visible_text": current.locator("body").inner_text(),
                    "state": {key: snapshot(base, cookie) for key, cookie in cookies.items()}})

            def start(current, *, succeeds=True):
                key = page_keys[current]
                before = snapshot(base, cookies[key])["generation_marker"]
                current.get_by_role("button", name="Start fresh test with this fixture", exact=True).click()
                wait_until(lambda: poll_generation(base, cookies[key]) not in (None, "", before),
                           dispatch_events=current.wait_for_timeout, label="native Start generation")
                record.setdefault("native_starts", []).append({"scope": namespace(base, cookies[key]).name,
                    "before": before, "after": poll_generation(base, cookies[key])})
                if succeeds:
                    expect(current.get_by_role("textbox", name="Your name", exact=True)).to_be_visible(timeout=60000)
                    shared.idle(current)

            def download_original(current, label):
                with current.expect_download() as pending:
                    current.get_by_role("button", name="Download unchanged original", exact=True).click()
                downloaded = base / CONTROL / (label + ".docx")
                pending.value.save_as(downloaded)
                value = digest(downloaded)
                assert value == record["fixture"]["original_sha256"]
                record.setdefault("original_downloads", []).append({"label": label, "sha256": value})
                downloaded.unlink()

            def preserved(before, key="a"):
                after = snapshot(base, cookies[key])
                for field in ("generation_marker", "source_sha256", "originals", "live_canary"):
                    assert after[field] == before[field], (field, after, before)
                return after

            page = session("a")
            expect(page.get_by_text("Anyone with this link can upload, view and download these files without a login. The fixture library is shared; this browser’s report workspace is isolated.", exact=True)).to_be_visible()
            expect(page.get_by_text("Reset clears this browser’s disposable report run. Shared originals remain available.", exact=True)).to_be_visible()
            start(page)
            a_before = snapshot(base, cookies["a"])
            assert a_before["source_sha256"] == record["fixture"]["original_sha256"]
            capture("native-stage-and-disclosure", page)
            download_original(page, "before-fault")
            # Close A before artificial aging; no background session refresh can
            # turn the intended idle fixture into an accidental active fixture.
            page.close()
            page = session("b")
            if scenario == "quota":
                record["quota_setup"] = fill_budget(base)
                full = snapshot(base, cookies["a"])["reservations"]
                start(page, succeeds=False)
                expect(page.get_by_text("128 MiB budget", exact=False)).to_be_visible()
                expect(page.get_by_text("Copies unused for 24 hours are cleared automatically.", exact=False)).to_be_visible()
                shared.idle(page)
                assert snapshot(base, cookies["b"])["source_sha256"] is None
                assert preserved(a_before)["reservations"] == full
                capture("quota-disclosure", page)
            else:
                age(base, cookies["a"])
                mode = {"source-failure": "source-failure", "return-during-rollback": "pause-fail-index"}.get(scenario, "crash-partial")
                arm(base, cookies["b"], mode)
                start(page, succeeds=False)
                if mode == "pause-fail-index":
                    wait_until(lambda: (base / CONTROL / "paused").exists(),
                               dispatch_events=page.wait_for_timeout, label="pre-index pause entered")
                    returned = session("a", recovering=True)
                    hidden = snapshot(base, cookies["a"])
                    assert not hidden["exists"] and len(hidden["tombstones"]) == 1
                    capture("return-fails-closed-during-admission", returned)
                    (base / CONTROL / "release").write_text("release synthetic failure")
                if mode != "crash-partial":
                    message = "SYNTHETIC pre-index failure" if mode == "pause-fail-index" else "SYNTHETIC source-write failure"
                    expect(page.get_by_text(message, exact=False)).to_be_visible(timeout=60000)
                    shared.idle(page)
                    after = preserved(a_before)
                    assert after["reservations"] == a_before["reservations"] and not after["journal"]
                    failed = snapshot(base, cookies["b"])
                    assert failed["source_sha256"] is None and not failed["pending_entries"]
                    assert not failed["tombstones"] and not failed["discarding"]
                    capture("failed-admission-preserves-before", page)
                    returned = session("a")  # Real return refreshes A before B's distinct success.
                    start(page)
                    preserved(a_before)
                    assert snapshot(base, cookies["b"])["source_sha256"] == a_before["source_sha256"]
                    capture("native-retry-success", page)
                    b_marker = snapshot(base, cookies["b"])["generation_marker"]
                    page.get_by_role("button", name="Reset this test workspace", exact=True).click()
                    expect(page.get_by_role("textbox", name="Your name", exact=True)).not_to_be_visible()
                    wait_until(lambda: poll_generation(base, cookies["b"]) not in (None, "", b_marker),
                               dispatch_events=page.wait_for_timeout, label="native B Reset generation")
                    shared.idle(page)
                    assert snapshot(base, cookies["b"])["source_sha256"] is None
                    preserved(a_before)
                    capture("native-scoped-reset", page)
                else:
                    wait_until(lambda: server.process.poll() is not None,
                               dispatch_events=page.wait_for_timeout, label="native partial process exit")
                    assert server.process.returncode == 23 and (base / CONTROL / "crashed").exists()
                    server.stop()
                    hidden = snapshot(base, cookies["a"])
                    assert hidden["journal"] and len(hidden["tombstones"]) == 1 and not hidden["exists"]
                    if scenario == "corrupt-journal":
                        (base / ADMISSION / JOURNAL).write_text('{"schema":2}')
                    recovery_before = snapshot(base, cookies["a"])
                    def unchanged_recovery():
                        observed = snapshot(base, cookies["a"])
                        for field in ("tombstones", "discarding", "reservations", "index_sha256", "journal_sha256"):
                            assert observed[field] == recovery_before[field], field
                    # Close all dead sessions before restart: old clients must not
                    # reconnect and race test setup or repeat a pending callback.
                    for current in contexts:
                        for dead_page in current.pages:
                            dead_page.close()
                    server.start()
                    returned = session("a", recovering=True)
                    capture("return-blocked-after-crash", returned)
                    page = session("c")
                    start(page, succeeds=False)
                    blocked = "Fixture installation recovery metadata is invalid." if scenario == "corrupt-journal" else "requires its browser's scoped reset"
                    expect(page.get_by_text(blocked, exact=False)).to_be_visible()
                    capture("unrelated-start-blocked", page)
                    unchanged_recovery()
                    # Unrelated Reset neither clears the journal nor old copy.
                    unrelated_marker = snapshot(base, cookies["c"])["generation_marker"]
                    page.get_by_role("button", name="Reset this test workspace", exact=True).click()
                    wait_until(lambda: poll_generation(base, cookies["c"]) not in (None, "", unrelated_marker),
                               dispatch_events=page.wait_for_timeout, label="unrelated native C Reset generation")
                    shared.idle(page)
                    assert snapshot(base, cookies["a"])["tombstones"] == hidden["tombstones"]
                    unchanged_recovery()
                    affected = session("b")
                    expect(affected.get_by_role("button", name="Reset this test workspace", exact=True)).to_be_visible()
                    marker = snapshot(base, cookies["b"])["generation_marker"]
                    affected.get_by_role("button", name="Reset this test workspace", exact=True).click()
                    wait_until(lambda: poll_generation(base, cookies["b"]) not in (None, "", marker),
                               dispatch_events=affected.wait_for_timeout, label="affected native B Reset generation")
                    shared.idle(affected)
                    capture("affected-reset-reachable", affected)
                    assert (base / ADMISSION / JOURNAL).exists()
                    unchanged_recovery()
                    (base / CONTROL / "restored.jsonl").write_text("")
                    start(page, succeeds=scenario != "corrupt-journal")
                    if scenario == "corrupt-journal":
                        expect(page.get_by_text(blocked, exact=False)).to_be_visible()
                        shared.idle(page)
                        assert snapshot(base, cookies["a"])["tombstones"] == hidden["tombstones"]
                        assert (base / ADMISSION / JOURNAL).exists()
                        assert snapshot(base, cookies["c"])["source_sha256"] is None
                        unchanged_recovery()
                        capture("corrupt-journal-still-blocked", page)
                    else:
                        assert not (base / ADMISSION / JOURNAL).exists()
                        complete = snapshot(base, cookies["c"])
                        assert complete["source_sha256"] == a_before["source_sha256"]
                        assert not complete["pending_entries"] and not complete["tombstones"] and not complete["discarding"]
                        assert complete["reservations"] == [{"scope": complete["scope"],
                            "generation": complete["generation_marker"].split("|")[1],
                            "added_bytes": complete["installed_payload_bytes"]}]
                        observations = [json.loads(line) for line in (base / CONTROL / "restored.jsonl").read_text().splitlines()]
                        assert any({"scope": a_before["scope"], "generation": a_before["generation_marker"].split("|")[1],
                                    "source_sha256": a_before["source_sha256"]} in row["restored"] for row in observations)
                        # Distinct C success can reclaim A again under the 24-hour policy.
                        capture("known-partial-recovered-then-new-admission", page)
            download_original(page, "after-journey")
            assert record["frontend"] and all(item["matches"] for item in record["frontend"])
            assert not record["network_attempts"] and not record["page_errors"]
            assert not (base / shared.GUARD_LOG).read_text()
            final = snapshot(base, cookies["a"])
            assert final["originals"] == original["originals"] and final["live_canary"] == original["live_canary"]
            record["result"] = "passed"
        except Exception as exc:
            record["result"] = "failed"
            record["failures"].append(type(exc).__name__ + ": " + str(exc))
            if page and not page.is_closed():
                try:
                    page.screenshot(path=str(output / "first-failure.png"), timeout=5000)
                except Exception as screenshot_error:
                    record["screenshot_error"] = type(screenshot_error).__name__
            raise
        finally:
            for index, context in enumerate(contexts):
                try:
                    context.tracing.stop(path=str(output / f"context-{index}.zip"))
                    context.close()
                except Exception as trace_error:
                    record.setdefault("artifact_errors", []).append(type(trace_error).__name__)
            if browser:
                browser.close()
            server.stop()
            record["server_guard"] = (base / shared.GUARD_LOG).read_text().splitlines()
            record["fault_receipts"] = [json.loads(line) for line in (base / CONTROL / "events.jsonl").read_text().splitlines()] if (base / CONTROL / "events.jsonl").exists() else []
            record["final"] = {key: snapshot(base, cookie) for key, cookie in cookies.items()}
            if record.get("artifact_errors"):
                record["result"] = "failed"
            (output / "results.json").write_text(json.dumps(record, indent=2))
    assert record["result"] == "passed", record.get("artifact_errors")
    return record


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    # Record source provenance independently of the eventual CI status.
    provenance = {key: subprocess.check_output(["git", "rev-parse", value], cwd=ROOT, text=True).strip()
                  for key, value in (("head", "HEAD"), ("tree", "HEAD^{tree}"))}
    provenance["product_git_blobs"] = {name: subprocess.check_output(
        ["git", "hash-object", name], cwd=ROOT, text=True).strip() for name in (
        "run_web.py", "app/monthly_report_fixture_admission.py", "app/monthly_report_fixture_runs.py",
        "app/monthly_report_testing.py", "app/monthly_report_shared_testing_ui.py", "app/monthly_report_ui.py")}
    provenance["harness_sha256"] = digest(Path(__file__))
    provenance["checkout_kind"] = "Actual tested checkout; PR jobs may use GitHub's prospective merge, not the PR head"
    provenance["worktree_diff_sha256"] = sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest()
    results = {"synthetic_only": True, "provenance": provenance, "completed": [], "failures": []}
    try:
        with sync_playwright() as playwright:
            for engine, name in ((playwright.chromium, "chromium"), (playwright.webkit, "playwright-webkit")):
                for scenario in SCENARIOS:
                    output = OUT / name / scenario
                    output.mkdir(parents=True, exist_ok=True)
                    try:
                        exercise(engine, name, scenario, output)
                        results["completed"].append(name + ":" + scenario)
                    except Exception as exc:
                        results["failures"].append(name + ":" + scenario + ": " + str(exc))
    finally:
        results["result"] = "passed" if len(results["completed"]) == 10 and not results["failures"] else "failed"
        (OUT / "results.json").write_text(json.dumps(results, indent=2))
    assert results["result"] == "passed", results["failures"]


if __name__ == "__main__":
    if sys.argv[1:] == ["--serve"]:
        require_clean_configuration()
        install_outbound_guard(os.environ["EPC_DATA_DIR"])
        install_faults(os.environ["EPC_DATA_DIR"])
        shared.serve()  # unchanged run_web.py + backend socket/service guards
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("No target URL, data directory or additional arguments are supported")
