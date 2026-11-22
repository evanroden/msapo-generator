"""A87: independent source-truth manifest through real Monthly DOCX/PDF outputs.

Every source is manufactured in memory.  The JSON truth manifest is authored
independently of the application parser; it is not a snapshot of parser output.
The selected final wording is constructed ONLY from located extracted lines.
No mocked AI, paid OCR, production data or genuine client source is involved.
Refs #270 #304 #277 #285.
"""
from collections import Counter
from dataclasses import replace
from email.message import EmailMessage
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
from zipfile import ZipFile

from docx import Document
from docx.shared import Inches
from openpyxl import Workbook
from PIL import Image, ImageDraw
import pymupdf
import pytest

from app import monthly_report_library as library
from app import monthly_report_sources as sources
from app import pdf_converter
from app.monthly_report_content_policy import page_allowed, page_fingerprint
from app.monthly_report_docx import generate_report
from app.monthly_report_model import ReportDraft, ResolvedBlock, default_sections, synthetic_profiles, ReportPeriod
from conftest import requires_libreoffice


TRUTH = Path(__file__).parent / "fixtures" / "monthly_extraction_completeness_a87.json"
PROFILE = synthetic_profiles()[0]  # North only: South rows must not cross scope.
PERIOD = ReportPeriod(2026, 9)
CANARY = re.compile(r"A87-[A-Z]+(?:-[A-Z]+)*-\d{2}")


def _truth():
    data = json.loads(TRUTH.read_text(encoding="utf-8"))
    assert data["schema"] == "a87-synthetic-truth-v1"
    all_ids = [item["id"] for part in ("include", "withhold") for item in data[part]]
    assert len(all_ids) == len(set(all_ids))
    assert all(item["reason"].strip() for item in data["withhold"])
    return data


def _png(*, scan=False):
    picture = Image.new("RGB", (612, 792) if scan else (64, 44), "white")
    pen = ImageDraw.Draw(picture)
    if scan:
        pen.text((40, 70), "A87-PDF-SCAN-03 image only", fill="black")
    else:
        pen.rectangle((6, 6, 57, 36), fill="black")
    buffer = BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def _synthetic_originals():
    """Input bytes are defined here, not derived from the independent truth."""
    word = Document()
    word.add_paragraph("A87-DOCX-PARA-01: Vendor inspected AHU on 2026-09-08.")
    table = word.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Evidence"
    table.cell(0, 1).text = "Finding"
    table.cell(1, 0).text = "A87-DOCX-TABLE-02"
    table.cell(1, 1).text = "Vendor checked motor rotation."
    shape = word.add_picture(BytesIO(_png()), width=Inches(0.6))
    shape._inline.docPr.set("descr", "A87-DOCX-ASSET-03")
    docx_buffer = BytesIO()
    word.save(docx_buffer)

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((45, 65), "A87-PDF-TECH-01: Vendor measured pump at 45 psi on 2026-09-14.")
        page = pdf.new_page()
        page.insert_text((45, 65), "A87-PDF-PRICE-02: Proposal total $4310.00.")
        page = pdf.new_page()
        page.insert_image(page.rect, stream=_png(scan=True))
        pdf_bytes = pdf.tobytes()

    wb = Workbook()
    sheet = wb.active
    sheet.title = "North maintenance"
    sheet.append(("Work Order", "Site", "Date", "Status", "Work"))
    sheet.append(("A87-XLSX-NORTH-01", "North", "2026-09-11", "Completed",
                  "Vendor tested AHU controls."))
    sheet.append(("A87-XLSX-UNDATED-02", "North", "", "Open",
                  "Date unknown; follow-up required."))
    south = wb.create_sheet("South maintenance")
    south.append(("Work Order", "Site", "Date", "Status", "Work"))
    south.append(("A87-XLSX-SOUTH-03", "South", "2026-09-12", "Closed",
                  "Outside the North report scope."))
    xlsx_buffer = BytesIO()
    wb.save(xlsx_buffer)

    csv_bytes = (
        "Work Order,Site,Date,Status,Work\n"
        "A87-CSV-NORTH-01,North,2026-09-13,Closed,Vendor inspected VAV damper.\n"
        "A87-CSV-PENDING-02,North,2026-09-13,Did not start,Valve work remains pending.\n"
        "A87-CSV-SOUTH-03,South,2026-09-13,Closed,Outside the North report scope.\n"
        "A87-CSV-OCTOBER-04,North,2026-10-02,Closed,Outside September period.\n"
    ).encode()
    txt_bytes = (
        "A87-TXT-UNKNOWN-01: Date unknown; vendor measured 40 psi; no completion date inferred.\n"
        "A87-TXT-PENDING-02: Vendor said work was not completed; follow-up pending.\n"
        "A87-TXT-PRICE-03: Vendor quote $3100.00; financial sentence only.\n"
    ).encode()
    attachment = b"A87-ATT-TXT-01: Vendor noted supply fan vibration on 2026-09-19.\n"
    email = EmailMessage()
    email["From"] = "vendor@example.invalid"
    email["To"] = "reader@example.invalid"
    email["Subject"] = "Synthetic September evidence"
    email.set_content(
        "A87-EML-TECH-01: Vendor inspected drive belts on 2026-09-18.\n"
        "A87-EML-PRICE-02: Invoice amount $900.00.\n"
    )
    email.add_attachment(attachment, maintype="text", subtype="plain",
                         filename="attached-note.txt")
    originals = (
        ("evidence.docx", docx_buffer.getvalue()),
        ("pages.pdf", pdf_bytes),
        ("orders.xlsx", xlsx_buffer.getvalue()),
        ("orders.csv", csv_bytes),
        ("notes.txt", txt_bytes),
        ("vendor.eml", email.as_bytes()),
    )
    return originals, attachment


