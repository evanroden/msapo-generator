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
from datetime import datetime, timezone
from zipfile import ZipFile

import pymupdf
from playwright.sync_api import sync_playwright, expect, TimeoutError as BrowserTimeout


URL = os.environ.get("MONTHLY_QA_PUBLIC_URL", "https://msapo-generator.onrender.com").rstrip("/")
EXPECTED = os.environ.get("MONTHLY_QA_EXPECTED_COMMIT", "").lower()
RUN_LABEL = os.environ.get("MONTHLY_QA_RUN_LABEL", "single")
if not re.fullmatch(r"[a-z0-9-]{1,24}", RUN_LABEL):
    raise ValueError("Invalid synthetic QA run label.")
ROOT = Path("test-artifacts/monthly-live-isolated") / RUN_LABEL
ROOT.mkdir(parents=True, exist_ok=True)
EVIDENCE = {"expected_commit": EXPECTED, "public_url": URL, "run_label": RUN_LABEL,
            "checks": {}, "events": [], "artifacts": {}, "synthetic_only": True}
STATE = re.compile(r"^QA fixture state: (empty|known-value prefill|original-source replay) · "
                   r"generation ([0-9a-f]{12}) · revision (\d+)$")


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


def event(stage: str, **details) -> None:
    """Only action stages, opaque IDs and revisions; never private payloads."""
    EVIDENCE["events"].append({
        "at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "stage": stage, **details,
    })
    print("QA EVENT " + stage + " " + json.dumps(details, sort_keys=True), flush=True)


def state_diagnostics(page, action: str, error: Exception) -> None:
    # Never write a full page dump or internal exception paths. Only already
    # synthetic QA status captions and alert *kinds* may reach CI artifacts.
    captions = page.get_by_text(re.compile(
        r"^(QA fixture state:|QA fixture action|QA reset acknowledged:|Current fixture:)"
    )).all_text_contents()
    alerts = page.locator('[data-testid="stAlert"]').all_text_contents()
    safe_alerts = [
        "fixture install error" if "fixture could not be installed" in item.casefold()
        else "reset error" if "reset" in item.casefold()
        else "other alert"
        for item in alerts[-5:]
    ]
    EVIDENCE.setdefault("diagnostics", []).append({
        "action": action, "error_type": type(error).__name__,
        "qa_status": captions[-6:], "alert_kinds": safe_alerts,
    })
    screenshot(page, "not-ready-" + action)


def await_fixture_state(page, mode: str, *, previous_generation: str | None = None,
                        timeout: int = 45000) -> dict:
    """Wait for a committed, generation-bound state, not an always-visible button."""
    if mode not in ("empty", "known-value prefill", "original-source replay"):
        raise ValueError("Invalid fixture state.")
    locator = page.get_by_text(re.compile(r"^QA fixture state: ")).first
    different = ("(?!" + re.escape(previous_generation) + r"\b)"
                 if previous_generation else "")
    revision = "0" if mode == "empty" else r"[1-9]\d*"
    pattern = re.compile(r"^QA fixture state: " + re.escape(mode) +
                         r" · generation " + different +
                         r"[0-9a-f]{12} · revision " + revision + r"$")
    try:
        expect(locator).to_have_text(pattern, timeout=timeout)
        observed = locator.text_content() or ""
        matched = STATE.fullmatch(observed)
        if not matched or matched[1] != mode:
            raise AssertionError("QA status did not match the requested fixture.")
    except (AssertionError, BrowserTimeout) as exc:
        state_diagnostics(page, mode.replace(" ", "-"), exc)
        raise
    return {"mode": matched[1], "generation": matched[2], "revision": int(matched[3])}


def load_fixture(page, mode: str, *, previous_generation: str | None = None) -> dict:
    label = "Load known-value report" if mode == "prefill" else "Replay synthetic source files"
    expected = "known-value prefill" if mode == "prefill" else "original-source replay"
    event("fixture_requested", mode=mode, generation=previous_generation)
    page.get_by_role("button", name=label, exact=True).click()
    state = await_fixture_state(page, expected)
    receipt = page.get_by_text(re.compile(
        r"^QA fixture action accepted and committed: " + mode + r" · action [0-9a-f]{12} · revision "
    )).first
    try:
        receipt.wait_for(timeout=15000)
        text = receipt.text_content() or ""
        match = re.search(r"action ([0-9a-f]{12}) · revision (\d+)", text)
        if (not match or int(match[2]) != state["revision"]
                or (previous_generation and state["generation"] != previous_generation)):
            raise AssertionError("Fixture action was not committed in the expected QA generation.")
    except (AssertionError, BrowserTimeout) as exc:
        state_diagnostics(page, "fixture-receipt-" + mode, exc)
        raise
    event("fixture_committed", mode=mode, action=match[1],
          generation=state["generation"], revision=state["revision"])
    return state


