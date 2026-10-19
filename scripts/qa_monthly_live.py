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
        r"^(QA fixture state:|QA fixture action|QA reset acknowledged:|QA comparison completed:|QA generation action|QA working report SHA256:|QA working Activity SHA256:|QA durable Activity SHA256:|QA Activity callback |Current fixture:)"
    )).all_text_contents()
    alerts = page.locator('[data-testid="stAlert"]').all_text_contents()
    safe_alerts = [
        "fixture install error" if "fixture could not be installed" in item.casefold()
        else "reset error" if "reset" in item.casefold()
        else "other alert"
        for item in alerts[-5:]
    ]
    diagnostics = {
        "action": action, "error_type": type(error).__name__,
        "qa_status": captions[-12:], "alert_kinds": safe_alerts,
    }
    # Synthetic QA only: diagnose visible-editor hydration against the
    # server-acknowledged Activity journal without recording any source text.
    # The existing strict pass/fail assertions remain unchanged.
    if action.startswith("activity-"):
        try:
            editors = page.get_by_role("textbox", name="Activity summary", exact=True)
            diagnostics["activity_widget_count"] = editors.count()
            if editors.count():
                displayed = editors.first.input_value(timeout=3000)
                diagnostics["visible_activity_sha256"] = hashlib.sha256(
                    displayed.encode("utf-8")).hexdigest()
                diagnostics["visible_activity_length"] = len(displayed)
            for label, key in (
                ("QA working Activity SHA256:", "working_activity_sha256"),
                ("QA durable Activity SHA256:", "durable_activity_sha256"),
            ):
                matched = page.get_by_text(re.compile(
                    r"^" + re.escape(label) + r" [0-9a-f]{64}$"
                )).all_text_contents()
                diagnostics[key] = matched[-1].split(": ", 1)[1] if matched else None
        except Exception:
            # Diagnostics must never obscure or downgrade the primary failure.
            diagnostics["activity_hashes_unavailable"] = True
    EVIDENCE.setdefault("diagnostics", []).append(diagnostics)
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
            from scripts.qa_public_build import running_code_marker
            label = running_code_marker(page).text_content() or ""
            last = label.strip()
            if last == "Running code: " + EXPECTED:
                return last
        except Exception as exc:
            last = type(exc).__name__ + ": " + str(exc)[:160]
        print("Waiting for tested commit to be served: " + last, flush=True)
        time.sleep(12)
    raise AssertionError("Served build not verified within deployment window: " + last)


def request_qa_generation(page, stage):
    """Require a new action receipt for the visible report, then its completion."""
    state_text = page.get_by_text(re.compile(r"^QA fixture state: ")).first.text_content() or ""
    state = STATE.fullmatch(state_text)
    if state is None:
        raise AssertionError("No committed QA report identity before generation.")
    fingerprint = (page.get_by_text(re.compile(r"^QA working report SHA256: [0-9a-f]{64}$"))
                   .last.text_content() or "").split(": ")[-1]
    prior = page.get_by_text(re.compile(r"^QA generation action ")).all_text_contents()
    prior_id = re.search(r"action ([0-9a-f]{12})", prior[-1])[1] if prior else ""
    event("generation_requested", stage_id=stage, generation=state[2], revision=int(state[3]),
          fingerprint=fingerprint[:12])
    page.get_by_role("button", name="Generate QA Word and PDF", exact=True).click()
    pattern = (r"^QA generation action (accepted|completed|rejected): action " +
               (r"(?!" + prior_id + r"\b)" if prior_id else "") +
               r"([0-9a-f]{12}) · generation " + state[2] + r" · revision " + state[3] +
               r" · fingerprint " + fingerprint[:12] + r" · received ")
    receipt = page.get_by_text(re.compile(pattern)).last
    try:
        receipt.wait_for(timeout=25000)
        accepted = re.match(pattern, receipt.text_content() or "")
        if accepted is None:
            raise AssertionError("QA generation receipt does not match the intended report.")
        action = accepted[2]
        event("generation_acknowledged", stage_id=stage, action=action, state=accepted[1])
        final_pattern = (r"^QA generation action (completed|rejected): action " + action +
                         r" · generation " + state[2] + r" · revision " + state[3] +
                         r" · fingerprint " + fingerprint[:12] + r" · received ")
        final = page.get_by_text(re.compile(final_pattern)).last
        final.wait_for(timeout=175000)
        completed = (final.text_content() or "").startswith("QA generation action completed:")
        checkpoint(stage + " generation completed for accepted revision", completed,
                   final.text_content() or "")
        event("generation_completed", stage_id=stage, action=action)
    except (BrowserTimeout, AssertionError) as exc:
        state_diagnostics(page, "generation-" + stage, exc)
        raise