def _located(content, canary):
    """Return independently checkable one-based source position and exact line."""
    hits = [(number, line)
            for number, page in enumerate(content.source.page_texts, 1)
            for line in page.splitlines() if canary in line]
    assert len(hits) == 1, (content.source.filename, canary, hits)
    assert hits[0][1].count(canary) == 1
    return hits[0]


def _ingested(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    # This manifest counts the text each extractor reads natively. Pin the
    # server without local OCR (as in CI) so it is the same where tesseract
    # is installed (production). OCR-read text is covered by the A07 reader
    # tests and by A57's raster canary, which pins OCR both ways.
    import shutil
    which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "tesseract" else which(name, *a, **k))
    originals, attachment = _synthetic_originals()
    contents, messages = sources.ingest_batch(PROFILE, originals)
    assert messages == (), messages
    assert {c.source.filename for c in contents} == {
        "evidence.docx", "pages.pdf", "orders.xlsx", "orders.csv",
        "notes.txt", "vendor.eml", "attached-note.txt",
    }
    assert len(contents) == 7
    originals_by_name = dict(originals)
    originals_by_name["attached-note.txt"] = attachment
    for content in contents:
        original = originals_by_name[content.source.filename]
        assert content.source.sha256 == sha256(original).hexdigest()
        assert sources.source_bytes(PROFILE, content.source) == original
    return {c.source.filename: c for c in contents}, originals


def _audit(contents, truth):
    """Require every declared technical item to have exactly one source location."""
    included_lines = []
    locations = {}
    for part in ("include", "withhold"):
        for expected in truth[part]:
            content = contents[expected["source"]]
            if expected.get("asset"):
                continue  # Physical image provenance has its own assertion below.
            page, line = _located(content, expected["id"])
            if "page" in expected:
                assert page == expected["page"], (expected["id"], page)
            locations[expected["id"]] = (content.source.id, page, line)
            if part == "include":
                included_lines.append(
                    f"{content.source.filename} / source page {page}: {line.strip()}"
                )
    assert len(included_lines) == len(truth["include"])
    observed = Counter(CANARY.findall("\n".join(
        page for content in contents.values() for page in content.source.page_texts)))
    declared = Counter({item["id"]: 1 for part in ("include", "withhold")
                        for item in truth[part] if not item.get("asset")})
    assert observed == declared, ("Missing, duplicated or fabricated source canaries", observed, declared)
    return included_lines, locations


