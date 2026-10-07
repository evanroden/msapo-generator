"""Deterministic DOCX assembly with recoverable PDF conversion.

The committed shell contains only styles and page chrome, never client assets.
M1 renders text/stock-text and tables; image-backed blocks fail explicitly until
their library resolver is installed. Missing content must not vanish silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import tempfile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app import pdf_converter
from app.monthly_report_checks import preflight
from app.monthly_report_model import ReportDraft, included_sections, report_filename


SHELL_PATH = Path(__file__).resolve().parents[1] / "templates" / "monthly_report" / "shell.docx"
FIXED_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)
OCEAN = "092B24"  # Matches --enfra-ocean in the existing application CSS.


@dataclass(frozen=True)
class ReportPackage:
    docx: bytes
    pdf: bytes | None
    docx_name: str
    pdf_name: str
    fingerprint: str
    pdf_error: str = ""


def canonical_docx(raw: bytes) -> bytes:
    """python-docx fixes XML timestamps, but zipfile otherwise adds wall time."""
    output = BytesIO()
    with ZipFile(BytesIO(raw)) as source, ZipFile(output, "w", ZIP_DEFLATED) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))
    return output.getvalue()


def _save(document) -> bytes:
    core = document.core_properties
    core.author = "Email Process Control"
    core.last_modified_by = "Email Process Control"
    core.created = FIXED_TIME
    core.modified = FIXED_TIME
    core.revision = 1
    core.title = "Operations and Maintenance Monthly Review"
    core.subject = ""
    core.comments = ""
    # python-docx ships a stock preview thumbnail. Do not accidentally ship it
    # as a supposed branding asset in the content-free shell or generated file.
    rels = document.part.package.rels
    for key, rel in list(rels.items()):
        if rel.reltype.endswith("/thumbnail"):
            del rels[key]
    buffer = BytesIO()
    document.save(buffer)
    return canonical_docx(buffer.getvalue())


def _field(paragraph, instruction: str) -> None:
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), instruction)
    paragraph._p.append(field)


def _configure_section(section, *, content: bool, address: str = "") -> None:
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.75 if content else 0)
    section.left_margin = section.right_margin = Inches(0.75 if content else 0)
    section.header_distance = section.footer_distance = Inches(0.3)
    # Headers/footers link to the previous section by default. Explicitly
    # unlink all three variants so a divider can never inherit contact chrome.
    section.different_first_page_header_footer = False
    for part in (section.header, section.footer, section.first_page_header,
                 section.first_page_footer, section.even_page_header, section.even_page_footer):
        part.is_linked_to_previous = False
        for child in list(part._element):
            part._element.remove(child)
        part.add_paragraph()
    if content:
        section.header.paragraphs[0].text = "ENFRA | Operations and Maintenance"
        footer = section.footer.paragraphs[0]
        if address:
            footer.add_run(address + "  |  ")
        footer.add_run("Page ")
        _field(footer, "PAGE")


def create_shell(path: Path) -> None:
    """Reproducible build helper; runtime generation only reads the checked shell."""
    document = Document()
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_after = Pt(8)
    for style_name, size in (("Title", 30), ("Heading 1", 23), ("Heading 2", 16)):
        style = document.styles[style_name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(OCEAN)
    _configure_section(document.sections[0], content=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_save(document))


def outline(draft: ReportDraft) -> tuple[tuple[str, tuple[str, ...], int], ...]:
    """Conservative text-only minimum; large text/tables can flow onto more pages."""
    return tuple((f"{s.number}. {s.title}", tuple(b.key for b in s.blocks), 2)
                 for s in included_sections(draft.sections))


def _display_page(document, *, label: str, title: str, subtitle: str = "") -> None:
    # Generated solid colour and text, not a reproduction of private logo bands
    # or photos. Library image dividers are resolved in the next milestone.
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Inches(2.2)
    paragraph.paragraph_format.left_indent = Inches(0.75)
    run = paragraph.add_run(label)
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = RGBColor.from_string(OCEAN)
    paragraph = document.add_paragraph(title, "Title")
    paragraph.paragraph_format.left_indent = Inches(0.75)
    paragraph.paragraph_format.right_indent = Inches(0.75)
    if subtitle:
        paragraph = document.add_paragraph(subtitle)
        paragraph.paragraph_format.left_indent = Inches(0.75)
        paragraph.paragraph_format.right_indent = Inches(0.75)


def _text(document, text: str) -> None:
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith(("- ", "• ")):
            document.add_paragraph(line[2:], "List Bullet")
        elif line.startswith("## "):
            document.add_paragraph(line[3:], "Heading 2")
        else:
            document.add_paragraph(line)


def assemble_docx(draft: ReportDraft, *, acknowledged_fingerprint: str = "") -> bytes:
    checks = preflight(draft)
    blocking = [c.message for c in checks if c.blocking]
    if blocking:
        raise ValueError(" ".join(blocking))
    if any(not c.blocking for c in checks) and acknowledged_fingerprint != draft.fingerprint:
        raise ValueError("Acknowledge the warnings for this version of the report.")
    document = Document(SHELL_PATH)
    _configure_section(document.sections[0], content=False)
    _display_page(document, label=draft.profile.contract, title=draft.profile.title,
                  subtitle="Operations and Maintenance Monthly Review\n" + draft.period.label)
    for text in ("Prepared by: " + draft.prepared_by,
                 "Facilities: " + "; ".join(f.title for f in draft.profile.facilities),
                 "SYNTHETIC DEMONSTRATION — NOT A CLIENT REPORT" if draft.synthetic else ""):
        if text:
            paragraph = document.add_paragraph(text)
            paragraph.paragraph_format.left_indent = Inches(0.75)
            paragraph.paragraph_format.right_indent = Inches(0.75)
    _configure_section(document.add_section(WD_SECTION_START.NEW_PAGE), content=True, address=draft.address_line)
    document.add_heading("Table of contents", 0)
    sections = included_sections(draft.sections)
    for section in sections:
        document.add_paragraph(f"{section.number}. {section.title}")
    document.add_paragraph("Confidential — intended for the report recipients. Do not distribute without permission.")
    document.add_paragraph("Create. Sustain. Empower.")
    blocks = {b.key: b for b in draft.blocks}
    for section in sections:
        _configure_section(document.add_section(WD_SECTION_START.NEW_PAGE), content=False)
        _display_page(document, label=f"Section {section.number}" if not section.appendix else f"Appendix {section.number}", title=section.title)
        _configure_section(document.add_section(WD_SECTION_START.NEW_PAGE), content=True, address=draft.address_line)
        document.add_heading(f"{section.number}. {section.title}", 1)
        for spec in section.blocks:
            block = blocks.get(spec.key)
            if block is None or block.source == "Omit":
                continue
            if block.asset_hashes:
                raise ValueError("Image and PDF-page assets require the library resolver.")
            _text(document, block.text)
            if block.rows:
                width = len(spec.columns) or max(map(len, block.rows))
                table = document.add_table(rows=1 if spec.columns else 0, cols=width)
                table.style = "Light Shading Accent 1"
                if spec.columns:
                    for cell, col in zip(table.rows[0].cells, spec.columns):
                        cell.text = col.title
                        shading = OxmlElement("w:shd")
                        shading.set(qn("w:fill"), OCEAN)
                        cell._tc.get_or_add_tcPr().append(shading)
                        for run in cell.paragraphs[0].runs:
                            run.font.color.rgb = RGBColor(255, 255, 255)
                            run.bold = True
                for values in block.rows:
                    if len(values) > width:
                        raise ValueError(f"Too many table columns in {spec.key}.")
                    for cell, value in zip(table.add_row().cells, values):
                        cell.text = value
    return _save(document)


def generate_report(draft: ReportDraft, *, acknowledged_fingerprint: str = "") -> ReportPackage:
    docx = assemble_docx(draft, acknowledged_fingerprint=acknowledged_fingerprint)
    pdf = None
    error = ""
    # The converter writes into the shared OUTPUT_DIR. A random stem prevents
    # collisions; both the actual and expected output paths are always cleaned.
    stem = "monthly-" + uuid4().hex
    expected_pdf = pdf_converter.OUTPUT_DIR / (stem + ".pdf")
    actual_pdf = None
    try:
        with tempfile.TemporaryDirectory(prefix="monthly-report-") as directory:
            input_path = Path(directory) / (stem + ".docx")
            input_path.write_bytes(docx)
            actual_pdf = pdf_converter.convert_to_pdf(input_path)
            pdf = actual_pdf.read_bytes()
            if not pdf.startswith(b"%PDF-"):
                raise ValueError("The converter returned an invalid PDF.")
    except Exception as exc:  # noqa: BLE001 - keep the finished DOCX on any backend failure
        pdf = None
        error = f"PDF conversion failed ({type(exc).__name__}). The DOCX is ready to download; retry PDF generation."
    finally:
        for path in {actual_pdf, expected_pdf} - {None}:
            path.unlink(missing_ok=True)
    return ReportPackage(docx, pdf, report_filename(draft, "docx"), report_filename(draft, "pdf"), draft.fingerprint, error)