def reset_fixture(page, from_state: dict, stage: str) -> dict:
    event("reset_requested", stage_id=stage, generation=from_state["generation"])
    page.get_by_role("button", name="Reset this test only", exact=True).click()
    # The Replay button existed before reset. Its visibility provided ZERO
    # evidence that reset was acknowledged, causing an apparent lost click.
    state = await_fixture_state(page, "empty", previous_generation=from_state["generation"],
                                timeout=40000)
    ack = page.get_by_text(re.compile(
        r"^QA reset acknowledged: empty fixture · generation " + state["generation"] +
        r" · action [0-9a-f]{12}"
    )).first
    try:
        ack.wait_for(timeout=15000)
        receipt = ack.text_content() or ""
        match = re.search(r"action ([0-9a-f]{12})", receipt)
        if not match:
            raise AssertionError("Reset acknowledgment lacks a new action identifier.")
        page.get_by_text("Choose known-value prefill or source replay", exact=False).wait_for(timeout=15000)
        if page.get_by_text(re.compile(r"^Current fixture:")).count():
            raise AssertionError("An old fixture remained mounted after acknowledged reset.")
        if page.get_by_role("button", name="Download isolated QA DOCX", exact=True).count():
            raise AssertionError("An old export remained available after reset.")
    except (AssertionError, BrowserTimeout) as exc:
        state_diagnostics(page, "reset-" + stage, exc)
        raise
    event("reset_acknowledged", stage_id=stage, action=match[1],
          generation=state["generation"], revision=state["revision"])
    return state


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


def complete_report(page, mode, fixture_state):
    checkpoint("fixture " + mode + " loaded", page.get_by_text(
        "Current fixture: " + mode, exact=False).first.is_visible())
    result_mode = "source replay" if "replay" in mode else "known-value prefill"
    event("comparison_requested", mode=mode, generation=fixture_state["generation"],
          revision=fixture_state["revision"])
    page.get_by_role("button", name="Compare fixture facts", exact=True).click()
    # Unlike a transient button=True, this post-editor receipt is emitted only
    # after the actual comparison is evaluated for the current report revision.
    receipt = page.get_by_text(re.compile(
        r"^QA comparison evaluated: " + result_mode +
        r" · \d+/\d+ · action [0-9a-f]{12} · generation " +
        fixture_state["generation"] + r" · revision " +
        str(fixture_state["revision"]) + r" ·"
    )).first
    try:
        receipt.wait_for(timeout=25000)
        status = receipt.text_content() or ""
        counted = re.search(r" · (\d+)/(\d+) · action ([0-9a-f]{12}) ", status)
        if not counted:
            raise AssertionError("Comparison receipt had no independently checked counts.")
    except (AssertionError, BrowserTimeout) as exc:
        state_diagnostics(page, "comparison-" + mode.replace(" ", "-"), exc)
        raise
    result = page.get_by_text(re.compile(
        re.escape(result_mode) + r": \d+/\d+ independent")).first.text_content() or ""
    match = re.search(r"(\d+)/(\d+)", result)
    failed = page.get_by_text(re.compile(r"^CHECK\s*[—-]")).all_text_contents()
    failure_detail = "; ".join(value.strip() for value in failed)
    screenshot(page, mode.replace(" ", "-") + "-comparison")
    checkpoint("fixture " + mode + " content/provenance",
               bool(match and match[1] == match[2] == "18" and
                    counted[1] == counted[2] == "18" and not failed),
               result + ("; unmet checks: " + failure_detail if failed else ""))
    event("comparison_evaluated", mode=mode, action=counted[3],
          generation=fixture_state["generation"], revision=fixture_state["revision"],
          matched=int(counted[1]), total=int(counted[2]))
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
            start_state = await_fixture_state(page, "empty")
            prefill_state = load_fixture(page, "prefill",
                                         previous_generation=start_state["generation"])
            complete_report(page, "known-value prefill", prefill_state)
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
            empty_state = reset_fixture(page, prefill_state, "before-replay")
            replay_state = load_fixture(page, "replay",
                                        previous_generation=empty_state["generation"])
            complete_report(page, "original-source replay", replay_state)
            final_state = reset_fixture(page, replay_state, "final")
            checkpoint("isolated reset returns empty QA fixture",
                       final_state["generation"] != replay_state["generation"] and
                       final_state["revision"] == 0)
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