def test_six_format_truth_manifest_and_repeat_import(tmp_path, monkeypatch):
    truth = _truth()
    contents, originals = _ingested(tmp_path, monkeypatch)
    selected, locations = _audit(contents, truth)
    assert len(selected) == 10 and len(locations) == 17

    pdf = contents["pages.pdf"].source
    assert len(pdf.page_texts) == 3
    assert "A87-PDF-TECH-01" in pdf.page_texts[0]
    assert "A87-PDF-PRICE-02" in pdf.page_texts[1]
    assert 3 in pdf.needs_vision and not pdf.page_texts[2].strip()
    assert 2 not in pdf.selected_pages and 3 not in pdf.selected_pages
    with pymupdf.open(stream=dict(originals)["pages.pdf"], filetype="pdf") as original_pdf:
        assert len(original_pdf) == 3
        assert original_pdf[2].get_images(), "Scan was a real image, not an empty page."

    word = contents["evidence.docx"]
    assert word.image_items and word.source.needs_vision
    with ZipFile(BytesIO(dict(originals)["evidence.docx"])) as z:
        assert b"A87-DOCX-ASSET-03" in z.read("word/document.xml")

    csv = contents["orders.csv"].tables
    xlsx = contents["orders.xlsx"].tables
    assert len(csv) == 1 and len(csv[0].rows) == 4
    assert len(xlsx) == 2 and sum(len(table.rows) for table in xlsx) == 3
    assert csv[0].rows[1][3] == "Did not start"
    assert xlsx[0].rows[1][2] == ""  # Missing date remains unknown.
    assert xlsx[1].rows[0][1] == "South"

    repeated, messages = sources.ingest_batch(PROFILE, originals, existing=tuple(contents.values()))
    assert len(repeated) == 7
    assert {c.source.id for c in repeated} == {c.source.id for c in contents.values()}
    assert sum("Duplicate skipped" in m for m in messages) == len(originals)
    assert all(sources.source_bytes(PROFILE, c.source) for c in repeated)


def test_price_only_and_image_only_pages_require_review_and_bad_siblings_do_not_erase(tmp_path, monkeypatch):
    truth = _truth()
    contents, originals = _ingested(tmp_path, monkeypatch)
    _audit(contents, truth)
    pdf = contents["pages.pdf"].source
    reviewed = replace(pdf, client_page_reviews=tuple(
        (page, page_fingerprint(pdf, page)) for page in (1, 2)))
    assert page_allowed(reviewed, 1)
    assert not page_allowed(reviewed, 2)  # Explicitly reviewed pricing is still forbidden.
    assert not page_allowed(reviewed, 3)  # Scanned data is not blank/safe text.
    assert "Price-only" in next(x["reason"] for x in truth["withhold"]
                                if x["id"] == "A87-PDF-PRICE-02")
    assert "human visual review" in next(x["reason"] for x in truth["withhold"]
                                         if x["id"] == "A87-PDF-SCAN-03")

    extra, messages = sources.ingest_batch(
        PROFILE,
        (("bad.docx", b"not-a-docx"), ("unsupported.bin", b"bad"),
         ("good-sibling.txt", b"A87-GOOD-SIBLING-01: Reviewed independent source.")),
        existing=tuple(contents.values()))
    assert any("Not read: bad.docx" in notice for notice in messages)
    assert any("Not read: unsupported.bin" in notice for notice in messages)
    assert len(extra) == 8
    assert any(c.source.filename == "good-sibling.txt" for c in extra)
    for content in contents.values():
        assert sources.source_bytes(PROFILE, content.source) == (
            dict(originals).get(content.source.filename)
            if content.source.filename != "attached-note.txt"
            else b"A87-ATT-TXT-01: Vendor noted supply fan vibration on 2026-09-19.\n"
        )
    with pytest.raises(ValueError, match="empty"):
        sources.ingest(PROFILE, "missing.txt", b"")


