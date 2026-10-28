"""Conservative native Word work-order table adapter.

Source inspection already assigns each Word table a section, slot, immutable
item ID and physical body position. Reuse those facts rather than guessing from
narrative text or modifying the DOCX. This module prepares *review candidates*;
it never publishes imported rows, changes a master, or flattens a drawing.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from zipfile import ZipFile, BadZipFile

from defusedxml import ElementTree as ET

from app import monthly_report_sources as sources
from app.monthly_report_import import DocxInspection, ImportItem, inspect_docx
from app.monthly_report_model import ReportPeriod, ReportProfile, ReportTable
from app.monthly_report_sources import SourceContent, SourceTable, source_reference
from app.monthly_report_work_order_normalized import (
    WorkOrderReview, normalize_table, suggest_mapping,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_BODY_XML_BYTES = 24 * 1024 * 1024
MAX_CANDIDATE_ROWS = 20_000
MAX_CANDIDATE_CELLS = 200_000
MAX_HEADERS_TO_CHECK = 5

_UNSUPPORTED_CONTENT = {
    W + name for name in ("txbxContent", "object", "pict", "drawing", "altChunk", "sdt",
                           "del", "ins", "moveFrom", "moveTo")
}


@dataclass(frozen=True)
class WordUnmatchedRow:
    word_row: int
    cells: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class WordTableReview:
    """Native table identity, physical row origins and any unaccepted material."""
    item_id: str
    source_item: int
    word_position: int
    word_section: int
    source_reference: str
    status: str  # records, not_work_orders, unsupported_layout
    raw_rows: tuple[tuple[str, ...], ...]
    header_word_row: int = 0
    title_bands: tuple[WordUnmatchedRow, ...] = ()
    original_row_numbers: tuple[int, ...] = ()
    unmatched: tuple[WordUnmatchedRow, ...] = ()
    notices: tuple[str, ...] = ()
    review: WorkOrderReview | None = None

    @property
    def ready_for_inclusion(self):
        return (self.status == "records" and self.review is not None
                and bool(self.review.rows) and not self.review.needs_review
                and not self.unmatched and not self.notices)

    def editable_table(self) -> ReportTable | None:
        return self.review.review_table() if self.review is not None else None


@dataclass(frozen=True)
class DocxWorkOrderReview:
    source_id: str
    source_sha256: str
    source_fingerprint: str
    filename: str
    tables: tuple[WordTableReview, ...]
    ignored_table_ids: tuple[str, ...]
    source_notices: tuple[str, ...] = ()

    @property
    def ready_for_inclusion(self):
        return bool(self.tables) and all(t.ready_for_inclusion for t in self.tables)


def _native_body(raw: bytes):
    """Read only the bounded native XML; source package remains untouched."""
    try:
        with ZipFile(BytesIO(raw)) as archive:
            member = archive.getinfo("word/document.xml")
            if member.file_size > MAX_BODY_XML_BYTES:
                raise ValueError(
                    "Word body XML exceeds the safe layout-review budget. "
                    "Review a smaller original without flattening its tables.")
            root = ET.fromstring(archive.read(member))
    except (BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError("Word table structure could not be reviewed safely.") from exc
    body = root.find(W + "body")
    if body is None:
        raise ValueError("Word document has no readable body.")
    return list(body)


def _native_row_issue(row):
    """Only the full-width title band above the header may be merged safely."""
    if row.tag != W + "tr":
        return "Word row has an unsupported structural tag."
    if row.find(W + "trPr/" + W + "gridBefore") is not None or (
            row.find(W + "trPr/" + W + "gridAfter") is not None):
        return "Word row omits physical grid cells."
    cells = row.findall(W + "tc")
    if not cells:
        return "Word row has no native cells."
    for cell in cells:
        if any(node.tag in _UNSUPPORTED_CONTENT for node in cell.iter()):
            return "Word table row contains floating or unsupported editable objects."
        if cell.find(".//" + W + "tbl") is not None:
            return "Word row contains a nested table."
        if cell.find(W + "tcPr/" + W + "gridSpan") is not None or (
                cell.find(W + "tcPr/" + W + "vMerge") is not None):
            return "Word row contains merged or vertically spanning cells."
    return ""


def _full_width_band(row, values, width):
    """A single merged, visible title cell preceding a known header."""
    cells = row.findall(W + "tc")
    if len(cells) != 1 or not values or not values[0].strip() or any(
            value.strip() for value in values[1:]):
        return False
    span = cells[0].find(W + "tcPr/" + W + "gridSpan")
    if span is None:
        return False
    try:
        covered = int(span.get(W + "val", "0"))
    except ValueError:
        return False
    return covered == width and not any(
        node.tag in _UNSUPPORTED_CONTENT or node.tag == W + "tbl"
        for node in cells[0].iter())


def _find_header(raw_rows, native_rows):
    """Permit only clearly supported identity/date/status headings."""
    recognized = []
    for i, row in enumerate(raw_rows[:MAX_HEADERS_TO_CHECK]):
        if i >= len(native_rows) or _native_row_issue(native_rows[i]):
            continue
        try:
            mapping = suggest_mapping(row)
        except ValueError:
            continue
        if all(getattr(mapping, name) is not None
               for name in ("work_order", "work_date", "status")):
            recognized.append((i, row))
    return recognized[0] if len(recognized) == 1 else None, len(recognized) > 1


def _one_table(content: SourceContent, item: ImportItem, source_item: int,
               native: list, profile: ReportProfile, period: ReportPeriod):
    original = tuple(item.rows)
    reference = source_reference(content.source, source_item)
    base = dict(
        item_id=item.id, source_item=source_item, word_position=item.position,
        word_section=item.word_section, source_reference=reference,
        raw_rows=original,
    )
    if (item.position < 1 or item.position > len(native)
            or native[item.position - 1].tag != W + "tbl"):
        return WordTableReview(**base, status="unsupported_layout", notices=(
            "The inspected Word table no longer matches its native position.",))
    body = native[item.position - 1]
    native_rows = body.findall(W + "tr")
    if len(native_rows) != len(original):
        return WordTableReview(**base, status="unsupported_layout", notices=(
            "Word table row geometry differs from the inspected source. Review the original.",))
    if not original or len(original) > MAX_CANDIDATE_ROWS or len(original[0]) > 256:
        return WordTableReview(**base, status="unsupported_layout", notices=(
            "Word table exceeds the supported row/column review limits.",))
    width = len(original[0])
    if any(len(row) != width for row in original) or len(original) * width > MAX_CANDIDATE_CELLS:
        return WordTableReview(**base, status="unsupported_layout", notices=(
            "Word table has inconsistent/oversized physical cells.",))
    header, multiple = _find_header(original, native_rows)
    if header is None:
        return WordTableReview(**base, status="not_work_orders", notices=(
            "Several work-order headings conflict; select the correct native table manually."
            if multiple else
            "No unambiguous native work-order ID/date/status header was found.",))
    header_index, columns = header
    preamble, unmatched, candidates, source_rows = [], [], [], []
    for number, (row, shape) in enumerate(zip(original, native_rows), 1):
        reason = _native_row_issue(shape)
        if number <= header_index:
            # Keep exact preceding title/group rows as source context, but
            # do not interpret them as work orders.
            title = "Full-width title band" if _full_width_band(shape, row, width) else (
                reason or "Heading or other preamble before work-order header")
            preamble.append(WordUnmatchedRow(number, row, title))
            continue
        if number == header_index + 1:
            continue  # Known column headings, never an additional record.
        if not any(cell.strip() for cell in row):
            # Preserve blank source rows in the raw inventory; no record claim.
            continue
        if reason:
            unmatched.append(WordUnmatchedRow(number, row, reason))
            continue
        if tuple(v.strip().casefold() for v in row) == tuple(
                v.strip().casefold() for v in columns):
            continue  # Repeated header in a native continuation table.
        mapping = suggest_mapping(columns)
        identity = mapping.work_order
        if identity is None or not row[identity].strip():
            unmatched.append(WordUnmatchedRow(number, row,
                "Missing work-order identity or unlinked continuation text."))
            continue
        if any("\n" in cell for cell in row):
            # Explicit Word breaks may be meaningful; don't linearize them.
            unmatched.append(WordUnmatchedRow(number, row,
                "Multiline cell needs original-layout review before normalization."))
            continue
        candidates.append(row)
        source_rows.append(number)
    if not candidates:
        return WordTableReview(
            **base, status="unsupported_layout", header_word_row=header_index + 1,
            title_bands=tuple(preamble), unmatched=tuple(unmatched),
            notices=("No unambiguous work-order rows could be mapped.",))
    from app.monthly_report_content_policy import table_has_pricing
    warnings = []
    if table_has_pricing(columns, tuple(candidates)):
        warnings.append(
            "Work-order source includes pricing/financial data; remove it from "
            "client-facing rows before approval. Original remains retained.")
    normalized = normalize_table(
        SourceContent(content.source, (SourceTable(item.id, columns, tuple(candidates)),)),
        1, profile, period)
    # The canonical source row key now names this exact DOCX item index,
    # rather than another table's index in the temporary adapter view.
    normalized = replace(
        normalized, table_number=source_item, source_reference=reference,
        rows=tuple(replace(row, origin=replace(row.origin, table_number=source_item))
                   for row in normalized.rows))
    return WordTableReview(
        **base, status="records", header_word_row=header_index + 1,
        title_bands=tuple(preamble), original_row_numbers=tuple(source_rows),
        unmatched=tuple(unmatched), notices=tuple(warnings), review=normalized)


def review_docx_workorders(profile: ReportProfile, content: SourceContent,
                           period: ReportPeriod) -> DocxWorkOrderReview:
    """Only positive Activity work-order tables; no guessed cross-site routing."""
    source = content.source
    if source.suffix != ".docx":
        raise ValueError("Choose a saved Word source for native work-order review.")
    raw = sources.source_bytes(profile, source)
    from app.monthly_report_import import ImportError as WordImportError
    try:
        inspection: DocxInspection = inspect_docx(
            sources._path(profile, source.sha256, source.suffix))
        if inspection.sha256 != source.sha256:
            raise ValueError("The stored Word source changed during inspection.")
        if len(inspection.items) != len(source.page_texts):
            raise ValueError(
                "Word source inventory differs from its saved review. Re-read the file.")
        native = _native_body(raw)
    except WordImportError as exc:
        raise ValueError("The saved Word file is not safely inspectable for work orders.") from exc
    tables, ignored = [], []
    for number, item in enumerate(inspection.items, 1):
        if item.kind != "table":
            continue
        if not (item.part == "word/document.xml" and
                item.section == "activity" and item.suggested_slot == "work_orders"):
            ignored.append(item.id)
            continue
        tables.append(_one_table(content, item, number, native, profile, period))
    return DocxWorkOrderReview(
        source.id, source.sha256, source.fingerprint, source.filename,
        tuple(tables), tuple(ignored), inspection.notices)
