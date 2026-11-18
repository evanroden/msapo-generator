"""A17 golden 12-section export, audited as editable OOXML and rendered PDF.

This is an invented layout/route control, not an authentic import, served
Streamlit session, physical-device test, or Microsoft Word acceptance.
"""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from PIL import Image, ImageDraw
import pymupdf as fitz
import pytest

from app.monthly_report_asset_review import asset_fingerprint
from app.monthly_report_docx import generate_report
from app.monthly_report_model import (
    ReportDraft, ReportPeriod, ReportTable, ResolvedBlock,
    default_sections, included_sections, synthetic_profiles,
)
from tests.conftest import requires_libreoffice


PRIVATE_PRICE = "A17-PRIVATE-QUOTE-$91,234.56"
PRIVATE_CONTACT = "A17-PRIVATE-CONTACT-555-123-9876"
OTHER_SITE = "A17-OTHER-SITE-CANARY"


def _png(size, color, *, alpha=False, label="") -> bytes:
    mode = "RGBA" if alpha else "RGB"
    image = Image.new(mode, size, (0, 0, 0, 0) if alpha else color)
    draw = ImageDraw.Draw(image)
    if alpha:
        draw.rectangle((12, 12, size[0] - 12, size[1] - 12), fill=(*color, 220))
    else:
        draw.rectangle((size[0] // 8, size[1] // 8,
                        size[0] * 7 // 8, size[1] * 7 // 8),
                       fill=(110, 140, 170))
    if label:
        draw.text((20, 20), label, fill=(255, 255, 255, 255) if alpha else (0, 0, 0))
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def golden_synthetic_draft(setenv, directory: Path):
    """All 11 ordinary sections and Appendix G, with current reviewed edits."""
    setenv.setenv("EPC_DATA_DIR", str(directory))
    assets = {}
    def register(raw: bytes) -> str:
        reference = sha256(raw).hexdigest() + ".png"
        assets[reference] = raw
        return reference

    mark = register(_png((600, 140), (40, 180, 100), alpha=True, label="SYNTHETIC MARK"))
    client = register(_png((360, 100), (50, 80, 170), alpha=True))
    cover = register(_png((2400, 1600), (170, 110, 50), label="SYNTHETIC COVER"))
    org = register(_png((1250, 1550), (240, 240, 240), label="SYNTHETIC ORG"))
    improvement = register(_png((2400, 1600), (50, 100, 130), label="SYNTHETIC PLANT"))
    scan = register(_png((900, 1200), (245, 245, 245), label="SYNTHETIC SOURCE PAGE"))
    divider = register(_png((1400, 1800), (190, 70, 35), label="SYNTHETIC DIVIDER"))

    all_sections = tuple(
        replace(section, included=True, divider_asset=divider if section.key == "activity" else "")
        for section in default_sections()
    )
    assert len(all_sections) == 12
    media_slots = {
        "org_chart": org, "improvements": improvement,
        "mbcx_report": scan, "vendor_reports": scan, "water_reports": scan,
    }
    blocks = []
    for section in all_sections:
        for index, spec in enumerate(section.blocks):
            marker = f"A17-{section.key.upper()}-CONTENT" if index == 0 else ""
            rows = ()
            if spec.key == "contact_matrix":
                rows = tuple(("Demo North", "Facilities", f"A17-CONTACT-{n:03}",
                              "Not provided", "Not provided") for n in range(80))
            elif spec.key == "service_calls":
                rows = tuple((f"A17-WO-{n:03}", "2026-09-12", "Demo North",
                              "Inspected synthetic AHU", f"AHU-{n:03}") for n in range(90))
            elif spec.key == "work_orders":
                rows = (("A17-WO-A", "Completed", "Demo North"),
                        ("A17-WO-B", "Open", "Demo North"))
            elif spec.key == "thermal_capacity":
                rows = (("Demo North", "Cooling", "500", "tons"),)
            elif spec.key == "subcontractor_matrix":
                rows = (("Demo North", "HVAC", "Synthetic Vendor",
                         "Not provided", "Not provided", "Pending"),)
            elif spec.key == "capital_renewal":
                rows = (("Demo North", "High", "Replace synthetic AHU controls"),)
            elif spec.key == "end_of_life":
                rows = (("Demo North", "Synthetic boiler", "2028"),)
            elif spec.key == "proposals":
                rows = (("Demo North", "Synthetic Vendor", "Valve inspection", "Pending"),)
            elif spec.key == "rfi_matrix":
                rows = (("Demo North", "Valve drawing", "Awaiting response"),)

            extra = ()
            if spec.key == "training_summary":
                extra = (ReportTable(("Course", "Hours", "Status"),
                                     (("Electrical safety", "1", "Completed"),),
                                     "a17-training"),)
            block = ResolvedBlock(spec.key, "This month", text=marker or (
                f"Synthetic current {spec.key.replace('_', ' ')}." if spec.type == "rich_text" else ""),
                rows=rows, extra_tables=extra,
                asset_hashes=(media_slots[spec.key],) if spec.key in media_slots else (),
                asset_captions=("Reviewed synthetic source page",) if spec.key in {
                    "mbcx_report", "vendor_reports", "water_reports",
                } else ())
            if block.asset_hashes:
                block = replace(block, client_asset_reviews=tuple(
                    asset_fingerprint(block, i) for i in range(len(block.asset_hashes))))
            blocks.append(block)

    for key, asset in (("brand_logo", mark), ("client_logo", client), ("cover_photo", cover)):
        block = ResolvedBlock(key, "This month", asset_hashes=(asset,))
        blocks.append(replace(block, client_asset_reviews=(asset_fingerprint(block, 0),)))

    # Explicitly omitted, unrelated content and pricing are never exported.
    blocks.extend((
        ResolvedBlock("unused_price", "Omit", text=PRIVATE_PRICE),
        ResolvedBlock("unused_contact", "Omit", text=PRIVATE_CONTACT),
        ResolvedBlock("wrong_site", "Omit", text=OTHER_SITE),
    ))
    return (
        ReportDraft(synthetic_profiles()[0], ReportPeriod(2026, 9),
                    "Synthetic Editor", all_sections, tuple(blocks),
                    address_line="Synthetic Report Center", synthetic=True),
        assets,
    )


def audit_golden_package(package, draft):
    """Independent native DOCX structure and PDF page/raster audit.

    Never infer all-page Word fidelity merely from successful PDF conversion.
    Each record is a *synthetic* manifest, not certification of a source report.
    """
    assert package.docx.startswith(b"PK")
    assert package.pdf and package.pdf.startswith(b"%PDF-"), package.pdf_error
    expected = included_sections(draft.sections)
    assert len(expected) == 12
    word = Document(BytesIO(package.docx))
    paragraph_text = "\n".join(p.text for p in word.paragraphs)
    table_text = "\n".join(cell.text for t in word.tables for row in t.rows for cell in row.cells)
    headers = "\n".join(cell.text for t in word.tables for cell in t.rows[0].cells)
    with ZipFile(BytesIO(package.docx)) as archive:
        parts = archive.namelist()
        text_parts = [name for name in parts if name.endswith((".xml", ".rels"))]
        native_xml = b"\n".join(archive.read(name) for name in text_parts)
        drawings = [name for name in parts if name.startswith("word/media/")]
        native_headers = [name for name in parts if name.startswith("word/header") and name.endswith(".xml")]
        native_footers = [name for name in parts if name.startswith("word/footer") and name.endswith(".xml")]
        assert drawings and native_headers and native_footers
        assert b"tblHeader" in native_xml, "Long tables must keep editable repeating header rows"
        assert b"word/media/" in native_xml or any(
            b"/image" in archive.read(name) for name in parts if name.endswith(".rels"))
        assert len(word.tables) >= 5
        assert len(word.inline_shapes) >= 2
        for token in (PRIVATE_PRICE, PRIVATE_CONTACT, OTHER_SITE):
            assert token.encode() not in native_xml
        divider_jpegs = []
        alpha_marks = []
        for name in drawings:
            try:
                with Image.open(BytesIO(archive.read(name))) as image:
                    if image.size == (1275, 1650) and image.format == "JPEG":
                        divider_jpegs.append((image.getpixel((20, 80)), image.getpixel((20, 500))))
                    if image.mode == "RGBA" and image.getchannel("A").getextrema()[0] == 0:
                        alpha_marks.append(name)
            except OSError:
                continue
        assert divider_jpegs, "The native section divider must remain embedded"
        assert all(len(set(pixels[0])) == 1 for pixels in divider_jpegs), (
            "Divider photographs, unlike editable title bands, are grayscale"
        )
        assert alpha_marks, "Transparent brand marks must not become opaque white rectangles"

    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        assert len(pdf) >= 27, "12 content sections, dividers, cover, TOC and overflow need pages"
        page_texts = [page.get_text() for page in pdf]
        pdf_text = "\n".join(page_texts)
        page_raster_sha256 = []
        for page in pdf:
            assert 610 <= page.rect.width <= 614 and 790 <= page.rect.height <= 794
            pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2), alpha=False)
            page_raster_sha256.append(sha256(pix.samples).hexdigest())
        pages_with_contacts = [i for i, text in enumerate(page_texts)
                               if "A17-CONTACT-" in text]
        assert len(pages_with_contacts) >= 2, "Contacts must overflow real PDF pages"
        assert all("Facility" in page_texts[i] and "Role" in page_texts[i]
                   for i in pages_with_contacts), "Contacts table headers must repeat"
        assert any("A17-CONTACT-079" in s for s in page_texts)
        assert any("A17-WO-089" in s for s in page_texts)
        assert any(page.get_images(full=True) for page in pdf)
        assert "Page " in page_texts[-1], "Final-page footer must contain the page number"
        for token in (PRIVATE_PRICE, PRIVATE_CONTACT, OTHER_SITE):
            assert token not in pdf_text

        section_manifest = {}
        for section in expected:
            marker = f"A17-{section.key.upper()}-CONTENT"
            assert paragraph_text.count(marker) == 1, marker
            assert pdf_text.count(marker) == 1, marker
            assert section.title in paragraph_text, section.title
            section_manifest[section.key] = {
                "number": section.number,
                "title": section.title,
                "marker": marker,
                "pdf_pages": [index + 1 for index, text in enumerate(page_texts) if marker in text],
                "native_editable": True,
            }
        assert "Table of contents" in paragraph_text
        assert "Appendix G" in paragraph_text
        assert "Electrical safety" in table_text
        assert "Valve inspection" in table_text and "Awaiting response" in table_text

        return {
            "synthetic_only": True,
            "served_or_authentic_acceptance": False,
            "word": {
                "sha256": sha256(package.docx).hexdigest(),
                "bytes": len(package.docx),
                "editable_tables": len(word.tables),
                "drawing_parts": len(drawings),
                "header_parts": len(native_headers),
                "footer_parts": len(native_footers),
                "repeating_table_headings": True,
                "transparent_logo": True,
                "grayscale_divider": True,
            },
            "pdf": {
                "sha256": sha256(package.pdf).hexdigest(),
                "bytes": len(package.pdf),
                "pages": len(pdf),
                "page_raster_sha256_20pct": page_raster_sha256,
                "contact_pages": [i + 1 for i in pages_with_contacts],
            },
            "sections": section_manifest,
            "private_canaries_absent": [PRIVATE_PRICE, PRIVATE_CONTACT, OTHER_SITE],
            "control_labels": ["cover/logo", "TOC", "dividers", "organization", "contacts",
                "activity", "utility", "thermal capacity", "MBCx", "maintenance",
                "vendor", "water", "issues", "capital", "proposals", "training",
                "Appendix G", "final footer", "page count", "privacy"],
            "note": "LibreOffice-generated synthetic PDF; no source originals, Word, served browser or device parity.",
        }