@requires_libreoffice
def test_six_source_review_to_persisted_real_word_and_pdf(tmp_path, monkeypatch):
    truth = _truth()
    contents, _ = _ingested(tmp_path, monkeypatch)
    selected, locations = _audit(contents, truth)
    pdf_content = contents["pages.pdf"]
    pdf = pdf_content.source
    exclusions = ((2, "Price-only page; never include"), (3, "Image-only: needs visual review"))
    pdf = replace(pdf, selected_pages=(1,),
                  client_page_reviews=((1, page_fingerprint(pdf, 1)),),
                  client_page_exclusions=exclusions)
    contents["pages.pdf"] = replace(pdf_content, source=pdf)
    word_content = contents["evidence.docx"]
    word = word_content.source
    word = replace(word, client_page_exclusions=tuple(
        (n, "Picture needs visual review") for n, _ in word_content.image_items))
    contents["evidence.docx"] = replace(word_content, source=word)

    # Reviewed, source-linked technical sentences alone; no generic prefilled
    # example text and no AI-generated work.  All exclusions remain in manifest.
    reviewed_text = "\n".join(selected)
    assert set(CANARY.findall(reviewed_text)) == {x["id"] for x in truth["include"]}
    assert all(x["id"] not in reviewed_text for x in truth["withhold"])
    sections = tuple(section for section in default_sections() if section.key == "activity")
    draft = ReportDraft(
        PROFILE, PERIOD, "Synthetic Editor", sections,
        (ResolvedBlock("work_orders", "This month"),
         ResolvedBlock("service_calls", "This month"),
         ResolvedBlock("activity_summary", "This month", text=reviewed_text)),
        synthetic=True, sources=tuple(c.source for c in contents.values()),
    )
    library.save_profile(PROFILE, expected_revision=0,
                         actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(draft, expected_revision=0)
    restored = library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD).draft
    assert restored.fingerprint == draft.fingerprint
    assert dict(next(s for s in restored.sources if s.filename == "pages.pdf").client_page_exclusions) == dict(exclusions)
    assert all(x["id"] in reviewed_text for x in truth["include"])

    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(pdf_converter, "PDF_BACKEND", "libreoffice")
    report = generate_report(restored, acknowledged_fingerprint=restored.fingerprint)
    assert report.docx and report.pdf and not report.pdf_error
    doc = Document(BytesIO(report.docx))
    word_text = "\n".join([p.text for p in doc.paragraphs] +
                          [cell.text for table in doc.tables
                           for row in table.rows for cell in row.cells])
    with pymupdf.open(stream=report.pdf, filetype="pdf") as pdf_result:
        pdf_page_count = len(pdf_result)
        pdf_page_locations = {}
        text_pages = []
        for number, page in enumerate(pdf_result, 1):
            extracted_page = page.get_text()
            text_pages.append(extracted_page)
            for canary in CANARY.findall(extracted_page):
                pdf_page_locations.setdefault(canary, []).append(number)
        pdf_text = "\n".join(text_pages)
        assert pdf_page_count >= 1
    expected_ids = {x["id"] for x in truth["include"]}
    assert set(pdf_page_locations) == expected_ids
    assert all(len(pages) == 1 for pages in pdf_page_locations.values())
    for name, text in (("DOCX", word_text), ("PDF", pdf_text)):
        actual = Counter(CANARY.findall(text))
        assert set(actual) == expected_ids, (name, actual)
        assert all(count == 1 for count in actual.values()), (name, actual)
        for item in truth["withhold"]:
            assert item["id"] not in text, (name, item["id"])
        assert "$4310" not in text and "$3100" not in text and "$900" not in text
        assert "Did not start" in text
        assert "not completed" in text
        assert "Date unknown" in text
        assert "ENFRA technician completed" not in text
        assert "pages.pdf / source page 1:" in text
    # Every published claim can be traced to the exact retained source sentence.
    for line in selected:
        assert line.split(": ", 1)[1] in reviewed_text
    for content in contents.values():
        assert sources.source_bytes(PROFILE, content.source)
    docx_sha = sha256(report.docx).hexdigest()
    pdf_sha = sha256(report.pdf).hexdigest()
    assert docx_sha != pdf_sha
    if os.environ.get("INDEPENDENT_OUTPUT"):
        # CI retains these exact synthetic bytes and proof manifest, rather
        # than claiming that the generic QA export is this A87 workload.
        destination = Path(os.environ["INDEPENDENT_OUTPUT"]) / "a87-six-formats"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "reviewed.docx").write_bytes(report.docx)
        (destination / "reviewed.pdf").write_bytes(report.pdf)
        (destination / "manifest.json").write_text(json.dumps({
            "fixture": "a87-synthetic-truth-v1",
            "report_identity": truth["report_scope"],
            "docx_sha256": docx_sha,
            "pdf_sha256": pdf_sha,
            "pdf_pages": pdf_page_count,
            "accepted_output_page_numbers": pdf_page_locations,
            "accepted_ids": sorted(expected_ids),
            "withheld_ids": sorted(item["id"] for item in truth["withhold"]),
            "source_identities": {
                c.source.filename: c.source.sha256 for c in contents.values()
            },
            "method": "synthetic original -> local parser -> reviewed extracted lines "
                      "-> saved/reloaded draft -> actual LibreOffice DOCX/PDF",
        }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
