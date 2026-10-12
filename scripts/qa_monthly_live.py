"""Bounded public-browser acceptance using ONLY server-isolated invented QA data.

Run after a green CI main commit has auto-deployed to the public Render URL.
Never inspect or mutate a real report/contract, or send private data. Screenshots
and downloads are synthetic and retained only as temporary CI artifacts.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
from zipfile import ZipFile

import pymupdf
from playwright.sync_api import sync_playwright, expect, TimeoutError as BrowserTimeout


URL = os.environ.get("MONTHLY_QA_PUBLIC_URL", "https://msapo-generator.onrender.com").rstrip("/")
EXPECTED = os.environ.get("MONTHLY_QA_EXPECTED_COMMIT", "").lower()
ROOT = Path("test-artifacts/monthly-live-isolated")
ROOT.mkdir(parents=True, exist_ok=True)
EVIDENCE = {"expected_commit": EXPECTED, "public_url": URL, "checks": {}, "artifacts": {}, "synthetic_only": True}


def checkpoint(name: str, passed: bool, detail: str = "") -> None:
    EVIDENCE["checks"][name] = {"passed": bool(passed), "detail": detail[:400]}
    print(("PASS" if passed else "FAIL") + " " + name + (" — " + detail[:120] if detail else ""), flush=True)
    if not passed:
        raise AssertionError(name + ": " + detail)


def screenshot(page, name):
    p = ROOT / (name + ".png")
    page.screenshot(path=str(p), full_page=False, timeout=30000)
    EVIDENCE["artifacts"][name + ".png"] = {"bytes": p.stat().st_size}
    return p


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def download(page, label, filename):
    with page.expect_download(timeout=60000) as task:
        page.get_by_role("button", name=label, exact=True).click()
    saved = ROOT / filename
    task.value.save_as(str(saved))
    raw = saved.read_bytes()
    EVIDENCE["artifacts"][filename] = {"bytes": len(raw), "sha256": sha(raw)}
    return raw


def open_until_matching(page):
    # Render cold starts and GitHub auto-deploy can lag a successful main CI.
    deadline = time.monotonic() + 10 * 60
    last = "not checked"
    address = URL + "/?workflow=monthly&monthly_qa=isolated"
    while time.monotonic() < deadline:
        try:
            page.goto(address, wait_until="domcontentloaded", timeout=65000)
            page.get_by_text("Running code: ", exact=False).first.wait_for(timeout=16000)
            label = page.get_by_text(re.compile(r"^Running code:")).first.text_content() or ""
            last = label.strip()
            if last == "Running code: " + EXPECTED:
                return last
        except Exception as exc:
            last = type(exc).__name__ + ": " + str(exc)[:160]
        print("Waiting for tested commit to be served: " + last, flush=True)
        time.sleep(12)
    raise AssertionError("Served build not verified within deployment window: " + last)


def complete_report(page, mode):
    checkpoint("fixture " + mode + " loaded", page.get_by_text(
        "Current fixture: " + mode, exact=False).first.is_visible())
    page.get_by_role("button", name="Compare fixture facts", exact=True).click()
    page.get_by_text(re.compile(("source replay" if "replay" in mode else "known-value prefill")
                                + r": \d+/\d+ independent")).first.wait_for(timeout=25000)
    result = page.get_by_text(re.compile(r"\d+/\d+ independent")).first.text_content() or ""
    match = re.search(r"(\d+)/(\d+)", result)
    failed = page.get_by_text(re.compile(r"^CHECK\s*[—-]")).all_text_contents()
    failure_detail = "; ".join(value.strip() for value in failed)
    screenshot(page, mode.replace(" ", "-") + "-comparison")
    checkpoint("fixture " + mode + " content/provenance",
               bool(match and match[1] == match[2] and not failed),
               result + ("; unmet checks: " + failure_detail if failed else ""))
    page.get_by_role("button", name="Generate QA Word and PDF", exact=True).click()
    docx_button = page.get_by_role("button", name="Download isolated QA DOCX", exact=True)
    try:
        docx_button.wait_for(timeout=175000)
    except BrowserTimeout:
        # Distinguish an unaccepted click, a queued request and a failed
        # export. The old timeout only said the button was not visible; the
        # screenshot and status evidence are synthetic-only and bounded.
        statuses = page.get_by_text(re.compile(
            r"QA generation request received|QA export was blocked|Generating isolated"
        )).all_text_contents()
        alerts = page.locator('[data-testid="stAlert"]').all_text_contents()
        page.get_by_role("button", name="Generate QA Word and PDF", exact=True).scroll_into_view_if_needed()
        screenshot(page, "qa-generation-not-ready")
        checkpoint("QA Word download becomes ready after accepted click", False,
                   "status=" + repr(statuses[-3:])[:165] +
                   "; alerts=" + repr(alerts[-3:])[:165])
    checkpoint("QA Word download becomes ready after accepted click", True)
    page.get_by_role("button", name="Download isolated QA PDF", exact=True).wait_for(timeout=10000)
    tag = "source-replay" if "replay" in mode else "known-prefill"
    word_raw = download(page, "Download isolated QA DOCX", tag + ".docx")
    pdf_raw = download(page, "Download isolated QA PDF", tag + ".pdf")
    checkpoint(tag + " Word package", word_raw.startswith(b"PK"))
    checkpoint(tag + " PDF signature", pdf_raw.startswith(b"%PDF-"))
    with ZipFile(ROOT / (tag + ".docx")) as zip_file:
        xml = "\n".join(zip_file.read(n).decode("utf-8", "ignore") for n in zip_file.namelist()
                        if n.endswith((".xml", ".rels", ".vml"))).casefold()
        checkpoint(tag + " no foreign client in native Word text",
                   all(s not in xml for s in ("rochester regional health", "unity hospital", "unity specialty hospital")))
        checkpoint(tag + " no proposal pricing in package text",
                   not any(s.casefold() in xml for s in ("$12,345.67", "$987.65", "$13,333.32", "$456.78", "$222.22")))
    with pymupdf.open(stream=pdf_raw, filetype="pdf") as doc:
        text = "\n".join(p.get_text() for p in doc)
        EVIDENCE["artifacts"][tag + ".pdf"]["pages"] = len(doc)
        checkpoint(tag + " multi-section PDF", len(doc) >= 10, str(len(doc)))
        checkpoint(tag + " CSV counts", "3 total, 2 completed, 1 open" in text and "66.7%" in text)
        checkpoint(tag + " proposal ID and Status", "Q-TEST-731" in text and "Pending" in text)
        checkpoint(tag + " no tested prices", not any(s in text for s in
                  ("$12,345.67", "$987.65", "$13,333.32", "$456.78", "$222.22")))
        checkpoint(tag + " no foreign client identity", not any(s in text.casefold() for s in
                  ("rochester regional health", "unity hospital", "unity specialty hospital")))
    return tag


def main():
    checkpoint("expected full Git commit provided", bool(re.fullmatch(r"[0-9a-f]{40}", EXPECTED)))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
        ctx = browser.new_context(accept_downloads=True, viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16),
                         "url": URL, "secure": True, "sameSite": "Lax"}])
        page = ctx.new_page()
        page.set_default_timeout(35000)
        try:
            EVIDENCE["served_build"] = open_until_matching(page)
            checkpoint("public served exact tested commit", EVIDENCE["served_build"] == "Running code: " + EXPECTED)
            page.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first.wait_for(timeout=30000)
            checkpoint("synthetic isolated interface visible", True)
            screenshot(page, "qa-entry")
            page.get_by_role("button", name="Load known-value report", exact=True).click()
            page.get_by_text("Current fixture: known-value prefill", exact=False).first.wait_for(timeout=45000)
            complete_report(page, "known-value prefill")
            # The visible Activity editor is a real Streamlit control.
            editor = page.get_by_role("textbox", name="Activity summary", exact=True).first
            original = editor.input_value()
            edited = original + "\nSynthetic owner edit retained through a browser refresh."
            editor.fill(edited)
            editor.press("Tab")
            # A blind 1.5-second sleep raced a real Streamlit rerun and its
            # durable journal write. Require a server-computed digest of the
            # EXACT synthetic edit before reloading. This does not weaken the
            # refresh check: it distinguishes a failed write from failed restore.
            expected_digest = sha(edited.encode("utf-8"))
            receipt = "QA durable Activity SHA256: " + expected_digest
            try:
                page.get_by_text(receipt, exact=True).wait_for(timeout=90000)
            except BrowserTimeout:
                latest = page.get_by_text(re.compile(r"QA durable Activity SHA256:")).all_text_contents()
                warnings = page.locator('[data-testid="stAlert"]').all_text_contents()
                editor.scroll_into_view_if_needed()
                screenshot(page, "activity-not-durably-saved")
                checkpoint("exact Activity edit reached durable server journal", False,
                           "expected " + expected_digest[:12] + "; observed " +
                           repr(latest[-2:])[:150] + "; notices " + repr(warnings[-3:])[:150])
            checkpoint("exact Activity edit reached durable server journal", True)
            page.reload(wait_until="domcontentloaded", timeout=60000)
            page.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first.wait_for(timeout=30000)
            page.get_by_text("Current fixture: known-value prefill", exact=False).first.wait_for(timeout=35000)
            editor = page.get_by_role("textbox", name="Activity summary", exact=True).first
            # The Streamlit QA caption and editor can mount before hydration
            # fills the textarea from the recovered draft. On e765 the failure
            # screenshot plainly showed the exact edited text restored AFTER
            # input_value() was sampled as empty. Await the exact value and a
            # freshly computed server-journal acknowledgment after reload.
            restored = False
            observed = ""
            try:
                expect(editor).to_have_value(edited, timeout=60000)
                page.get_by_text(receipt, exact=True).wait_for(timeout=60000)
                observed = editor.input_value()
                restored = observed == edited
            except (AssertionError, BrowserTimeout):
                observed = editor.input_value()
            if not restored:
                editor.scroll_into_view_if_needed()
                screenshot(page, "activity-lost-after-refresh")
            checkpoint("Activity editing survives refresh", restored,
                       "expected " + expected_digest[:12] + "; observed " +
                       sha(observed.encode("utf-8"))[:12] + "; saved receipts " +
                       repr(page.get_by_text(re.compile(r"QA durable Activity SHA256:")).all_text_contents())[:160])
            page.get_by_role("button", name="Reset this test only", exact=True).click()
            page.get_by_role("button", name="Replay synthetic source files", exact=True).wait_for(timeout=40000)
            page.get_by_role("button", name="Replay synthetic source files", exact=True).click()
            page.get_by_text("Current fixture: original-source replay", exact=False).first.wait_for(timeout=45000)
            complete_report(page, "original-source replay")
            page.get_by_role("button", name="Reset this test only", exact=True).click()
            page.get_by_text("Choose known-value prefill or source replay", exact=False).wait_for(timeout=40000)
            checkpoint("isolated reset returns empty QA fixture", True)
        finally:
            try:
                screenshot(page, "end-state")
            except Exception:
                pass
            browser.close()


if __name__ == "__main__":
    try:
        main()
        EVIDENCE["result"] = "isolated live tests passed"
    except Exception as exc:
        EVIDENCE["result"] = "failed or blocked"
        EVIDENCE["error"] = type(exc).__name__ + ": " + str(exc)[:800]
        raise
    finally:
        (ROOT / "summary.json").write_text(json.dumps(EVIDENCE, indent=2) + "\n")