def correct_replay_source_scope(page):
    """An explicit synthetic reviewer choice, never an extraction assertion."""
    warning = page.locator('[data-testid="stAlert"]').filter(has_text=
        "Establish the site scope of synthetic-activity.txt before including its content.")
    expect(warning).to_have_count(1, timeout=25000)
    expect(page.get_by_role("button", name="Create Word and PDF", exact=True)).to_be_disabled()
    before = (page.get_by_text(re.compile(r"^QA working report SHA256: [0-9a-f]{64}$"))
              .last.text_content() or "").split(": ")[-1]
    checkpoint("replay unknown source blocks generation", bool(re.fullmatch(r"[0-9a-f]{64}", before)))
    # The source text intentionally has no printed site. For this synthetic
    # journey the reviewer chooses Demo North explicitly; the original TXT
    # stays unchanged and the later 18/18 check still verifies its byte digest.
    warning.get_by_role("link", name="Correct site", exact=True).click()
    details = page.locator('[data-testid="stForm"]').filter(has=
        page.locator('[data-testid="stMultiSelect"]').filter(has_text="Source sites"))
    # The targeted link exposes exactly this source's existing form. Other
    # collapsed correction forms remain mounted, so select the visible one.
    details = details.filter(visible=True)
    expect(details).to_have_count(1)
    sites = details.locator('[data-testid="stMultiSelect"]').filter(has_text="Source sites")
    combo = sites.get_by_role("combobox")
    expect(combo).to_be_focused()
    combo.fill("Demo North")
    expect(combo).to_have_value("Demo North")
    page.get_by_role("option", name="Demo North", exact=True).click()
    # Finish the native multiselect with one ordinary Tab. BaseWeb keeps its
    # option portal open after selection and makes the surrounding workspace
    # aria-hidden until the picker closes; a role lookup there is premature.
    page.keyboard.press("Tab")
    expect(page.get_by_role("listbox")).to_have_count(0)
    details.get_by_role("button", name="Use these source details", exact=True).click()
    expect(warning).to_have_count(0, timeout=25000)
    changed = page.get_by_text(re.compile(r"^QA working report SHA256: (?!" + before + r"$)[0-9a-f]{64}$")).last
    changed.wait_for(timeout=25000)
    after = (changed.text_content() or "").split(": ")[-1]
    page.get_by_text("QA durable report SHA256: " + after, exact=True).wait_for(timeout=25000)
    event("source_scope_correction_committed", source="synthetic-activity.txt",
          selected_site="Demo North", before=before[:12], after=after[:12])
    checkpoint("replay targeted source correction persisted", after != before)
    # The existing issue retains its old provenance until the reviewer picks
    # the current source. A site correction must not silently waive that gate.
    stale = page.get_by_text("A supporting source changed or is missing.", exact=True)
    expect(stale).to_have_count(1)
    evidence = page.locator('[data-testid="stExpander"]').filter(has=
        page.get_by_role("checkbox", name="Remove unavailable source links", exact=True))
    summary = evidence.locator("summary")
    if not summary.evaluate("el => el.parentElement.open"):
        summary.click()
    source_pages = evidence.locator('[data-testid="stMultiSelect"]').filter(has_text="Supporting source pages")
    source_pages.get_by_role("combobox").fill("synthetic-activity.txt")
    page.get_by_role("option", name="synthetic-activity.txt · page 1", exact=True).click()
    page.keyboard.press("Tab")
    expect(page.get_by_role("listbox")).to_have_count(0)
    evidence.get_by_role("checkbox", name="Remove unavailable source links", exact=True).check()
    expect(stale).to_have_count(0, timeout=25000)
    final = page.get_by_text(re.compile(r"^QA working report SHA256: (?!" + after + r"$)[0-9a-f]{64}$")).last
    final.wait_for(timeout=25000)
    fingerprint = (final.text_content() or "").split(": ")[-1]
    page.get_by_text("QA durable report SHA256: " + fingerprint, exact=True).wait_for(timeout=25000)
    checkpoint("replay current issue evidence persisted", True, fingerprint[:12])


