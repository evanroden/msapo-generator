"""Opt-in served-caption acceptance: native UI, isolated invented report only.

This script never opens genuine fixtures or changes live business records. A
failed-save fault is deliberately not injected into the production store.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

import pymupdf
from playwright.sync_api import sync_playwright, expect
from scripts import qa_monthly_live as live
from scripts.qa_public_build import running_code_marker

EXPECTED = os.environ["MONTHLY_QA_EXPECTED_COMMIT"]
PHASE = os.environ["CAPTION_PHASE"]
OUT = Path("test-artifacts/output-caption-production") / PHASE
SEED = "Three September work orders: 3 total, 2 completed, 1 open (66.7%)."
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
assert re.fullmatch(r"[0-9a-f]{40}", EXPECTED)
assert PHASE in {"before", "after"}
OUT.mkdir(parents=True, exist_ok=True)


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    print("PASS " + message, flush=True)


def digest(raw):
    return {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}


def download(page, label, filename):
    with page.expect_download(timeout=30000) as pending:
        page.get_by_role("button", name=label, exact=True).click()
    item = pending.value
    target = OUT / filename
    item.save_as(str(target))
    require(item.failure() is None, label + " completed")
    return target.read_bytes()


def save_version(page, revision):
    action = page.get_by_role("button", name="Save shared version", exact=True)
    expect(action).to_be_enabled(timeout=60000)
    action.click()
    expect(page.locator(".enfra-browser-save-status")).to_contain_text(
        f"Version {revision} is saved", timeout=60000)


def run():
    result = {"expected_commit": EXPECTED, "phase": PHASE,
              "started_at": datetime.now(timezone.utc).isoformat(),
              "synthetic_only": True, "native_generation": True,
              "failed_save_fault_injection": False, "passed": False}
    safe = False
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(accept_downloads=True,
                                      viewport={"width": 1440, "height": 1000})
        context.add_cookies([{"name": "epc_device_id", "value": secrets.token_hex(16),
                             "url": live.URL, "secure": True, "sameSite": "Lax"}])
        host = urlsplit(live.URL).netloc
        off_host = []

        def route(request):
            target = urlsplit(request.request.url)
            if target.scheme in {"data", "blob", "about"} or target.netloc == host:
                request.continue_()
            else:
                off_host.append(target.netloc)
                request.abort()

        context.route("**/*", route)
        page = context.new_page()
        page.set_default_timeout(35000)
        try:
            result["served_before"] = live.open_until_matching(page)
            expect(page.get_by_text("ISOLATED SYNTHETIC TESTING", exact=False).first).to_be_visible()
            empty = live.await_fixture_state(page, "empty")
            state = live.load_fixture(page, "prefill", previous_generation=empty["generation"])
            safe = True
            result["generation"] = state["generation"]
            result["initial_revision"] = state["revision"]
            editor = page.get_by_role("textbox", name="Activity summary", exact=True)
            expect(editor).to_have_value(SEED, timeout=60000)
            # Normal native checkpoints, not a QA-only generation shortcut.
            save_version(page, state["revision"] + 1)
            save_version(page, state["revision"] + 2)
            prior = state["revision"] + 2
            expected_saved = prior + 1
            acknowledge = page.get_by_role("checkbox", name="I reviewed the warnings above", exact=True)
            if acknowledge.count() and not acknowledge.is_checked():
                acknowledge.locator("xpath=ancestor::label").click()
                expect(acknowledge).to_be_checked()
            generate = page.get_by_role("button", name="Create Word and PDF", exact=True)
            expect(generate).to_be_enabled(timeout=60000)
            require(page.get_by_role("button", name="Download DOCX", exact=True).count() == 0,
                    "No earlier output can satisfy this first generation")
            # Passive observer only: it neither dispatches events nor alters UI/state.
            page.evaluate("""() => {
              window.captionObservations = [];
              const record = () => {
                const status = document.querySelector('.enfra-browser-save-status')?.textContent || '';
                const caption = Array.from(document.querySelectorAll('a[href="#shared-report-history"]'))
                    .map(e => e.textContent).filter(t => /^Shared version \\d+$/.test(t));
                const value = {status, caption};
                if (caption.length && JSON.stringify(value) !== JSON.stringify(window.captionObservations.at(-1)))
                    window.captionObservations.push(value);
              };
              window.captionObserver = new MutationObserver(record);
              window.captionObserver.observe(document.body, {subtree: true, childList: true, characterData: true});
              record();
            }""")
            generate.click()
            expect(page.get_by_role("button", name="Download DOCX", exact=True)).to_be_visible(timeout=180000)
            expect(page.get_by_role("button", name="Download PDF", exact=True)).to_be_visible(timeout=30000)
            expect(page.locator(".enfra-browser-save-status")).to_contain_text(
                f"Version {expected_saved} is saved", timeout=30000)
            caption = page.locator('a[href="#shared-report-history"]').filter(
                has_text=re.compile(r"^Shared version \d+$"))
            expect(caption).to_have_count(1)
            shown = caption.inner_text()
            result["first_render"] = {
                "badge": page.locator(".enfra-browser-save-status").inner_text(),
                "caption": shown, "expected_revision": expected_saved,
                "observations": page.evaluate("window.captionObservations"),
                "history_opened": False, "manual_reload_before_assertion": False,
            }
            caption.scroll_into_view_if_needed()
            page.screenshot(path=str(OUT / "first-generation.png"))
            # Do not invoke history or a further full rerun before this check.
            if PHASE == "before":
                require(shown == f"Shared version {prior}", "Before: newer badge accompanies stale prior caption")
            else:
                require(shown == f"Shared version {expected_saved}", "After: first-render caption matches successful save")
                bad = [x for x in result["first_render"]["observations"]
                       if f"Version {expected_saved} is saved" in x["status"]
                       and any(y != f"Shared version {expected_saved}" for y in x["caption"])]
                require(not bad, "No stale caption was observed beside the new saved badge")
            word = download(page, "Download DOCX", "generated.docx")
            pdf = download(page, "Download PDF", "generated.pdf")
            result["word"] = digest(word)
            result["pdf"] = digest(pdf)
            with ZipFile(BytesIO(word)) as archive:
                require(archive.testzip() is None, "Actual downloaded Word archive is intact")
                tree = ElementTree.fromstring(archive.read("word/document.xml"))
                text = "\n".join("".join(n.itertext()) for n in tree.findall(".//w:p", NS))
                require(SEED in text, "Actual Word retains the exact known Activity")
                result["editable_tables"] = len(tree.findall(".//w:tbl", NS))
            with pymupdf.open(stream=pdf, filetype="pdf") as document:
                result["pdf"]["pages"] = len(document)
                require(len(document) >= 10, "Actual PDF contains multiple report sections")
                text = "\n".join(p.get_text() for p in document)
                require("3 total, 2 completed, 1 open" in text, "Actual PDF retains known Activity counts")
            if PHASE == "after":
                save_version(page, expected_saved + 1)
                expect(caption).to_have_text(f"Shared version {expected_saved + 1}", timeout=30000)
                require(download(page, "Download DOCX", "after-checkpoint.docx") == word,
                        "Later checkpoint retains identical generated Word bytes")
                require(download(page, "Download PDF", "after-checkpoint.pdf") == pdf,
                        "Later checkpoint retains identical generated PDF bytes")
                result["later_checkpoint_revision"] = expected_saved + 1
            page.reload(wait_until="domcontentloaded", timeout=60000)
            expect(page.get_by_role("textbox", name="Activity summary", exact=True)).to_have_value(SEED, timeout=60000)
            reopened = live.await_fixture_state(page, "known-value prefill")
            require(reopened["generation"] == state["generation"], "Reload retains the same isolated report generation")
            require(reopened["revision"] == expected_saved + (1 if PHASE == "after" else 0),
                    "Reload reads the exact newest shared version")
            result["reloaded"] = reopened
            result["served_after"] = running_code_marker(page).text_content().strip()
            require(result["served_before"] == result["served_after"] == "Running code: " + EXPECTED,
                    "Exact served build remains stable across generation and reload")
            require(not off_host, "No off-host browser requests")
            result["passed"] = True
        except Exception as exc:
            result["error_type"] = type(exc).__name__
            result["error"] = str(exc)[:3000]
            if safe:
                try:
                    page.screenshot(path=str(OUT / "first-failure.png"))
                    result["synthetic_alerts"] = page.get_by_test_id("stAlert").all_text_contents()
                except Exception:
                    pass
            raise
        finally:
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            (OUT / "receipt.json").write_text(json.dumps(result, indent=2))
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
