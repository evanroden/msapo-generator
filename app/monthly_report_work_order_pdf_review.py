"""Conservative, page-referenced work-order review for native-text PDFs.

This parser never OCRs, approves, persists or publishes a work-order claim.
Only a positively headed, bounded text table can produce normalized candidates.
Scans, missing work-order identities, wrapped/orphaned cells and ambiguous
tables are retained as explicit operator-review conditions, not fabricated rows.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
CROSS_PAGE_DUPLICATE = "duplicate work-order identity across PDF pages"


@dataclass(frozen=True)
class PdfPageReview:
    page: int
    source_reference: str
    rotation: int
    status: str  # records, scanned, no_table, ambiguous
    review: WorkOrderReview | None = None
    unmatched_rows: tuple[tuple[str, ...], ...] = ()
    notices: tuple[str, ...] = ()
    unmatched_origins: tuple[str, ...] = ()


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
        # Two-column WO/status or WO/date exports are candidates, not facts.
        # Missing fields retain review questions and block automatic totals.
        if (mapping.work_order is not None and
                (mapping.work_date is not None or mapping.status is not None)):
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
    """Extract native table cells with exact table/row review coordinates."""
    if page.rotation:
        page.set_rotation(0)  # Disposable view only, never saved original.
    tables = page.find_tables(strategy="text").tables
    if not tables:
        tables = page.find_tables(strategy="lines").tables
    if len(tables) > MAX_TABLES_PER_PAGE:
        raise ValueError("PDF page has too many table candidates to review safely.")

    matched, unheaded, native = [], [], []
    for table_index, table in enumerate(
            sorted(tables, key=lambda item: (item.bbox[1], item.bbox[0])), 1):
        rows = _extract_table(table)
        labeled = tuple((values, f"native table {table_index}, row {ordinal}")
                        for ordinal, values in enumerate(rows, 1) if any(values))
        native.extend(labeled)
        result = _maybe_header(rows)
        if result is None:
            unheaded.extend(labeled)
            continue
        heading_index, columns = result
        identity = suggest_mapping(columns).work_order
        data, skipped, unmatched = [], [], []
        for row_index, values in enumerate(rows[:heading_index], 1):
            if any(values):
                data.append(values)
                skipped.append(len(data))
                unmatched.append((
                    values, f"native table {table_index}, row {row_index}"))
        for row_index, values in enumerate(rows[heading_index + 1:],
                                           heading_index + 2):
            if not any(values):
                continue  # PyMuPDF text-grid spacer, not a native text row.
            data.append(values)
            slot = len(data)  # Stable normalized physical-data-row slot.
            if tuple(v.casefold() for v in values) == tuple(
                    col.casefold() for col in columns):
                skipped.append(slot)
            elif identity is None or not values[identity].strip():
                skipped.append(slot)
                unmatched.append((
                    values, f"native table {table_index}, row {row_index}"))
        matched.append((columns, data, skipped, unmatched))

    if not matched:
        notices = ("Native table cells had no supported work-order header; "
                   "review the page; no records were inferred.",) if unheaded else ()
        return (None, tuple(v for v, _ in unheaded), notices, (),
                tuple(origin for _, origin in unheaded))
    columns = matched[0][0]
    if any(candidate[0] != columns for candidate in matched[1:]):
        # Different positively identified layouts are never joined or counted.
        return (None, tuple(v for v, _ in native), (
            "Multiple work-order tables with different headers were found on "
            "one page; inspect each native table before mapping.",), (),
            tuple(origin for _, origin in native))

    original_rows, skipped, unmatched = [], [], list(unheaded)
    for _, values, ignored, uncertain in matched:
        offset = len(original_rows)
        original_rows.extend(values)
        skipped.extend(offset + index for index in ignored)
        unmatched.extend(uncertain)
    if not original_rows and not unmatched:
        return None, (), ("The table has no readable work-order rows.",), (), ()
    notices = (("Additional unheaded table cells require review; "
                "none were counted as work orders.",) if unheaded else (),)
    # Full original_rows retains skipped/missing-ID data positions. Accepted
    # SourceRow numbers refer to these slots; unmatched gets native coordinates.
    return (SourceTable("PDF page " + str(page.number + 1), columns,
                        tuple(original_rows)),
            tuple(row for row, _ in unmatched),
            tuple(note for note in notices if note), tuple(skipped),
            tuple(origin for _, origin in unmatched))


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
            skipped_rows, unmatched_origins = [], []
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
                    skipped_rows.append(())
                    unmatched_origins.append(())
                    notices.append((reason,))
                    continue
                table, unknown, problems, skipped, origins = _page_table(page)
                page_tables.append(table)
                unresolved.append(unknown)
                skipped_rows.append(skipped)
                unmatched_origins.append(origins)
                # Count every native source cell once, including ambiguous pages.
                cell_count += (len(table.columns) * len(table.rows) if table
                               else sum(len(values) for values in unknown))
                if ((table and len(table.rows) > MAX_REVIEW_ROWS) or
                        cell_count > MAX_REVIEW_CELLS):
                    raise ValueError("PDF work-order cells exceed the safe review budget.")
                if table is None:
                    notices.append(problems or (
                        "No supported native-text work-order table was found. "
                        "Review the source page manually; no rows were invented.",))
                    continue
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
    for number, (table, unknown, rotation, problems, skipped, origins) in enumerate(
            zip(page_tables, unresolved, rotations, notices, skipped_rows,
                unmatched_origins), 1):
        review = (normalize_table(scoped_content, number, profile, period)
                  if table is not None else None)
        if review is not None and skipped:
            ignored = set(skipped)
            review = replace(review, rows=tuple(
                row for row in review.rows
                if row.origin.row_number not in ignored))
        status = ("records" if review is not None else
                  "scanned" if problems and "Image-only" in problems[0] else
                  "ambiguous" if problems and "Multiple" in problems[0] else
                  "no_table")
        pages.append(PdfPageReview(number, source_reference(source, number),
                                   rotation, status, review, unknown, problems,
                                   origins))
    duplicates = _cross_page_duplicates(pages)
    if duplicates:
        collisions = set(duplicates)
        pages = [replace(page, review=replace(page.review, rows=tuple(
            replace(row, issues=(*row.issues, CROSS_PAGE_DUPLICATE))
            if (row.site, row.work_order.casefold()) in collisions
            and CROSS_PAGE_DUPLICATE not in row.issues else row
            for row in page.review.rows))) if page.review else page for page in pages]
    return PdfWorkOrderReview(
        source.id, source.sha256, source.fingerprint, source.filename,
        tuple(pages), duplicates)


def reconcile_pdf_group_duplicates(groups):
    """Re-evaluate cross-page collisions after an explicit row correction.

    Same-page collisions, exclusions, corrections and original source cells
    are never cleared by this derived-issue reconciliation.
    """
    from app.monthly_report_work_order_normalized import restore_review, review_record

    reviews = [restore_review(group["record"]) if group["record"] else None
               for group in groups]
    seen = {}
    for page, review in enumerate(reviews):
        if review is None:
            continue
        for row in review.rows:
            if row.site and row.work_order:
                seen.setdefault((row.site, row.work_order.casefold()), set()).add(page)
    collisions = {key for key, pages in seen.items() if len(pages) > 1}
    for index, review in enumerate(reviews):
        if review is None:
            continue
        rows = []
        for row in review.rows:
            issues = tuple(issue for issue in row.issues
                           if issue != CROSS_PAGE_DUPLICATE)
            if (row.site, row.work_order.casefold()) in collisions:
                issues += (CROSS_PAGE_DUPLICATE,)
            rows.append(replace(row, issues=issues))
        # A two-column PDF has no source column for site/date. Only distinct
        # explicit corrections of *every* non-excluded row can satisfy that
        # missing mapping; otherwise it stays unresolved on each edit.
        questions = [q for q in review.questions
                     if not (q.startswith("Map ") and
                             q.endswith(" before including records"))]
        for field in ("work_order", "site", "work_date", "status"):
            if getattr(review.mapping, field) is not None:
                continue
            if not rows or not all(row.excluded or (
                    getattr(row, field) and field in dict(row.corrections))
                    for row in rows):
                questions.append("Map " + field + " before including records")
        groups[index]["record"] = review_record(replace(
            review, rows=tuple(rows), questions=tuple(dict.fromkeys(questions))))
    return groups