def complete_report(page, mode):
    checkpoint("fixture " + mode + " loaded", page.get_by_text(
        "Current fixture: " + mode, exact=False).first.is_visible())
    if "replay" in mode:
        correct_replay_source_scope(page)
    event("comparison_requested", mode=mode)
    page.get_by_role("button", name="Compare fixture facts", exact=True).click()
    expected = "source replay" if "replay" in mode else "known-value prefill"
    receipt = page.get_by_text(re.compile(
        r"^QA comparison completed: " + expected + r" · 18/18 · action [0-9a-f]{12} · at "
    )).first
    try:
        receipt.wait_for(timeout=25000)
    except BrowserTimeout as exc:
        state_diagnostics(page, "comparison-" + mode.replace(" ", "-"), exc)
        raise
    comparison_receipt = receipt.text_content() or ""
    action = re.search(r"action ([0-9a-f]{12})", comparison_receipt)
    checkpoint("fixture " + mode + " accepted comparison",
               bool(action), comparison_receipt[:180])
    event("comparison_completed", mode=mode, action=action[1])
    result = page.get_by_text(re.compile(r"\d+/\d+ independent")).first.text_content() or ""
    match = re.search(r"(\d+)/(\d+)", result)
    failed = page.get_by_text(re.compile(r"^CHECK\s*[—-]")).all_text_contents()
    failure_detail = "; ".join(value.strip() for value in failed)
    screenshot(page, mode.replace(" ", "-") + "-comparison")
    checkpoint("fixture " + mode + " content/provenance",
               bool(match and match[1] == match[2] == "18" and not failed),
               result + ("; unmet checks: " + failure_detail if failed else ""))
    request_qa_generation(page, mode.replace(" ", "-"))
    docx_button = page.get_by_role("button", name="Download isolated QA DOCX", exact=True)
    try:
        docx_button.wait_for(timeout=175000)
    except BrowserTimeout:
        # Distinguish an unaccepted click, a queued request and a failed
        # export. The old timeout only said the button was not visible; the
        # screenshot and status evidence are synthetic-only and bounded.
        statuses = page.get_by_text(re.compile(
            r"QA generation action|QA export was blocked|Generating isolated"
        )).all_text_contents()
        alerts = page.locator('[data-testid="stAlert"]').all_text_contents()
        page.get_by_role("button", name="Generate QA Word and PDF", exact=True).scroll_into_view_if_needed()
        screenshot(page, "qa-generation-not-ready")
        checkpoint(mode + " QA Word download becomes ready after accepted click", False,
                   "status=" + repr(statuses[-3:])[:165] +
                   "; alerts=" + repr(alerts[-3:])[:165])
    checkpoint(mode + " QA Word download becomes ready after accepted click", True)
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


