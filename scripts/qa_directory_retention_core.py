"""Core retention UI/store acceptance only. No CSV export or picker substitution.

Uses genuine import, confirmation, save, history, reload and Storage UI actions.
Read-only disposable-store receipts complement, never replace, those actions.
Not production, native CSV, elapsed-30-day, aging, deletion or physical-device acceptance.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import qa_directory_retention_local as local
from scripts.qa_directory_retention_local import (
    live, SafetyStop, ACTOR, SHEET, CONFIRM, IMPORT_DISCLOSURE, STORAGE_DISCLOSURE,
    ORIGIN, PREFIX, MARKER, GUARD_LOG, CANARY, LocalConfig, Server,
    child_environment, allowed_url, final_isolation_failure, validate_route,
)

OUT = ROOT / "test-artifacts/directory-retention-core"


@contextmanager
def open_owned(base, relative):
    """Open a contained read-only descriptor without following any symlinks."""
    local.guarded_root(base)
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in {"..", "."} for p in parts):
        raise SafetyStop("Invalid owned-store relative path")
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            yield leaf
        finally:
            os.close(leaf)
    finally:
        os.close(fd)


def read_descriptor(fd, limit, links):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != links or info.st_size > limit:
        raise SafetyStop("Owned-store file has invalid type, size or link count")
    result = os.read(fd, limit + 1)
    after = os.fstat(fd)
    if (len(result) > limit or len(result) != info.st_size
            or (info.st_dev, info.st_ino, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise SafetyStop("Owned-store file changed during bounded read")
    return result


def read_owned(base, relative, limit=65536):
    """Mutable manifest/history files must remain independent single-link files."""
    with open_owned(base, relative) as fd:
        return read_descriptor(fd, limit, links=1)


def verify_source_pair(base, root, raw):
    """The exact source/pool paths must be the two links to one owned inode.

    Both descriptors stay open for comparison; independent equal-byte copies,
    an additional link elsewhere, symlinks and a lone source all fail closed.
    """
    digest = sha256(raw).hexdigest()
    source = root / "directory_sources" / (digest + ".xlsx")
    pool = root / "objects" / digest[:2] / digest
    with open_owned(base, source) as first, open_owned(base, pool) as second:
        def identity():
            a, b = os.fstat(first), os.fstat(second)
            if ((a.st_dev, a.st_ino) != (b.st_dev, b.st_ino)
                    or a.st_nlink != 2 or b.st_nlink != 2):
                raise SafetyStop("Original workbook source/pool are not an exact two-link pair")
        identity()
        if (read_descriptor(first, len(raw), links=2) != raw
                or read_descriptor(second, len(raw), links=2) != raw):
            raise SafetyStop("Original workbook was not retained byte-identically")
        identity()


def owned_names(base, relative):
    """Bounded directory enumeration without following intermediate links."""
    local.guarded_root(base)
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise SafetyStop("Invalid owned-store directory")
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(names) >= 16 or entry.is_symlink():
                    raise SafetyStop("Unexpected owned-store directory entries")
                names.append(entry.name)
        return sorted(names)
    finally:
        os.close(fd)


def expected_state(contract, raw, updated_at):
    digest = sha256(raw).hexdigest()
    source = digest + ":" + SHEET + "!B6"
    return {"schema": 1, "contract": contract, "revision": 1, "actor": ACTOR,
            "updated_at": updated_at, "source_sha256": digest, "source_sheet": SHEET,
            "action": "save", "archived": False, "contract_contacts": [],
            "sites": [{"key": "site-" + sha256(source.encode()).hexdigest()[:24],
                       "title": live.SITE, "aliases": [], "address": "100 Example Way",
                       "source": source, "active": True,
                       "contacts": [{"role": "Facility Director", "name": live.PERSON,
                                     "phone": live.PHONE, "email": live.EMAIL,
                                     "source": digest + ":" + SHEET + "!B9,B10,B11"}]}]}


class CoreJourney(local.LocalJourney):
    def download_grid(self, *args, **kwargs):
        raise SafetyStop("CSV export is not part of core retention acceptance")

    def confirm_review(self):
        from playwright.sync_api import expect
        def confirm():
            # Streamlit 1.61.1 uses React Aria Checkbox: a visible label
            # containing a VisuallyHidden input. Click its associated label,
            # not the hidden input, and verify the native checked state.
            checkbox = self.page.get_by_role("checkbox", name=CONFIRM, exact=True)
            label = self.page.get_by_test_id("stCheckbox").locator("label").filter(has=checkbox)
            expect(checkbox).to_have_count(1)
            expect(checkbox).to_be_enabled()
            expect(checkbox).not_to_be_checked()
            expect(label).to_have_count(1)
            expect(label).to_be_visible()
            self.guard()
            label.click()
            expect(checkbox).to_be_checked()
        self.action("Confirm reviewed synthetic contact", confirm)

    def snapshot(self, name):
        # The inherited snapshot has a pre-guard; add a post-guard and discard
        # the image if the page/namespace drifted during capture.
        path = self.output / (name + ".png")
        super().snapshot(name)
        try:
            self.guard()
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def store_receipt(self, contract, stage):
        self.guard()
        digest = sha256(self.raw).hexdigest()
        root = self.namespace.relative_to(self.base) / "monthly_reports"
        key = re.sub(r"[^a-z0-9]+", "-", contract.casefold()).strip("-")[:50] or "contract"
        key += "-" + sha256(contract.encode()).hexdigest()[:12]
        if (owned_names(self.base, root / "directory") != [key]
                or owned_names(self.base, root / "directory" / key) != ["history", "manifest.json"]
                or owned_names(self.base, root / "directory" / key / "history") != ["00000001.json"]):
            raise SafetyStop("Unexpected saved contracts or revisions")
        paths = [root / "directory" / key / "manifest.json",
                 root / "directory" / key / "history/00000001.json"]
        documents = [read_owned(self.base, path) for path in paths]
        if documents[0] != documents[1]:
            raise SafetyStop("Saved manifest differs from immutable revision one")
        state = json.loads(documents[0])
        stamp = state.get("updated_at")
        if not isinstance(stamp, str) or not stamp or len(stamp) > 64:
            raise SafetyStop("Invalid saved timestamp")
        if json.dumps(state, sort_keys=True, allow_nan=False) != json.dumps(
                expected_state(contract, self.raw, stamp), sort_keys=True, allow_nan=False):
            raise SafetyStop("Saved directory/site/contact values differ from synthetic input")
        verify_source_pair(self.base, root, self.raw)
        receipt = {"state": state, "history_sha256": sha256(documents[1]).hexdigest(),
                   "original_sha256": digest, "pool_sha256": digest}
        self.guard()
        if self.storage_receipts and receipt != self.storage_receipts[0]["receipt"]:
            raise SafetyStop("Saved directory history changed across reload/Storage")
        self.storage_receipts.append({"stage": stage, "receipt": receipt})
        return receipt

    def saved_receipt(self, contract, stage):
        from playwright.sync_api import expect
        self.radio("Review saved directory")
        saved = self.page.get_by_role("combobox", name="Saved contract directory", exact=True)
        expect(saved).to_be_visible()
        self.action("Inspect saved directory choices", saved.click)
        options = self.page.get_by_role("option")
        expect(options).to_have_count(1)
        expect(options).to_have_text([contract])
        self.action("Select synthetic directory", lambda: self.page.get_by_role("option", name=contract, exact=True).click())
        history = self.expand("History and restoration")
        caption = history.get_by_text(re.compile(r"^Version 1 · " + re.escape(ACTOR) + r" · .+ · save$"))
        expect(caption).to_have_count(1)
        expect(caption).to_be_visible()
        expect(history.get_by_role("spinbutton", name="Directory version to inspect", exact=True)).to_have_value("1")
        expect(history.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(history.get_by_test_id("stDataFrame")).to_be_visible()
        contacts = self.expand("All included contacts before saving")
        expect(contacts.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(contacts.get_by_test_id("stDataFrame")).to_be_visible()
        receipt = self.store_receipt(contract, stage)
        self.snapshot(stage)
        self.guard()
        return {"caption": caption.inner_text(), "store": receipt}

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
        worksheet = self.page.get_by_role("combobox", name="Contract worksheet", exact=True)
        expect(worksheet).to_have_count(1)
        expect(worksheet).to_be_visible()
        expect(worksheet).to_have_value(SHEET)
        self.fill("Contract name", contract)
        expect(self.page.get_by_text("Saving 1 reviewed site records; 0 other saved records remain unchanged. Other workbook tabs are not imported into this contract.", exact=True)).to_be_visible()
        preview = self.expand("All included contacts before saving")
        expect(preview.get_by_test_id("stDataFrame")).to_have_count(1)
        expect(preview.get_by_test_id("stDataFrame")).to_be_visible()
        expect(self.page.get_by_role("button", name="Save contract directory", exact=True)).to_be_disabled()
        self.confirm_review()
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
        return {"history_sha256": before["store"]["history_sha256"],
                "history_caption": before["caption"]}


def exercise():
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
              "browser_distribution": "Playwright pinned Chromium",
              "production_acceptance": False, "native_csv_acceptance": False,
              "coverage": "core retention UI/store acceptance", "limits": [
                  "No CSV export or picker acceptance.",
                  "Retention-clock correctness (.imported timestamp) is not verified.",
                  "No production, physical-device, elapsed-30-day, aging or deletion acceptance.",
                  "Loopback HTTP only; socket audit is not an OS outbound sandbox.",
                  "Exact store values are verified read-only; native canvas values require screenshot review.",
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
                browser = playwright.chromium.launch(headless=True, env=child_environment(base, commit))
                record["browser_version"] = browser.version
                context = browser.new_context(accept_downloads=False, service_workers="block",
                                              viewport={"width": 1440, "height": 1000})
                if context.cookies():
                    raise SafetyStop("Fresh local browser context contains cookies")
                context.add_cookies([{"name": "epc_device_id", "value": token, "url": ORIGIN, "sameSite": "Lax"}])
                page = context.new_page()
                page.set_default_timeout(30000)
                journey = CoreJourney(page, context, token, config, OUT, base, server, raw)
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
                    record["result"] = "passed core retention UI/store acceptance; CSV not tested"
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
    if sys.argv[1:]:
        raise SystemExit("No target URL, data directory or additional arguments are supported")
    exercise()
