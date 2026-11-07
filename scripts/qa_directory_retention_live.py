"""Opt-in hosted #291 acceptance. Only a fresh synthetic directory is touched.

This is not run by pytest, and refuses ordinary local/manual execution. The
existing serialized live workflow must explicitly opt in through its repository
variable. No fixture admission, reset, consolidation, age manipulation, or live
directory route is used. Raw-byte lifecycle proof remains a separate local test.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from urllib.parse import parse_qs, urlsplit
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

ORIGIN = "https://msapo-generator.onrender.com"
OPT_IN = "synthetic-only-v1"
BANNER = ("ISOLATED SYNTHETIC TESTING — not a client report. No live report, "
          "contact, capacity, logo or design records are accessible here.")
IMPORT_DISCLOSURE = ("A confirmed import keeps the uploaded workbook file for 30 days for checking, "
                     "then deletes it. The reviewed contacts and directory history stay.")
STORAGE_DISCLOSURE = "contact-directory workbooks are deleted 30 days after their latest import."
CONFIRM = "I reviewed all included sites and contacts and confirm this shared save"
ACTOR = "Synthetic Directory Retention QA"
SITE = "Synthetic Retention North"
PERSON = "Synthetic Accepted Site Lead"
PHONE = "202-555-0101"
EMAIL = "site@example.invalid"
SHEET = "Synthetic Retention Sites"
OUT = Path("test-artifacts/monthly-live-isolated/directory-retention")


class SafetyStop(RuntimeError):
    """No subsequent action is allowed after a failed isolation gate."""


@dataclass(frozen=True)
class Config:
    commit: str
    origin: str = ORIGIN

    @classmethod
    def from_environment(cls, env, checkout):
        required = {
            "MONTHLY_QA_DIRECTORY_ACCEPTANCE": OPT_IN,
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "evanroden/msapo-generator",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_WORKFLOW": "Monthly Isolated Live Acceptance",
        }
        if any(env.get(key) != value for key, value in required.items()):
            raise SafetyStop("Hosted synthetic-directory opt-in or workflow provenance is absent.")
        commit = env.get("MONTHLY_QA_EXPECTED_COMMIT", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or checkout != commit:
            raise SafetyStop("Expected full commit must equal this checked-out tested revision.")
        if env.get("MONTHLY_QA_PUBLIC_URL", ORIGIN).rstrip("/") != ORIGIN:
            raise SafetyStop("Directory acceptance allows only its audited exact HTTPS origin.")
        return cls(commit)

    def address(self, kind):
        if kind not in {"directory", "storage"}:
            raise SafetyStop("Unexpected administration route.")
        return self.origin + "/?workflow=monthly&monthly_qa=isolated&monthly_admin=" + kind


def validate_route(url, kind):
    if kind not in {"directory", "storage"}:
        raise SafetyStop("Unexpected administration kind.")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "msapo-generator.onrender.com"
            or parsed.path not in {"", "/"} or parsed.fragment
            or parse_qs(parsed.query, keep_blank_values=True) != {
                "workflow": ["monthly"], "monthly_qa": ["isolated"], "monthly_admin": [kind]}):
        raise SafetyStop("Navigation left the exact isolated directory/storage route.")


def validate_identity(cookies, token):
    identities = [item for item in cookies if item.get("name") == "epc_device_id"]
    if (not re.fullmatch(r"[0-9a-f]{32}", token) or len(identities) != 1
            or identities[0].get("value") != token
            or identities[0].get("domain", "").lstrip(".") != "msapo-generator.onrender.com"
            or identities[0].get("path") != "/"):
        raise SafetyStop("The fresh synthetic browser identity changed or is ambiguous.")


def request_allowed(url, kind, *, top_level=False):
    target = urlsplit(url)
    if target.scheme != "https" or target.netloc != "msapo-generator.onrender.com":
        return False
    if top_level:
        try:
            validate_route(url, kind)
        except SafetyStop:
            return False
    return True


def workbook():
    """A small real XLSX, invented in this run with no external file inputs.

    Only the first worksheet is selected. Other tabs contain hidden, inactive
    and index records to show that original bytes and reviewed data differ.
    This single-sheet journey does not claim automatic inactive-row filtering.
    """
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    detail = {"A6": "Facility", "B6": SITE, "A7": "Address", "B7": "100 Example Way",
              "A9": "Facility Director", "B9": PERSON, "A10": "Phone", "B10": PHONE,
              "A11": "Email", "B11": EMAIL}
    sheets = [(SHEET, detail, False),
              ("Hidden excluded", {"A6": "Facility", "B6": "Synthetic Hidden Site",
                                   "A9": "Facility Director", "B9": "Synthetic Hidden Person"}, True),
              ("Inactive excluded", {"A6": "Facility", "B6": "INACTIVE Synthetic Closed",
                                     "A9": "Facility Director", "B9": "Synthetic Inactive Person"}, False),
              ("Index", {"A1": "Synthetic excluded index marker"}, False)]
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        types = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        types += '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        types += '<Default Extension="xml" ContentType="application/xml"/>'
        types += '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        types += ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, 5)) + '</Types>'
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="' + rel + '/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        entries = ''.join(f'<sheet name="{name}" sheetId="{i}" r:id="r{i}" state="{"hidden" if hidden else "visible"}"/>' for i, (name, _, hidden) in enumerate(sheets, 1))
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>{entries}</sheets></workbook>')
        entries = ''.join(f'<Relationship Id="r{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, 5))
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + entries + '</Relationships>')
        for i, (_, values, _) in enumerate(sheets, 1):
            rows = {}
            for coordinate, value in values.items():
                row = int(re.search(r"\d+", coordinate)[0])
                rows.setdefault(row, []).append(f'<c r="{coordinate}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            xml = ''.join(f'<row r="{row}">{"".join(cells)}</row>' for row, cells in sorted(rows.items()))
            archive.writestr(f"xl/worksheets/sheet{i}.xml", f'<worksheet xmlns="{ns}"><sheetData>{xml}</sheetData></worksheet>')
    return stream.getvalue()


def csv_rows(raw):
    if len(raw) > 65536:
        raise SafetyStop("Unexpectedly large directory CSV.")
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise SafetyStop("CSV columns are missing or ambiguous.")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise SafetyStop("CSV row width does not match its columns.")
    # A blank column is the native optional row index. No named fields are dropped.
    if "" in reader.fieldnames and [row[""] for row in rows] != [str(i) for i in range(len(rows))]:
        raise SafetyStop("Unexpected CSV index data.")
    return [{key: value for key, value in row.items() if key != ""} for row in rows]


def verify_history(raw):
    # Streamlit's native JavaScript CSV exporter stringifies booleans as "true".
    if csv_rows(raw) != [{"Site": SITE, "Aliases": "", "Active": "true", "Contacts": "1"}]:
        raise SafetyStop("Saved history rows differ from the single invented site.")


def verify_contacts(raw):
    if csv_rows(raw) != [{"Site": SITE, "Role": "Facility Director", "Name": PERSON,
                         "Phone": PHONE, "Email": EMAIL}]:
        raise SafetyStop("Saved contacts differ from the reviewed invented contact.")


class Journey:
    def __init__(self, page, context, token, config, output):
        self.page, self.context, self.token, self.config, self.output = page, context, token, config, output
        self.kind = "directory"
        self.events = []
        self.blocked = []

    def boundary(self):
        if self.blocked:
            raise SafetyStop("An unexpected browser request was blocked; no further actions are allowed.")
        validate_route(self.page.url, self.kind)
        validate_identity(self.context.cookies([self.config.origin]), self.token)

    def guard(self):
        from playwright.sync_api import expect
        self.boundary()
        expect(self.page.get_by_text(BANNER, exact=True)).to_be_visible()
        expect(self.page.get_by_text("Running code: " + self.config.commit, exact=True)).to_have_count(1)
        expect(self.page.get_by_test_id("stException")).to_have_count(0)
        # Assertions pump browser events. Fail before the operation if anything
        # changed during their waits, not only in the post-operation guard.
        self.boundary()

    def action(self, name, operation):
        self.guard()
        self.events.append({"action": name, "status": "attempted"})
        result = operation()
        self.guard()
        self.events[-1]["status"] = "completed"
        return result

    def button(self, label):
        return self.action(label, lambda: self.page.get_by_role("button", name=label, exact=True).click())

    def radio(self, label):
        from playwright.sync_api import expect
        def select():
            group = self.page.get_by_role("radiogroup", name="Directory task", exact=True)
            # Streamlit's styled option owns the native press; its input is
            # visually hidden. Match that exact input without clicking through it.
            option = group.get_by_test_id("stRadioOption").filter(
                has=self.page.get_by_role("radio", name=label, exact=True))
            radio = option.get_by_role("radio", name=label, exact=True)
            expect(group).to_have_count(1)
            expect(option).to_have_count(1)
            expect(radio).to_have_count(1)
            expect(option).to_be_visible()
            expect(radio).to_be_enabled()
            self.guard()  # Locator waits pump events; recheck before the press.
            option.click()
            expect(radio).to_be_checked()
        return self.action(label, select)

    def fill(self, label, value):
        def enter():
            field = self.page.get_by_role("textbox", name=label, exact=True)
            field.fill(value)
            field.press("Tab")
        self.action("Set " + label, enter)

    def expand(self, label):
        box = self.page.get_by_test_id("stExpander").filter(has=self.page.locator("summary").filter(has_text=label))
        if not box.locator("details").evaluate("node => node.open"):
            self.action("Open " + label, lambda: box.locator("summary").click())
        return box

    def snapshot(self, name):
        self.guard()
        self.page.screenshot(path=str(self.output / (name + ".png")), full_page=True)

    def download_grid(self, box, name):
        from playwright.sync_api import expect
        grid = box.get_by_test_id("stDataFrame")
        expect(grid).to_have_count(1)
        def download():
            grid.hover()
            with self.page.expect_download() as receipt:
                grid.get_by_role("button", name="Download as CSV", exact=True).click()
            item = receipt.value
            if item.failure():
                raise SafetyStop("Native CSV download failed.")
            path = self.output / (name + ".csv")
            item.save_as(str(path))
            return path.read_bytes()
        return self.action("Download " + name, download)

    def saved_receipt(self, contract, stage):
        from playwright.sync_api import expect
        self.radio("Review saved directory")
        saved = self.page.get_by_role("combobox", name="Saved contract directory", exact=True)
        expect(saved).to_be_visible()
        # Inspect native options, not only the preselected label.
        self.action("Inspect saved directory choices", saved.click)
        options = self.page.get_by_role("option")
        expect(options).to_have_count(1)
        expect(options).to_have_text([contract])
        self.action("Select synthetic directory", lambda: self.page.get_by_role("option", name=contract, exact=True).click())
        history = self.expand("History and restoration")
        caption = history.get_by_text(re.compile(r"^Version 1 · " + re.escape(ACTOR) + r" · .+ · save$"))
        expect(caption).to_have_count(1)
        version = history.get_by_role("spinbutton", name="Directory version to inspect", exact=True)
        expect(version).to_have_value("1")
        history_raw = self.download_grid(history, stage + "-history")
        verify_history(history_raw)
        contacts = self.expand("All included contacts before saving")
        contacts_raw = self.download_grid(contacts, stage + "-contacts")
        verify_contacts(contacts_raw)
        self.snapshot(stage)
        return {"caption": caption.inner_text(), "history": history_raw, "contacts": contacts_raw}

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


def main():
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    config = Config.from_environment(os.environ, checkout)
    from playwright.sync_api import sync_playwright
    raw = workbook()
    token = secrets.token_hex(16)
    contract = "Synthetic Retention 291 " + secrets.token_hex(5)
    OUT.mkdir(parents=True, exist_ok=False)  # Never mix receipts from two attempts.
    report = {"result": "not completed", "commit": config.commit, "origin": config.origin,
              "synthetic_only": True, "contract": contract, "source_sha256": sha256(raw).hexdigest(),
              "source_bytes": len(raw), "raw_storage_verified": False,
              "limits": ["No hosted raw workbook download exists; byte/lifecycle proof is local only.",
                         "No aged hosted deletion, fixture admission, reset or consolidation."]}
    journey = None
    blocked = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True, service_workers="block", viewport={"width": 1440, "height": 1000})
            if context.cookies():
                raise SafetyStop("New context unexpectedly contains cookies.")
            context.add_cookies([{"name": "epc_device_id", "value": token, "url": config.origin,
                                 "secure": True, "sameSite": "Lax"}])
            page = context.new_page()
            page.set_default_timeout(30000)
            journey = Journey(page, context, token, config, OUT)
            journey.blocked = blocked
            def route_gate(route):
                allowed = request_allowed(route.request.url, journey.kind,
                    top_level=route.request.is_navigation_request() and route.request.frame.parent_frame is None)
                if not allowed:
                    blocked.append("Unexpected origin or top-level route")  # Do not log arbitrary URL data.
                    route.abort()
                else:
                    route.continue_()
            context.route("**/*", route_gate)
            def websocket_gate(socket):
                target = urlsplit(socket.url)
                if (target.scheme, target.netloc, target.path) != ("wss", "msapo-generator.onrender.com", "/_stcore/stream"):
                    blocked.append("Unexpected websocket")
                    socket.close()
                else:
                    socket.connect_to_server()
            context.route_web_socket("**/*", websocket_gate)
            report.update(journey.run(raw, contract))
            if blocked:
                raise SafetyStop("An unexpected browser request was blocked.")
            report["result"] = "passed native served disclosure, save and history persistence"
            context.close()
            browser.close()
    except Exception as exc:
        # Avoid a screenshot/trace of an unverified context or arbitrary error text.
        report["failure_type"] = type(exc).__name__
        raise
    finally:
        report["events"] = journey.events if journey else []
        report["blocked_requests"] = len(blocked)
        (OUT / "receipt.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
