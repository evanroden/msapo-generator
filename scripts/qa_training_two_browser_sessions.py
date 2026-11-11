"""Native same-row Training stale-save and explicit recovery acceptance.

Two real Chromium contexts share the isolated synthetic report but maintain
independent Streamlit widget sessions. A rejected stale session edit cannot
erase the newer committed row. The deliberate saved-copy choice is observed
before a new edit, and real Word/PDF reflect that choice. This test does not
claim that different monthly-session rows automatically three-way merge.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import traceback

from docx import Document
import pymupdf
from playwright.sync_api import expect, sync_playwright

from scripts import qa_training_two_browser as base

OUT = base.ROOT / "test-artifacts" / "training-two-browser" / "event-row"
ORIGINAL = "Synthetic safety refresher"
A_EDIT = "Synthetic completed session from A"
B_EDIT = "Synthetic competing session from B"


def edit_session(page, old, new):
    base.settled(page)
    button = page.get_by_role("button", name=re.compile(
        r"Edit session.*" + re.escape(old), flags=re.S))
    expect(button).to_have_count(1)
    button.click()
    topic = page.get_by_role("textbox", name="Training topic", exact=True)
    expect(topic).to_have_value(old)
    topic.fill(new)
    topic.press("Tab")
    expect(topic).to_have_value(new)
    page.get_by_role("button", name="Save session", exact=True).click()
    base.settled(page)
    expect(page.get_by_text(new, exact=True)).to_be_visible(timeout=30000)


def save_shared(page, token, revision):
    summary = page.locator('[data-testid="stExpander"] summary').filter(
        has=page.get_by_text("Shared report history", exact=True))
    expect(summary).to_have_count(1)
    if summary.get_attribute("aria-expanded") != "true":
        summary.click()
    save = page.get_by_role("button", name="Save shared version", exact=True)
    expect(save).to_be_enabled()
    save.click()
    base.settled(page)
    assert base.snapshot_store(token)[2].revision == revision


def event_titles(saved):
    tables = [table for block in saved.draft.blocks if block.key == "training_summary"
              for table in block.extra_tables if table.reference == "training:events:v1"]
    assert len(tables) == 1
    return [row[0] for row in tables[0].rows]


def accept_saved_version(page, evidence):
    base.settled(page)
    review = page.get_by_role("button", name="Review draft changes", exact=True)
    if review.count():
        review.click()
        choose = page.get_by_role("button", name="Open saved report", exact=True)
        expect(choose).to_be_visible()
        choose.click()
        evidence["recovery_choice"] = "Open saved report"
        base.settled(page)


def verify_word_pdf(word, pdf):
    doc = Document(BytesIO(word))
    text = " ".join(
        [p.text for p in doc.paragraphs] +
        [c.text for t in doc.tables for r in t.rows for c in r.cells])
    with pymupdf.open(stream=pdf, filetype="pdf") as opened:
        pdf_text = " ".join(" ".join(p.get_text().split()) for p in opened)
    for document_text in (text, pdf_text):
        assert document_text.count(A_EDIT) == 1
        assert B_EDIT not in document_text
        assert ORIGINAL not in document_text


def journey():
    OUT.mkdir(parents=True, exist_ok=True)
    base.OUT = OUT
    token = __import__("secrets").token_hex(16)
    evidence = {"synthetic": True, "contexts": 2, "edits": [], "passed": False}
    with base.server(), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        first = base.browser_context(browser, token)
        second = base.browser_context(browser, token)
        a, b = first.new_page(), second.new_page()
        try:
            a.goto(base.URL, wait_until="domcontentloaded")
            a.get_by_role("button", name="Load known-value report", exact=True).click()
            expect(a.get_by_text(re.compile(r"^QA fixture state: known-value prefill"))).to_be_visible(timeout=45000)
            base.open_training(a)
            b.goto(base.URL, wait_until="domcontentloaded")
            base.open_training(b)
            start = base.snapshot_store(token)[2]
            assert start.revision == 1 and event_titles(start) == [ORIGINAL]
            evidence["edits"].append({"stage": "both readers", "saved_revision": 1})
            # The loser begins native editing first. Its input is not delivered
            # into A's session or committed by A's later save.
            old_button = b.get_by_role("button", name=re.compile(
                r"Edit session.*" + re.escape(ORIGINAL), re.S))
            expect(old_button).to_have_count(1)
            old_button.click()
            topic_b = b.get_by_role("textbox", name="Training topic", exact=True)
            expect(topic_b).to_have_value(ORIGINAL)
            topic_b.fill(B_EDIT)
            topic_b.press("Tab")
            expect(topic_b).to_have_value(B_EDIT)

            edit_session(a, ORIGINAL, A_EDIT)
            save_shared(a, token, 2)
            assert event_titles(base.snapshot_store(token)[2]) == [A_EDIT]
            evidence["edits"].append({"stage": "A saved", "saved_revision": 2})

            b.get_by_role("button", name="Save session", exact=True).click()
            base.settled(b)
            expect(b.get_by_text(
                "Another version was saved. Your working draft is preserved.",
                exact=False)).to_be_visible(timeout=30000)
            assert event_titles(base.snapshot_store(token)[2]) == [A_EDIT]
            expect(b.get_by_text(B_EDIT, exact=True)).to_be_visible(timeout=30000)
            evidence["edits"].append({"stage": "B stale conflict", "saved_revision": 2,
                                      "pending_row_still_visible": True})
            b.reload(wait_until="domcontentloaded")
            accept_saved_version(b, evidence)
            base.open_training(b)
            assert event_titles(base.snapshot_store(token)[2]) == [A_EDIT]

            b.get_by_role("button", name="Generate QA Word and PDF", exact=True).click()
            expect(b.get_by_role("button", name="Download isolated QA DOCX", exact=True)).to_be_visible(timeout=180000)
            expect(b.get_by_role("button", name="Download isolated QA PDF", exact=True)).to_be_visible(timeout=60000)
            word, w = base.download(b, "Download isolated QA DOCX", "row-conflict.docx")
            pdf, p = base.download(b, "Download isolated QA PDF", "row-conflict.pdf")
            verify_word_pdf(word, pdf)
            evidence["output"] = {"docx": w, "pdf": p}
            assert event_titles(base.snapshot_store(token)[2]) == [A_EDIT]
            evidence["passed"] = True
        except Exception:
            evidence["error"] = traceback.format_exc()[:4500]
            for label, page in (("A", a), ("B", b)):
                try:
                    page.screenshot(path=str(OUT / (label + "-failure.png")))
                except Exception:
                    pass
            raise
        finally:
            (OUT / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
            second.close()
            first.close()
            browser.close()


if __name__ == "__main__":
    journey()
