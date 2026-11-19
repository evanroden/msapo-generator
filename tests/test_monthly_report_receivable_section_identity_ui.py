"""A78: the native AR editor uses the same included-section identity as Word/PDF.

Synthetic empty/filled 12, 10 and 8 section variants. No financial export
authorization and no source or persisted draft mutation.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path

import pytest
import pymupdf
from docx import Document
from docx.oxml.ns import qn
from streamlit.testing.v1 import AppTest

from app.monthly_report_contents_pagination import anchor_for
from app.monthly_report_docx import assemble_docx, generate_report
from tests.conftest import requires_libreoffice
from app.monthly_report_model import (
    ReportPeriod, ResolvedBlock, included_sections, optional_sections,
    synthetic_draft, synthetic_profiles,
)


APP = """
import streamlit as st
from app.monthly_report_receivable_ui import render_receivable_intake
draft = st.session_state["report"]
blocks = {block.key: block for block in draft.blocks}
draft, blocks = render_receivable_intake(draft, blocks, "synthetic_a78")
st.session_state["result_blocks"] = blocks
st.session_state["report"] = draft
"""


def _draft(excluded=(), *, filled=False, omit_ar=False, duplicate_ar=False):
    base = synthetic_draft(synthetic_profiles()[1], ReportPeriod(2026, 10))
    ar = optional_sections()[0]
    sections = (*base.sections[:9], ar, *base.sections[9:])
    sections = tuple(
        replace(s, included=False) if s.key in excluded or (omit_ar and s.key == "accounts_receivable")
        else s for s in sections
    )
    if duplicate_ar:
        sections = (*sections, ar)
    rows = (("Synthetic facility", "SYN-INV-1", "Awaiting review"),) if filled else ()
    blocks = (*base.blocks, ResolvedBlock("accounts_receivable", "This month", rows=rows))
    return replace(base, sections=sections, blocks=blocks)


@pytest.mark.parametrize("excluded,number,total", [
    ((), 10, 12),
    (("water", "training"), 9, 10),
    (("water", "issues", "proposals", "training"), 8, 8),
])
@pytest.mark.parametrize("filled", [False, True])
def test_native_editor_matches_actual_report_order_and_preserves_rows(excluded, number, total, filled):
    draft = _draft(excluded, filled=filled)
    selected = included_sections(draft.sections)
    assert len(selected) == total
    ar = [s for s in selected if s.key == "accounts_receivable"]
    assert len(ar) == 1 and (ar[0].number, ar[0].title) == (str(number), "Accounts Receivable")

    app = AppTest.from_string(APP)
    app.session_state["report"] = draft
    app.run()
    assert not app.exception
    captions = [c.value for c in app.caption]
    label = f"Section {number} — Accounts Receivable"
    assert any(c.startswith(label + " · Open invoices and AR Aging") for c in captions)
    if filled:
        assert f"Current {label} invoice status rows: 1" in captions
    else:
        assert not any("Current Section" in c for c in captions)
    if number != 10:
        assert all("Section 10" not in c for c in captions)
    assert app.session_state["report"] == draft
    assert app.session_state["result_blocks"]["accounts_receivable"].rows == (
        (("Synthetic facility", "SYN-INV-1", "Awaiting review"),) if filled else ()
    )


@pytest.mark.parametrize("missing,duplicate", [(True, False), (False, True)])
def test_missing_or_ambiguous_ar_section_never_claims_a_number(missing, duplicate):
    draft = _draft(omit_ar=missing, duplicate_ar=duplicate, filled=True)
    app = AppTest.from_string(APP)
    app.session_state["report"] = draft
    app.run()
    assert not app.exception
    captions = [c.value for c in app.caption]
    assert any(c.startswith("Accounts Receivable (not uniquely included) · Open invoices") for c in captions)
    assert not any(c.startswith("Section ") for c in captions)
    assert app.session_state["report"] == draft


@pytest.mark.parametrize("excluded,number,total", [
    ((), 10, 12),
    (("water", "training"), 9, 10),
    (("water", "issues", "proposals", "training"), 8, 8),
])
@pytest.mark.parametrize("filled", [False, True])
def test_native_word_contents_divider_and_body_share_actual_ar_identity(excluded, number, total, filled):
    draft = _draft(excluded, filled=filled)
    original = draft
    raw = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint)
    document = Document(BytesIO(raw))
    sections = included_sections(draft.sections)
    assert len(sections) == total
    links = []
    for paragraph in document.paragraphs:
        for link in paragraph._p.iter(qn("w:hyperlink")):
            anchor = link.get(qn("w:anchor"), "")
            if anchor.startswith("mr_contents_"):
                links.append((anchor, "".join(t.text or "" for t in link.iter(qn("w:t")))))
    assert links == [(anchor_for(s.key), f"{s.number}. {s.title}") for s in sections]
    headings = [p.text for p in document.paragraphs if p.style.name == "Heading 1"]
    assert headings == [text for _, text in links]
    paragraphs = [p.text for p in document.paragraphs]
    assert paragraphs.count(f"Section {number}") == 1
    assert headings.count(f"{number}. Accounts Receivable") == 1
    assert paragraphs.count("Accounts Receivable") == 1
    assert [a for a, _ in links].count(anchor_for("accounts_receivable")) == 1
    ar_body = next(i for i, p in enumerate(document.paragraphs)
                   if p.style.name == "Heading 1" and p.text == f"{number}. Accounts Receivable")
    assert paragraphs.index(f"Section {number}") < ar_body
    assert sum("SYN-INV-1" in cell.text for table in document.tables
               for row in table.rows for cell in row.cells) == int(filled)
    assert draft == original


@requires_libreoffice
@pytest.mark.parametrize("excluded,number,total,filled", [
    (("water", "training"), 9, 10, False),
    (("water", "issues", "proposals", "training"), 8, 8, True),
])
def test_real_pdf_ar_heading_links_and_divider_ink(excluded, number, total, filled, tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    draft = _draft(excluded, filled=filled)
    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    assert package.pdf and package.contents_notice == "", package.pdf_error
    assert package.docx
    with pymupdf.open(stream=package.pdf, filetype="pdf") as pdf:
        # GitHub's existing independent-synthetic artifact collection retains
        # the exact native derivatives and their hashes for manual comparison.
        if os.environ.get("INDEPENDENT_OUTPUT"):
            target = (Path(os.environ["INDEPENDENT_OUTPUT"]) /
                      f"a78-sections-{total}-number-{number}")
            target.mkdir(parents=True, exist_ok=True)
            (target / "report.docx").write_bytes(package.docx)
            (target / "report.pdf").write_bytes(package.pdf)
            (target / "manifest.json").write_text(json.dumps({
                "synthetic_only": True,
                "ordinary_sections": total,
                "receivable_number": number,
                "receivable_rows": int(filled),
                "docx_sha256": sha256(package.docx).hexdigest(),
                "pdf_sha256": sha256(package.pdf).hexdigest(),
                "pdf_pages": len(pdf),
                "source_documents": 0,
            }, indent=2))
        toc = pdf.get_toc()
        assert len(toc) == total
        expected = [(s.number, s.title) for s in included_sections(draft.sections)]
        assert [entry[1] for entry in toc] == [f"{n}. {title}" for n, title in expected]
        ar_entry = next(entry for entry in toc if entry[1] == f"{number}. Accounts Receivable")
        ar_body_page = ar_entry[2] - 1
        assert ar_body_page > 0
        assert f"{number}. Accounts Receivable" in pdf[ar_body_page].get_text()
        dividers = [i for i, page in enumerate(pdf)
                    if f"Section {number}" in page.get_text()
                    and "Accounts Receivable" in page.get_text()]
        assert len(dividers) == 1 and dividers[0] < ar_body_page
        page = pdf[dividers[0]]
        rects = page.search_for(f"Section {number}")
        assert len(rects) == 1
        r = rects[0]
        assert r.width > 0 and r.height > 0 and r.x0 >= page.rect.x0
        assert r.x1 <= page.rect.x1 and r.y0 >= page.rect.y0
        assert r.y1 <= page.rect.y1
        spans = [span for block in page.get_text("dict")["blocks"]
                 if "lines" in block for line in block["lines"] for span in line["spans"]
                 if f"Section {number}" in span["text"]]
        assert spans and any(span["size"] >= 19 for span in spans)
        # The divider should show a dark, legible text fill, not white-on-white.
        assert any((0.2126 * ((s["color"] >> 16) & 255)
                    + 0.7152 * ((s["color"] >> 8) & 255)
                    + 0.0722 * (s["color"] & 255)) < 130 for s in spans)
        clip = (r + (-2, -2, 2, 2)) & page.rect
        pix = page.get_pixmap(dpi=150, clip=clip, alpha=False)
        assert min(pix.samples) < 120 and max(pix.samples) > 200
        body_text = pdf[ar_body_page].get_text()
        assert ("SYN-INV-1" in body_text) == filled
        assert not any("$700" in pg.get_text() for pg in pdf)


def test_stale_receivable_receipt_notice_does_not_claim_a_fixed_number():
    from app.monthly_report_receivable_intake import _NOTICE
    assert "Accounts Receivable rows changed" in _NOTICE
    assert "Section 10" not in _NOTICE


def test_approved_custom_receivable_title_and_appendix_identity():
    from app.monthly_report_receivable_ui import receivable_section_heading
    draft = _draft()
    sections = tuple(replace(s, appendix=True, number="G", title="Invoice status")
                     if s.key == "accounts_receivable" else s for s in draft.sections)
    revised = replace(draft, sections=sections)
    assert receivable_section_heading(revised) == "Appendix G — Invoice status"
    assert draft.sections != revised.sections