@requires_libreoffice
def test_complete_twelve_section_application_export_audit(monkeypatch, tmp_path):
    from app import pdf_converter
    monkeypatch.setattr(pdf_converter, "OUTPUT_DIR", tmp_path)
    from app import monthly_report_library as library
    draft, assets = golden_synthetic_draft(monkeypatch, tmp_path / "data")
    original = {key: sha256(value).hexdigest() for key, value in assets.items()}
    # Native operator changes must travel through the real on-disk snapshot,
    # not merely a mocked in-memory session or rehydrated UI control.
    revised = replace(draft, blocks=tuple(
        replace(block, text=block.text + "\nA17-OPERATOR-EDIT-RELOADED")
        if block.key == "activity_summary" else block for block in draft.blocks))
    saved = library.save_snapshot(revised, expected_revision=0,
                                  assets=tuple(assets.items()),
                                  entered_editor="Synthetic Editor")
    opened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period)
    assert opened is not None and opened.revision == saved.revision == 1
    assert opened.draft.fingerprint == revised.fingerprint
    draft = opened.draft
    def persisted_asset(ref):
        return library.read_asset(draft.profile.contract, draft.profile.key, ref)
    package = generate_report(draft, acknowledged_fingerprint=draft.fingerprint,
                              asset_loader=persisted_asset)
    manifest = audit_golden_package(package, draft)
    assert "A17-OPERATOR-EDIT-RELOADED" in " ".join(
        paragraph.text for paragraph in Document(BytesIO(package.docx)).paragraphs)
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        assert any("A17-OPERATOR-EDIT-RELOADED" in page.get_text() for page in pdf)
    assert list(manifest["sections"]) == [section.key for section in included_sections(draft.sections)]
    assert len(manifest["pdf"]["page_raster_sha256_20pct"]) == manifest["pdf"]["pages"]
    assert {key: sha256(value).hexdigest() for key, value in assets.items()} == original


def test_twelve_section_privacy_preflight_refuses_priced_current_proposal(monkeypatch, tmp_path):
    from app.monthly_report_docx import assemble_docx
    draft, assets = golden_synthetic_draft(monkeypatch, tmp_path / "data")
    changed = tuple(replace(block, rows=(("Demo North", "Vendor", PRIVATE_PRICE, "Pending"),))
                    if block.key == "proposals" else block for block in draft.blocks)
    revised = replace(draft, blocks=changed)
    with pytest.raises(ValueError):
        assemble_docx(revised, acknowledged_fingerprint=revised.fingerprint,
                      asset_loader=assets.__getitem__)