def verify_stale_second_tab_after_reset(ctx, primary, empty_state: dict) -> None:
    """Real same-cookie browser tabs may not revive a reset QA generation.

    This only uses invented QA fixtures. It is a separate browser-recovery
    proof in the second first-attempt run, not another expensive render pass.
    """
    event("two_tab_begin", generation=empty_state["generation"])
    loaded = load_fixture(primary, "prefill",
                          previous_generation=empty_state["generation"])
    other = ctx.new_page()
    other.set_default_timeout(35000)
    try:
        address = URL + "/?workflow=monthly&monthly_qa=isolated"
        other.goto(address, wait_until="domcontentloaded", timeout=60000)
        other.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first.wait_for(timeout=30000)
        stale_state = await_fixture_state(other, "known-value prefill", timeout=45000)
        checkpoint("second tab opens same verified QA fixture generation",
                   stale_state["generation"] == loaded["generation"] and
                   stale_state["revision"] == loaded["revision"])
        second_editor = other.get_by_role("textbox", name="Activity summary", exact=True).first
        expect(second_editor).to_have_value(
            "Three September work orders: 3 total, 2 completed, 1 open (66.7%).",
            timeout=45000)
        # Tab A resets only the shared synthetic browser's generation, while
        # Tab B still holds a fully mounted older editor in its own session.
        reset_state = reset_fixture(primary, loaded, "other-tab-still-mounted")
        event("second_tab_stale_action_attempt", old=loaded["generation"],
              new=reset_state["generation"])
        # A stale widget interaction after reset must never be committed to the
        # new namespace. If the old control was already unmounted, that is an
        # acceptable fail-closed rebind, not a reason to click again.
        try:
            if second_editor.is_visible():
                second_editor.fill(
                    "INVENTED OLD-TAB EDIT AFTER ISOLATED RESET; MUST NOT SURVIVE.",
                    timeout=10000)
                second_editor.press("Tab", timeout=10000)
        except BrowserTimeout as exc:
            # A control detached by a correct generation swap can reject the
            # old tab interaction. A subsequent fresh read is the authority.
            event("second_tab_action_control_replaced", error=type(exc).__name__)
        other.reload(wait_until="domcontentloaded", timeout=60000)
        other.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first.wait_for(timeout=30000)
        observed_other = await_fixture_state(
            other, "empty", previous_generation=loaded["generation"], timeout=35000)
        primary.reload(wait_until="domcontentloaded", timeout=60000)
        primary.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first.wait_for(timeout=30000)
        observed_primary = await_fixture_state(
            primary, "empty", previous_generation=loaded["generation"], timeout=35000)
        no_exports = not other.get_by_role(
            "button", name="Download isolated QA DOCX", exact=True).count()
        no_editor = not other.get_by_role(
            "textbox", name="Activity summary", exact=True).count()
        checkpoint("stale second-tab edit cannot repopulate reset namespace",
                   observed_other["generation"] == observed_primary["generation"] ==
                   reset_state["generation"] and
                   observed_other["revision"] == observed_primary["revision"] == 0
                   and no_exports and no_editor)
        event("two_tab_reset_still_empty", generation=reset_state["generation"])
    except Exception:
        try:
            screenshot(other, "second-tab-reset-not-ready")
        except Exception:
            pass
        raise
    finally:
        other.close()


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
            complete_report(page, "known-value prefill")
            # A mounted Streamlit textbox can briefly report an empty value
            # while initial draft hydration is still applying the committed
            # fixture. The failed fd759 run built its edit from this transient
            # blank, expected SHA c0803d..., and left the server journal at the
            # original 212afb... hash. Never overwrite an unhydrated input or
            # mistake a locally visible textarea value for a durable edit.
            editor = page.get_by_role("textbox", name="Activity summary", exact=True).first
            expected_seed = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
            try:
                # The committed snapshot and earlier 18/18 comparison prove
                # the initial fixture. An active-work journal is not required
                # until the operator actually changes that saved snapshot.
                expect(editor).to_have_value(expected_seed, timeout=60000)
            except (AssertionError, BrowserTimeout) as exc:
                state_diagnostics(page, "activity-seed-not-ready", exc)
                checkpoint("initial Activity editor hydrated", False,
                           "Expected the populated known-value editor before composing a new edit.")
            checkpoint("initial Activity editor hydrated", True)
            event("activity_seed_ready", sha256=sha(expected_seed.encode("utf-8"))[:12])
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
            # Clearing is an intentional edit, not an uninitialized widget.
            # Require durable acknowledgment and a fresh-session empty editor
            # before re-entry, then verify the new wording in actual outputs.
            for step, wording in (("clear", ""), ("reentry", "Synthetic re-entered Activity after deliberate clear.")):
                editor = page.get_by_role("textbox", name="Activity summary", exact=True).first
                editor.fill(wording)
                editor.press("Tab")
                digest = sha(wording.encode("utf-8"))
                durable = "QA durable Activity SHA256: " + digest
                page.get_by_text(durable, exact=True).wait_for(timeout=90000)
                expect(editor).to_have_value(wording)
                page.reload(wait_until="domcontentloaded", timeout=60000)
                editor = page.get_by_role("textbox", name="Activity summary", exact=True).first
                try:
                    expect(editor).to_have_value(wording, timeout=60000)
                    page.get_by_text(durable, exact=True).wait_for(timeout=60000)
                except (BrowserTimeout, AssertionError) as exc:
                    state_diagnostics(page, "activity-" + step, exc)
                    raise
                checkpoint("Activity " + step + " survives acknowledged refresh", True)
            request_qa_generation(page, "known-prefill-reentry")
            reentered_word = download(page, "Download isolated QA DOCX", "reentry.docx")
            reentered_pdf = download(page, "Download isolated QA PDF", "reentry.pdf")
            from io import BytesIO
            from xml.etree import ElementTree
            # The live runner intentionally installs only the browser and PDF
            # analyzer. Read real Word paragraphs with the standard library.
            with ZipFile(BytesIO(reentered_word)) as package:
                document = ElementTree.fromstring(package.read("word/document.xml"))
            word_ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            word_text = "\n".join("".join(p.itertext()) for p in document.findall(".//w:p", word_ns))
            with pymupdf.open(stream=reentered_pdf, filetype="pdf") as pdf:
                pdf_text = "\n".join(p.get_text() for p in pdf)
            for label, content in (("Word", word_text), ("PDF", pdf_text)):
                checkpoint("Re-entered Activity in " + label, wording in content and
                           "Synthetic owner edit retained through a browser refresh." not in content)
            empty_state = reset_fixture(page, prefill_state, "before-replay")
            replay_state = load_fixture(page, "replay",
                                        previous_generation=empty_state["generation"])
            complete_report(page, "original-source replay")
            final_state = reset_fixture(page, replay_state, "final")
            checkpoint("isolated reset returns empty QA fixture",
                       final_state["generation"] != replay_state["generation"] and
                       final_state["revision"] == 0)
            # One extra non-rendering two-tab reset proof, after the second
            # independent first-attempt full report flow has already passed.
            if RUN_LABEL == "second":
                verify_stale_second_tab_after_reset(ctx, page, final_state)
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
