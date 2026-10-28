"""Conservative, page-referenced work-order review for native-text PDFs.

This parser never OCRs, approves, persists or publishes a work-order claim.
Only a positively headed, bounded text table can produce normalized candidates.
Scans, missing work-order identities, wrapped/orphaned cells and ambiguous
tables are retained as explicit operator-review conditions, not fabricated rows.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

import pymupdf as fitz

from app.monthly_report_model import ReportPeriod, ReportProfile
from app import monthly_report_sources as sources
from app.monthly_report_sources import SourceContent, SourceTable, source_reference
from app.monthly_report_work_order_normalized import (
    WorkOrderReview, normalize_table, suggest_mapping,
)

MAX_PDF_PAGES = 150
MAX_TABLES_PER_PAGE = 16
MAX_REVIEW_ROWS = 20_000
MAX_REVIEW_CELLS = 200_000


@dataclass(frozen=True)
class PdfPageReview:
    page: int
    source_reference: str
    rotation: int
    status: str  # records, scanned, no_table, ambiguous
    review: WorkOrderReview | None = None
    unmatched_rows: tuple[tuple[str, ...], ...] = ()
    notices: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfWorkOrderReview:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    filename: str
    pages: tuple[PdfPageReview, ...]
    cross_page_duplicates: tuple[tuple[str, str], ...] = ()

    @property
    def rows(self):
        return tuple((page.page, row) for page in self.pages if page.review
                     for row in page.review.rows)

    @property
    def needs_review(self):
        return (bool(self.cross_page_duplicates)
                or any(page.status != "records" or page.unmatched_rows or
                       (page.review is not None and page.review.needs_review)
                       for page in self.pages))

    @property
    def eligible_count(self):
        """Only evidence candidates; never a completeness/approval claim."""
        duplicates = set(self.cross_page_duplicates)
        return sum(not row.excluded and not row.issues
                   and (row.site, row.work_order.casefold()) not in duplicates
                   for _, row in self.rows)

    @property
    def ready_for_inclusion(self):
        return bool(self.rows) and not self.needs_review

    def page_references(self):
        return tuple(page.source_reference for page in self.pages if page.review)


def _clean_cell(value):
    return " ".join(str(value or "").replace("\r", "\n").split())


def _maybe_header(rows):
    """A positively identified WO identity + date + status header, or none."""
    for index, values in enumerate(rows[:3]):
        header = tuple(_clean_cell(value) for value in values)
        if not any(header):
            continue
        mapping = suggest_mapping(header)
        if all(getattr(mapping, field) is not None
               for field in ("work_order", "work_date", "status")):
            return index, header
    return None


def _extract_table(table):
    """Never infer cells from page text order or repair damaged column geometry."""
    values = table.extract()
    if not values or len(values) > MAX_REVIEW_ROWS + 5:
        raise ValueError("PDF table is empty or exceeds the row review limit.")
    width = max(map(len, values))
    if width <= 0 or width > 256:
        raise ValueError("PDF table exceeds the column review limit.")
    rows = []
    for row in values:
        if len(row) > width:
            raise ValueError("PDF table has inconsistent column geometry.")
        rows.append(tuple(_clean_cell(value) for value in row)
                    + ("",) * (width - len(row)))
    return tuple(rows)


def _page_table(page):
    """Read a table using only actual native PDF text, never model interpretation."""
    # A rotated page reports rotated coordinates to PyMuPDF's table finder.
    # Normalize ONLY this disposable in-memory PDF page; original source bytes
    # and stored source rotation remain untouched.
    if page.rotation:
        page.set_rotation(0)
    tables = page.find_tables(strategy="text").tables
    if len(tables) > MAX_TABLES_PER_PAGE:
        raise ValueError("PDF page has too many table candidates to review safely.")

    matched = []
    for table in tables:
        rows = _extract_table(table)
        result = _maybe_header(rows)
        if result is None:
            continue
        heading_index, columns = result
        width = len(columns)
        records, unknown = [], []
        for values in rows[heading_index + 1:]:
            if not any(values):
                continue  # PyMuPDF text-grid spacer; not a source record.
            if tuple(_clean_cell(value).casefold() for value in values) == tuple(
                    col.casefold() for col in columns):
                continue  # Header repeated at a page boundary or mid-table.
            if len(values) != width or not values[0].strip():
                unknown.append(values)
                continue  # Wrapped description / missing WO cannot be invented.
            records.append(values)
        matched.append((columns, tuple(records), tuple(unknown)))

    if len(matched) > 1:
        return None, (), ("Multiple work-order tables were found on one page; "
                          "review the source layout before mapping.",)
    if not matched:
        return None, (), ()
    columns, rows, unmatched = matched[0]
    if not rows and not unmatched:
        return None, (), ("The table has no readable work-order rows.",)
    return SourceTable("PDF page " + str(page.number + 1), columns, rows), unmatched, ()


def _cross_page_duplicates(pages):
    seen = {}
    for page in pages:
        if page.review is None:
            continue
        for row in page.review.rows:
            if row.work_order and row.site:
                seen.setdefault((row.site, row.work_order.casefold()), set()).add(page.page)
    return tuple(sorted(key for key, page_numbers in seen.items()
                        if len(page_numbers) > 1))


def review_pdf_workorders(profile: ReportProfile, content: SourceContent,
                          period: ReportPeriod) -> PdfWorkOrderReview:
    """Extract review candidates from a saved, hash-verified native-text PDF.

    The adapter only prepares candidates, never changes draft state. Every
    reviewable row's SourceRow.table_number is its actual 1-based PDF page,
    making the existing source_reference(source, page) precise and stable.
    """
    source = content.source
    if source.suffix != ".pdf":
        raise ValueError("Choose a saved PDF source for work-order review.")
    raw = sources.source_bytes(profile, source)
    if hashlib.sha256(raw).hexdigest() != source.sha256:
        raise ValueError("The saved PDF changed; no source rows were imported.")
    try:
        with fitz.open(stream=raw, filetype="pdf") as pdf:
            if pdf.is_encrypted and not pdf.authenticate(""):
                raise ValueError("This PDF is locked. Upload an unlocked original.")
            if len(pdf) > MAX_PDF_PAGES:
                raise ValueError("This PDF exceeds the 150-page work-order review limit.")
            if len(content.source.page_texts) != len(pdf):
                raise ValueError("The PDF page inventory changed; re-read the original.")
            page_tables, unresolved, rotations, notices = [], [], [], []
            cell_count = 0
            for number, page in enumerate(pdf, 1):
                rotation = page.rotation
                rotations.append(rotation)
                native_words = page.get_text("words")
                # Page-level read metadata remains available even when no
                # supported tabular structure is present.
                if not native_words:
                    reason = ("Image-only page: no searchable text work-order table. "
                              "Review the original; OCR was not performed."
                              if page.get_images(full=True) else
                              "Blank or textless PDF page: review before inclusion.")
                    page_tables.append(None)
                    unresolved.append(())
                    notices.append((reason,))
                    continue
                table, unknown, problems = _page_table(page)
                page_tables.append(table)
                unresolved.append(unknown)
                if table is None:
                    notices.append(problems or (
                        "No supported native-text work-order table was found. "
                        "Review the source page manually; no rows were invented.",))
                    continue
                cell_count += len(table.columns) * (len(table.rows) + len(unknown))
                if (len(table.rows) > MAX_REVIEW_ROWS or
                        cell_count > MAX_REVIEW_CELLS):
                    raise ValueError("PDF work-order cells exceed the safe review budget.")
                if unknown:
                    problems = (*problems, f"{len(unknown)} unlinked/partial rows "
                                "need review; none were counted as work orders.")
                notices.append(tuple(problems))
    except (fitz.mupdf.FzErrorBase, OverflowError, RuntimeError) as exc:
        raise ValueError("PDF work-order tables could not be read safely. "
                         "The saved source and report remain unchanged.") from exc

    # One immutable SourceTable placeholder per real PDF page binds
    # SourceRow.table_number and source_reference to the true page number.
    tables = tuple(table or SourceTable("PDF page " + str(index), ("Unknown",), ())
                   for index, table in enumerate(page_tables, 1))
    scoped_content = SourceContent(source, tables)
    pages = []
    for number, (table, unknown, rotation, problems) in enumerate(
            zip(page_tables, unresolved, rotations, notices), 1):
        review = (normalize_table(scoped_content, number, profile, period)
                  if table is not None else None)
        status = ("records" if review is not None else
                  "scanned" if problems and "Image-only" in problems[0] else
                  "ambiguous" if problems and "Multiple" in problems[0] else
                  "no_table")
        pages.append(PdfPageReview(number, source_reference(source, number),
                                   rotation, status, review, unknown, problems))
    return PdfWorkOrderReview(
        source.id, source.sha256, source.fingerprint, source.filename,
        tuple(pages), _cross_page_duplicates(pages))
