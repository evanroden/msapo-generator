"""Local monthly evidence ingestion, cached by digest on the runtime disk.

No model calls run here. Decode, validate, prepare thumbnails and normalize
images on the caller thread; only prepared network requests enter receipt_jobs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from io import BytesIO, StringIO
from contextlib import closing
from itertools import groupby
import codecs
import csv
import hashlib
from pathlib import Path
import re
import time
from xml.etree.ElementTree import ParseError as XMLParseError
from zipfile import BadZipFile
import zlib
from time import perf_counter

import pymupdf as fitz
from lxml.etree import XMLSyntaxError
from openpyxl import load_workbook

from app import monthly_report_library as library, monthly_report_import as docx_import, ocr
from app import monthly_report_pdf_reader as pdf_reader
from app.monthly_latency_spans import measure_span, record_span
from app.monthly_report_docx import ReportImage, normalize_report_image
from app.monthly_report_import import inspect_docx, read_import_image
from app.monthly_report_model import ReportProfile, ReportSource, ResolvedBlock
from app.monthly_report_upload_limits import byte_limit_label, source_size_error
from app.monthly_report_streamed_upload import StagedUpload
from app.monthly_report_latency_trace import mark, span, traced


CLASSIFICATIONS = (
    "Vendor service", "Water treatment", "Improvement / training photo", "CMMS export",
    "MBCx", "Utility results", "Proposal / quote", "Capital renewal", "Training", "Reference only",
)
MAX_FILE_BYTES = 30 * 1024 * 1024
MAX_REPORT_BYTES = 180 * 1024 * 1024
MAX_SOURCES = 50
MAX_REPORT_TEXT = 800_000
MAX_PAGES = 500
MAX_EMBED_PAGES = 150
MAX_CACHED_PAGE_IMAGE_BYTES = 60 * 1024 * 1024  # A single included page cannot exceed this report budget.
MAX_VISION_PAGES = ocr._MAX_PDF_PAGES
MAX_TABLE_CELLS = 200_000
MAX_TABLE_ROWS = 20_000
MAX_WORKBOOK_PARTS = 2000
MAX_WORKBOOK_BYTES = 80 * 1024 * 1024
MAX_WORKBOOK_PART_BYTES = 32 * 1024 * 1024
MAX_WORKSHEETS = 30
SUPPORTED = ocr.SUPPORTED_IMAGE_SUFFIXES | {".pdf", ".docx", ".xlsx", ".csv", ".eml", ".msg", ".txt"}
PAGE_DESTINATIONS = ("vendor_reports", "water_reports", "mbcx_report", "utility_analysis", "improvements")


@dataclass(frozen=True)
class SourceTable:
    name: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    # XLSX review provenance; CSV and legacy cache tables use safe defaults.
    hidden: bool = False
    missing_formula_cache_count: int = 0
    missing_formula_cache_cells: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceContent:
    source: ReportSource
    tables: tuple[SourceTable, ...] = ()
    # DOCX raster images correspond to item indices, not invented page numbers.
    image_items: tuple[tuple[int, str], ...] = ()
    # Disposable OCR evidence: (page, start, end, confidence, unrotated-page bbox).
    # This is retained in the source extraction cache, not human report edits.
    ocr_spans: tuple[tuple[int, int, int, float, tuple[float, float, float, float]], ...] = ()


def _path(profile: ReportProfile, digest: str, suffix: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or suffix not in SUPPORTED | {".json"}:
        raise ValueError("Invalid monthly source reference.")
    return library._profile_path(profile.contract, profile.key) / "sources" / (digest + suffix)


def file_size_limit(suffix: str) -> int:
    """One file-type admission rule for upload, stored reads, and UI guidance."""
    return docx_import.MAX_DOCX_BYTES if suffix.casefold() == ".docx" else MAX_FILE_BYTES


def source_bytes(profile: ReportProfile, source: ReportSource) -> bytes:
    path = _path(profile, source.sha256, source.suffix)
    limit = file_size_limit(source.suffix)
    if path.stat().st_size > limit:
        raise ValueError("Saved source exceeds the file limit. " + source_size_error(source.suffix, limit))
    # The original may change between stat and open. Bound the actual read
    # before hashing; never accept a truncated prefix as the saved original.
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Saved source exceeds the file limit. " + source_size_error(source.suffix, limit))
    if hashlib.sha256(raw).hexdigest() != source.sha256:
        raise ValueError("A source file failed its integrity check.")
    return raw


def _date(value: str) -> str:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def native_action_lines(source: ReportSource, *, passage_pages=None):
    """Price-free native work lines with their actual selected page origins."""
    from app.monthly_report_content_policy import contains_price, page_status
    from app.monthly_report_vendor_passages import read_vendor_document
    if passage_pages is None:
        passage_pages = read_vendor_document(source)
    found = {}
    for number in source.selected_pages:
        if not 1 <= number <= len(source.page_texts):
            continue
        text = source.page_texts[number - 1]
        if page_status(text, unreadable=number in source.needs_vision)[0] != "technical":
            continue
        if number in passage_pages:
            # Validated native PDF action spans are already complete, exact
            # source occurrences. Do not join unrelated labeled blocks.
            lines = tuple(p.text for p in passage_pages[number][0]
                          if p.field == "actions")
        else:
            # An unlabelled PDF often wraps "Inspected ... confirmed it" and
            # "did not start" into separate physical text lines. The Activity
            # editor already uses this conservative qualifier-aware grouping.
            # Reuse it *per page* before claiming completed-action evidence;
            # a truncated first line must not acquire a false positive cite.
            from app.monthly_report_structured_uploads import _logical_activity_lines
            lines = _logical_activity_lines(text.splitlines())
        for line in lines:
            line = line.strip()
            uncertain_work = re.search(
                r"\b(?:not|never|cannot|unable|recommend\w*|propos\w*|planned?|planning|"
                r"scheduled?|pending|awaiting|will|would|should|could|must|needs?|required|"
                r"if|unless|to be)\b|\b\w+n['’]t\b", line, re.I)
            if (re.search(r"\b(completed|repaired|replaced|inspected)\b", line, re.I)
                    and not uncertain_work and not contains_price(line)):
                found.setdefault(line, []).append(number)
    return tuple((line, tuple(dict.fromkeys(pages))) for line, pages in found.items())


def action_evidence(source: ReportSource):
    """Separate supported native action wording from edits needing source review.

    Never rewrite human fields. Unmatched wording may be a valid human summary,
    but must not acquire invented page citations merely because pages are selected.
    """
    supported = dict(native_action_lines(source))
    accepted, needs_review = [], []
    for line in dict.fromkeys(line.strip() for line in source.actions.splitlines() if line.strip()):
        if line in supported:
            accepted.append((line, supported[line]))
        else:
            needs_review.append(line)
    return tuple(accepted), tuple(needs_review)


def _labeled_facility(text, profile):
    """None means no label; an empty value keeps conflicting labels unresolved."""
    values = [value.strip() for value in re.findall(
        r"(?im)^[ \t]*(?:facility|site|building)[ \t]*[:=][ \t]*([^\r\n]{1,160})", text)
        if value.strip()]
    if not values:
        return None
    normalize = lambda value: " ".join(value.casefold().split())
    names = {}
    for site in profile.facilities:
        for name in (site.key, site.title, *site.aliases):
            names.setdefault(normalize(name), set()).add(site.key)
    identities = set()
    for value in values:
        label = normalize(value)
        matches = names.get(label, ())
        identities.add(("site", next(iter(matches))) if len(matches) == 1 else ("label", label))
    return values[0] if len(identities) == 1 else ""


def suggest_facts(source: ReportSource, profile: ReportProfile) -> ReportSource:
    text = "\n".join(source.page_texts)
    from app.monthly_report_vendor_passages import passage_notice
    # Never infer date/site/vendor from page furniture next to unrelated
    # physical columns. The original page text remains available for review.
    uncertain_pdf_pages = {
        number for number in range(1, len(source.page_texts) + 1)
        if source.suffix == ".pdf"
        and passage_notice(number, reason="geometry") in source.notices
    }
    metadata_text = "\n".join(
        value for number, value in enumerate(source.page_texts, 1)
        if number not in uncertain_pdf_pages)
    sample = (source.filename + "\n" + text[:30_000]).casefold()
    patterns = (("Water treatment", ("water treatment", "conductivity", "water analysis")),
                ("CMMS export", ("work order", "cmms", "task code")),
                ("MBCx", ("mbcx", "commissioning")),
                ("Utility results", ("utility results", "utility analysis", "utility consumption", "utility scorecard", "energy consumption")),
                ("Proposal / quote", ("proposal", "quotation", "quote")),
                ("Capital renewal", ("capital renewal", "end of useful life")),
                ("Training", ("training", "safety briefing")),
                ("Vendor service", ("service report", "service visit", "maintenance report")))
    hits = [kind for kind, terms in patterns if any(term in sample for term in terms)]
    # A document's own title decides its type. A vendor service report that
    # mentions a quote or a water reading in its body is still a service
    # report; the body words alone made it "Reference only", which left its
    # completed work unrouted. Conflicting titles keep the word count rule.
    from app.monthly_report_pre_model_routing import title_source_type
    titled, titles = title_source_type(text)
    title_text = "\n".join(titles).casefold()
    # A title that itself names two types ("Utility analysis and maintenance
    # report") is still mixed and waits for a person to choose.
    if titled and [kind for kind, terms in patterns
                   if any(term in title_text for term in terms)] in ([], [titled]):
        hits = [titled]
    classification = hits[0] if len(hits) == 1 else "Reference only"
    if not hits and source.suffix in ocr.SUPPORTED_IMAGE_SUFFIXES:
        classification = "Improvement / training photo"
    def labeled(label):
        match = re.search(r"(?im)^[ \t]*(?:" + label + r")[ \t]*[:=][ \t]*([^\r\n]{1,160})", metadata_text)
        return match[1].strip() if match else ""
    raw_date = labeled("service date|report date|completed date|date")
    date_match = re.search(r"\b(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4})\b", raw_date)
    facility = _labeled_facility(metadata_text, profile)
    if facility is None:
        # Filenames can suggest a document type, but cannot establish which
        # site's facts its contents describe. Scope needs native source text
        # or the user's explicit item-specific correction.
        scope_text = metadata_text[:30_000].casefold()
        matches = [f.title for f in profile.facilities if any(re.search(r"(?<!\w)" + re.escape(n.casefold()) + r"(?!\w)", scope_text) for n in (f.title, *f.aliases))]
        facility = matches[0] if len(matches) == 1 else ""
    source = replace(source, classification=classification)
    from app.monthly_report_vendor_passages import read_vendor_document
    limit_pages = set()
    passage_pages = read_vendor_document(source, limit_pages=limit_pages)
    labeled_pages = tuple(passage_pages)
    pending = [n for n, (_, review) in passage_pages.items() if review]
    from app.monthly_report_vendor_passages import FIELD_PATTERNS
    patterns = FIELD_PATTERNS
    field_values, field_pages = {}, {}
    for field, term in patterns.items():
        values = []
        field_pages[field] = []
        for n, page_text in enumerate(source.page_texts, 1):
            if n in passage_pages:
                page_values = [p.text for p in passage_pages[n][0] if p.field == field]
            else:
                page_values = [line.strip() for line in page_text.splitlines() if re.search(term, line, re.I)]
            if page_values:
                values.extend(page_values)
                field_pages[field].append(n)
        field_values[field] = "\n".join(values)
    oversized = [field for field, value in field_values.items() if len(value) > 6000] if labeled_pages else []
    from app.monthly_report_vendor_passages import passage_notice
    oversized_pages = sorted(limit_pages | {n for field in oversized for n in field_pages[field]})
    notices = tuple(dict.fromkeys((*source.notices,
        *(passage_notice(n, reason="limit") for n in oversized_pages),
        *(passage_notice(n) for n in pending if n not in oversized_pages and n not in uncertain_pdf_pages))))
    def lines(term, field=""):
        if labeled_pages and field:
            return field_values[field] if field not in oversized else ""
        return "\n".join(line.strip() for line in text.splitlines() if re.search(term, line, re.I))[:6000]
    actions = "\n".join(line for line, _ in native_action_lines(source, passage_pages=passage_pages))
    actions = "" if labeled_pages and len(actions) > 6000 else actions[:6000]
    return replace(source, notices=notices, classification=classification, confidence="medium" if len(hits) == 1 else "low",
                   vendor=labeled("vendor|contractor|service company"), facility=facility,
                   service_date=_date(date_match[0]) if date_match else "", work_order=labeled("job(?: number)?|wo(?: number)?|work order"),
                   tags=tuple(v.strip() for v in re.split(r"[,;]", labeled("equipment tags?|asset tags?")) if v.strip()),
                   actions=actions, findings=lines(r"\b(findings?|observed)\b", "findings"),
                   recommendations=lines(r"\brecommend", "recommendations"), follow_ups=lines(r"\b(follow.up|pending|scheduled)\b", "follow_ups"),
                   quotes=lines(r"\b(quoted|quotation|quote amount)\b"), out_of_limit=lines(r"\b(out.of.(?:limit|range)|above limit|below limit)\b"))


class _PlainHTML(HTMLParser):
    _BLOCKS = frozenset(("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
                         "blockquote", "pre", "dt", "dd", "table", "ul", "ol", "dl"))

    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if not self.hidden:
            if tag in self._BLOCKS or tag in ("br", "hr"):
                self.parts.append("\n")
            elif tag in ("td", "th"):
                # Cells must not concatenate numbers or source field labels.
                # Start tags also cover HTML's optional closing cell tags.
                self.parts.append("\t")
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in self._BLOCKS:
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain_html(value: str) -> str:
    reader = _PlainHTML()
    reader.feed(value)
    return "".join(reader.parts)


def _email(raw: bytes) -> tuple[str, tuple[tuple[str, bytes], ...], tuple[str, ...]]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        text = _plain_html(text)
    headers = "\n".join(f"{'Message date' if key == 'Date' else key}: {message.get(key, '')}" for key in ("Subject", "Date"))
    attachments, notices = [], []
    def direct_parts(part):
        # walk() descends through message/rfc822 attachments even when its
        # wrapper was skipped. Files in a forwarded email belong to that
        # forwarded original and require deliberate, separate import.
        if part.get_content_type() == "message/rfc822":
            notices.append("Nested email retained in the original; save its attachments separately.")
            return
        if part.is_multipart():
            for child in part.iter_parts():
                yield from direct_parts(child)
            return
        yield part

    for item in direct_parts(message):
        filename = item.get_filename()
        if filename:
            if len(attachments) >= MAX_SOURCES:
                raise ValueError("Too many email attachments; split this message before processing.")
            try:
                payload = item.get_payload(decode=True) or b""
            except (ValueError, OSError, LookupError, UnicodeError):
                # Keep one placeholder in the queue so the next attachment
                # retains its exact ordinal and gets processed independently.
                payload = b""
                notices.append(f"Email attachment {len(attachments) + 1} could not be decoded; save that item separately.")
            if item.defects:
                payload = b""
                notices.append(f"Email attachment {len(attachments) + 1} has invalid MIME encoding; save that item separately.")
            attachments.append((Path(filename.replace("\\", "/")).name, payload))
    return headers + "\n\n" + str(text), tuple(attachments), tuple(notices)


def _msg(raw: bytes) -> tuple[str, tuple[tuple[str, bytes], ...], tuple[str, ...]]:
    import olefile
    with olefile.OleFileIO(BytesIO(raw), raise_defects=olefile.DEFECT_INCORRECT) as msg:
        paths = msg.listdir()
        if len(paths) > 3000:
            raise ValueError("MSG contains too many property streams.")
        def read(path):
            if not msg.exists(path):
                return b""
            if msg.get_size(path) > MAX_FILE_BYTES:
                raise ValueError(f"MSG attachment/property exceeds {byte_limit_label(MAX_FILE_BYTES)}. Use a smaller attachment copy.")
            return msg.openstream(path).read()
        def string(prefix, tag):
            unicode = read([*prefix, "__substg1.0_" + tag + "001F"])
            if unicode:
                return unicode.decode("utf-16-le", errors="replace").rstrip("\x00")
            return read([*prefix, "__substg1.0_" + tag + "001E"]).decode("cp1252", errors="replace").rstrip("\x00")
        text = string([], "1000")
        notices = []
        if not text:
            html = read(["__substg1.0_10130102"])
            if html:
                text = _plain_html(html.decode("utf-8", errors="replace"))
            else:
                notices.append("MSG has no readable plain/HTML body. Review the original or paste its text; compressed RTF is not executed.")
        text = "Subject: " + string([], "0037") + "\n\n" + text
        attachments = []
        folders = sorted({p[0] for p in paths if p[0].startswith("__attach_version1.0_")})
        for index, folder in enumerate(folders, 1):
            if len(attachments) >= MAX_SOURCES:
                raise ValueError("Too many MSG attachments; split this message before processing.")
            filename = ""
            try:
                filename = string([folder], "3707") or string([folder], "3704")
                payload = read([folder, "__substg1.0_37010102"])
            except (ValueError, OSError, LookupError, UnicodeError):
                # One defective attachment property must not discard the
                # envelope or any preceding/following valid siblings.
                notices.append(f"MSG attachment {index} could not be read; save that item separately from the original.")
                attachments.append((Path(filename.replace("\\", "/")).name if filename else
                                    f"unreadable-attachment-{index}.msg", b""))
                continue
            if payload and filename:
                attachments.append((Path(filename.replace("\\", "/")).name, payload))
            else:
                notices.append(f"MSG attachment {index} has no readable file data or name; review it in the original.")
                attachments.append((Path(filename.replace("\\", "/")).name if filename else
                                    f"unreadable-attachment-{index}.msg", b""))
        return text, tuple(attachments), tuple(notices)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _table(name, records, *, strict_columns=False, csv_headerless=False) -> SourceTable:
    rows, cells = [], 0
    for record in records:
        row = tuple(_cell(v) for v in record)
        cells += len(row)
        filled = any(c != "" for c in row)
        if strict_columns and filled and rows and len(row) != len(rows[0]):
            # A bare '12,345.67' in a comma-separated file becomes two
            # cells and could move a price into a nonprice client column.
            # Do not guess how to rejoin columns or silently trim cells.
            # Checked before the budget: a separator its own rows contradict
            # is malformed, so it cannot veto the consistent reading by size.
            raise ValueError(
                "CSV rows have different column counts. Quote any values "
                "containing commas (for example, a monetary amount), then upload again."
            )
        if len(rows) >= MAX_TABLE_ROWS or cells > MAX_TABLE_CELLS or len(row) > 200:
            raise ValueError("Spreadsheet exceeds the row/column review budget; export a smaller date range.")
        if filled:
            rows.append(row)
    if not rows:
        raise ValueError("Spreadsheet has no nonempty rows.")
    width = max(map(len, rows))
    if csv_headerless and _csv_first_row_is_data(rows[0]):
        # A definite first data record is not a heading. Keep its *original*
        # physical cells, including blanks, duplicated values and leading 0s.
        # Generic headings require explicit physical-position mapping before
        # a work-order fact can enter the report.
        return SourceTable(name, tuple(f"Column {i + 1}" for i in range(width)),
                           tuple(row + ("",) * (width - len(row)) for row in rows))
    columns = []
    for i in range(width):
        value = rows[0][i] if i < len(rows[0]) else ""
        title = value.strip() or f"Column {i+1}"
        base, count = title, 2
        while title in columns:
            title = f"{base} ({count})"
            count += 1
        columns.append(title)
    return SourceTable(name, tuple(columns), tuple(r + ("",) * (width - len(r)) for r in rows[1:]))


_CSV_DATA_STATES = {
    "open", "pending", "inprogress", "notstarted", "unresolved",
    "awaitingparts", "completed", "complete", "closed", "finished", "done",
}
_CSV_HEADER_LABELS = {
    "workorder", "workorderid", "workordernumber", "wonumber", "wo",
    "ticketnumber", "status", "currentstatus", "workorderstatus",
    "date", "workdate", "servicedate", "receiveddate", "facility", "site",
    "location", "building", "hospital",
}
_CSV_DATA_DATE = re.compile(
    r"(?:19|20)\d{2}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{4}"
)
_CSV_ID_VALUE = re.compile(r"(?:[A-Za-z]{1,12}[-_:/ ]*)?\d{1,18}(?:[-_:/]\d{1,18})?")


def _csv_first_row_is_data(row) -> bool:
    """Only promote strongly identified headerless CMMS records.

    An arbitrary unlabeled table cannot be guessed safely; it retains the
    existing header interpretation. A date with either a recognized work-order
    state or a position-one order identifier can preserve the first record as
    data; neither condition is permission to choose field mappings or a site.
    """
    if len(row) < 3:
        return False
    words = tuple(re.sub(r"[^a-z0-9]", "", str(cell).casefold()) for cell in row)
    if any(word in _CSV_HEADER_LABELS for word in words):
        return False
    values = tuple(str(cell).strip() for cell in row)
    # Unknown/deferred status is precisely the sort of value that must stay
    # visible for correction, not disappear as a mistaken heading.
    return (any(_CSV_DATA_DATE.fullmatch(value) for value in values)
            and (any(word in _CSV_DATA_STATES for word in words)
                 or bool(_CSV_ID_VALUE.fullmatch(values[0]))))


def _csv_unicode_encoding(raw: bytes) -> str | None:
    """Honor only explicit signatures; UTF-32 LE shares UTF-16 LE's prefix."""
    if raw.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return "utf-32"
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    return None


def _csv_table(text: str) -> SourceTable:
    """Select only a uniquely consistent CSV dialect within the review budget.

    Sniffer can reject a valid delimiter when quoted cells contain that same
    separator or a newline. Probe the four already-supported separators with
    strict RFC-style double-quote handling over the *whole* source instead of
    treating a failed sample sniff as proof of comma CSV. A one-column table
    is legitimate only if every dialect agrees and none reports malformed
    rows; it is not a fallback for an inconsistent multi-column export.
    """
    candidates = []
    single_column = None
    malformed = False
    over_budget = None
    inconsistent_columns = None
    for delimiter in (",", ";", "\t", "|"):
        try:
            table = _table("CSV", csv.reader(
                StringIO(text, newline=""), delimiter=delimiter,
                quotechar='"', doublequote=True, strict=True,
            ), strict_columns=True, csv_headerless=True)
        except csv.Error:
            malformed = True
            continue
        except ValueError as exc:
            if "review budget" in str(exc):
                # An alternate separator cannot bypass row/cell/column limits.
                over_budget = exc
            elif "different column counts" in str(exc):
                inconsistent_columns = exc
                malformed = True
            else:
                malformed = True
            continue
        if len(table.columns) > 1:
            candidates.append((delimiter, table))
        elif single_column is None:
            single_column = table
    if over_budget is not None:
        raise over_budget
    if len(candidates) == 1:
        return candidates[0][1]
    if len(candidates) > 1:
        labels = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
        choices = ", ".join(labels[delimiter] for delimiter, _ in candidates)
        raise ValueError(
            f"CSV delimiter is ambiguous ({choices}). Export with one consistent "
            "delimiter and quote values that contain separators, then upload again."
        )
    if inconsistent_columns is not None:
        raise inconsistent_columns
    if malformed or single_column is None:
        raise ValueError(
            "CSV delimiter or quoting could not be determined from consistent "
            "columns. Export with one delimiter and quote fields containing "
            "separators or newlines, then upload again."
        )
    return single_column


def _cached_empty_formula_strings(raw: bytes, worksheet_path: str | None) -> frozenset[str]:
    """Return formula cells whose saved result is an explicit empty string.

    Excel and LibreOffice store ``=IF(A2="","",A2)`` with ``t="str"`` and an
    empty ``<v>``. openpyxl's data-only view returns None both for that cell
    and for a formula with no saved result, so only the stored XML separates a
    trusted cached blank from a missing result. Nothing is evaluated here. An
    unknown worksheet part returns nothing: every such cell stays untrusted.
    """
    from zipfile import ZipFile

    from openpyxl.xml.constants import SHEET_MAIN_NS
    from openpyxl.xml.functions import iterparse
    cell_tag, formula_tag, value_tag, row_tag = (
        f"{{{SHEET_MAIN_NS}}}{name}" for name in ("c", "f", "v", "row"))
    found = set()
    with ZipFile(BytesIO(raw)) as archive:
        if not worksheet_path or worksheet_path not in archive.namelist():
            return frozenset()
        with archive.open(worksheet_path) as part:
            for _event, element in iterparse(part):
                if element.tag == cell_tag:
                    stored = element.find(value_tag)
                    if (element.get("t") == "str" and element.get("r")
                            and element.find(formula_tag) is not None
                            and stored is not None and not stored.text):
                        found.add(element.get("r").upper())
                    element.clear()
                elif element.tag == row_tag:
                    element.clear()
    return frozenset(found)


def _spreadsheet(raw: bytes, suffix: str) -> tuple[SourceTable, ...]:
    if suffix == ".csv":
        encoding = _csv_unicode_encoding(raw)
        if encoding:
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError as exc:
                raise ValueError("CSV Unicode encoding could not be read. Export a fresh UTF-8 CSV copy.") from exc
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252")
        return (_csv_table(text),)
    from app.monthly_report_xlsx_currency import currency_evidence_value, preserve_currency_number_types
    # Enforce compressed-package and expanded-part budgets before either
    # read-only workbook view decodes XML or shared strings.
    from zipfile import ZipFile
    try:
        archive = ZipFile(BytesIO(raw))
    except BadZipFile as exc:
        raise ValueError("Workbook is not a valid XLSX package. Export a fresh XLSX or CSV copy.") from exc
    with archive as z:
        infos = z.infolist()
        names = [part.filename for part in infos]
        if len(set(names)) != len(names):
            raise ValueError("Workbook contains duplicate package parts. Export a fresh XLSX or CSV copy.")
        if (any(name.startswith("/") or "\\" in name or ".." in name.split("/") for name in names)
                or any(part.flag_bits & 1 for part in infos)
                or any("vbaproject" in name.casefold() for name in names)):
            raise ValueError("Workbook has unsafe package parts. Export a macro-free XLSX copy.")
        if len(infos) > MAX_WORKBOOK_PARTS:
            raise ValueError(f"Workbook exceeds {MAX_WORKBOOK_PARTS:,} package parts. Upload the required sheets separately.")
        if sum(part.file_size for part in infos) > MAX_WORKBOOK_BYTES:
            raise ValueError(f"Expanded workbook exceeds the {byte_limit_label(MAX_WORKBOOK_BYTES)} safe parsing budget. Upload the required sheets separately.")
        if any(part.file_size > MAX_WORKBOOK_PART_BYTES for part in infos):
            raise ValueError(f"A workbook part exceeds the {byte_limit_label(MAX_WORKBOOK_PART_BYTES)} safe parsing budget. Export the required cells as CSV or a smaller workbook.")
    workbook = formula_workbook = None
    try:
        # Openpyxl never evaluates formulas. A separate read-only formula view
        # identifies which blank/error values are NOT trusted cached results.
        workbook = load_workbook(BytesIO(raw), read_only=True, data_only=True, keep_links=False)
        formula_workbook = load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
        if len(workbook.worksheets) > MAX_WORKSHEETS:
            raise ValueError(f"Workbook exceeds {MAX_WORKSHEETS:,} worksheets; upload the required sheets separately.")
        preserve_currency_number_types(workbook)
        tables, total = [], 0
        for sheet, formula_sheet in zip(workbook.worksheets, formula_workbook.worksheets):
            if (sheet.max_row and sheet.max_row > MAX_TABLE_ROWS
                    or sheet.max_column and sheet.max_column > 200
                    or (sheet.max_row or 0) * (sheet.max_column or 0) > MAX_TABLE_CELLS):
                raise ValueError("Worksheet dimensions exceed the review budget.")
            if total + (sheet.max_row or 0) * (sheet.max_column or 0) > MAX_TABLE_CELLS:
                raise ValueError("Workbook cells exceed the total review budget.")
            missing, missing_count, cached_empty = [], 0, None

            def records():
                nonlocal missing_count, cached_empty
                for row, formula_row in zip(sheet.iter_rows(), formula_sheet.iter_rows()):
                    converted = []
                    for cell, original in zip(row, formula_row):
                        value = cell.value
                        if original.data_type == "f" and value is None and cell.data_type == "str":
                            # The data-only view also returns None for a saved
                            # empty-string result; only the stored XML differs.
                            if cached_empty is None:
                                cached_empty = _cached_empty_formula_strings(
                                    raw, getattr(sheet, "_worksheet_path", None))
                            if original.coordinate in cached_empty:
                                value = ""
                        if original.data_type == "f" and (value is None or cell.data_type == "e"):
                            missing_count += 1
                            if len(missing) < 16:
                                missing.append(original.coordinate)
                            value = None  # Never turn an uncached/error formula into a result.
                        converted.append(currency_evidence_value(value, cell.number_format))
                    yield tuple(converted)

            try:
                table = _table(sheet.title, records())
            except ValueError as exc:
                if str(exc) == "Spreadsheet has no nonempty rows.":
                    if missing_count:
                        places = ", ".join(missing)
                        raise ValueError(f"Worksheet {sheet.title} has no trusted cached formula values ({places}); recalculate and save the original workbook.") from exc
                    continue
                raise
            total += (sheet.max_row or 0) * (sheet.max_column or 0)
            if total > MAX_TABLE_CELLS:
                raise ValueError("Workbook cells exceed the total review budget.")
            tables.append(replace(table, hidden=sheet.sheet_state != "visible",
                                  missing_formula_cache_count=missing_count,
                                  missing_formula_cache_cells=tuple(missing)))
        if not tables:
            raise ValueError("Workbook has no nonempty worksheets.")
        return tuple(tables)
    except (XMLParseError, XMLSyntaxError) as exc:
        raise ValueError("Workbook XML could not be read. Export a fresh XLSX or CSV copy.") from exc
    except TypeError as exc:
        raise ValueError("Workbook structure could not be read. Export a fresh XLSX or CSV copy.") from exc
    finally:
        if formula_workbook is not None:
            formula_workbook.close()
        if workbook is not None:
            workbook.close()


def _cached_extraction(data, digest, suffix):
    """Decode only disposable extraction records, without coercing bad JSON shapes."""
    def sequence(value):
        if not isinstance(value, list):
            raise ValueError("Invalid source extraction cache sequence.")
        return value

    for name in ("client_page_policy", "native_action_policy", "vendor_passage_policy", "csv_dialect_policy", "csv_headerless_policy"):
        if type(data.get(name, 0)) is not int or data.get(name, 0) < 0:
            raise ValueError("Invalid source extraction cache policy.")
    record = data["source"]
    if not isinstance(record, dict):
        raise ValueError("Invalid source extraction cache record.")
    source = library.source_from_dict(record)
    if (source.id, source.sha256, source.suffix) != (digest, digest, suffix):
        raise ValueError("Source extraction cache identity changed.")
    for name, value in asdict(source).items():
        # The current serializer already validates this optional typed record.
        # It is neither text nor a sequence; legacy caches may omit it.
        if name == "financial_source_review":
            continue
        if name == "attachment_index":
            if type(value) is not int or value < 0:
                raise ValueError("Invalid attachment position in source cache.")
            continue
        if isinstance(value, tuple):
            sequence(record.get(name, []))
        elif not isinstance(value, str):
            raise ValueError("Invalid source extraction cache text.")
    if any(not isinstance(text, str) for name in ("tags", "page_texts", "notices")
           for text in getattr(source, name)):
        raise ValueError("Invalid source extraction cache text.")
    if any(type(page) is not int or not 1 <= page <= len(source.page_texts)
           for name in ("selected_pages", "needs_vision") for page in getattr(source, name)):
        raise ValueError("Invalid source extraction cache page.")
    for name in ("captions", "client_page_reviews", "client_page_exclusions"):
        if any(not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int
               or not isinstance(pair[1], str) for pair in record.get(name, [])):
            raise ValueError("Invalid source extraction cache page metadata.")
    tables = []
    for table in sequence(data.get("tables", [])):
        columns = sequence(table["columns"])
        rows = sequence(table["rows"])
        if (not isinstance(table["name"], str) or any(not isinstance(title, str) for title in columns)
                or any(len(sequence(row)) != len(columns) or any(not isinstance(cell, str) for cell in row)
                       for row in rows)):
            raise ValueError("Invalid source extraction cache table.")
        hidden = table.get("hidden", False)
        missing_count = table.get("missing_formula_cache_count", 0)
        missing_cells = table.get("missing_formula_cache_cells", [])
        if (type(hidden) is not bool or type(missing_count) is not int
                or not 0 <= missing_count <= MAX_TABLE_CELLS
                or not isinstance(missing_cells, list) or len(missing_cells) > 16
                or any(not isinstance(cell, str) or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", cell)
                       for cell in missing_cells)):
            raise ValueError("Invalid source extraction cache workbook provenance.")
        tables.append(SourceTable(table["name"], tuple(columns), tuple(tuple(row) for row in rows),
                                  hidden, missing_count, tuple(missing_cells)))
    if suffix in (".csv", ".xlsx") and (not tables or any(not table.columns for table in tables)):
        raise ValueError("Invalid source extraction cache table.")
    images = sequence(data.get("image_items", []))
    if any(not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int
           or not 1 <= pair[0] <= len(source.page_texts) or not isinstance(pair[1], str) for pair in images):
        raise ValueError("Invalid source extraction cache image.")
    spans = sequence(data.get("ocr_spans", []))
    validated_spans = []
    for entry in spans:
        if (not isinstance(entry, list) or len(entry) != 5
                or type(entry[0]) is not int or not 1 <= entry[0] <= len(source.page_texts)
                or type(entry[1]) is not int or type(entry[2]) is not int
                or not 0 <= entry[1] < entry[2] <= len(source.page_texts[entry[0] - 1])
                or not isinstance(entry[3], (float, int)) or isinstance(entry[3], bool)
                or not 0 <= entry[3] <= 100 or not isinstance(entry[4], list)
                or len(entry[4]) != 4 or any(not isinstance(v, (float, int))
                                             or isinstance(v, bool) for v in entry[4])
                or not 0 <= entry[4][0] < entry[4][2]
                or not 0 <= entry[4][1] < entry[4][3]):
            raise ValueError("Invalid PDF OCR extraction cache span.")
        validated_spans.append((entry[0], entry[1], entry[2], float(entry[3]), tuple(entry[4])))
    return SourceContent(source, tuple(tables), tuple(tuple(pair) for pair in images),
                         tuple(validated_spans))


def _same_source_bytes(path, raw):
    """Verify a cached original with bounded reads before skipping its republish."""
    library._qa_path_guard(path)
    if path.is_symlink():
        return False
    try:
        with path.open("rb") as stored:
            for offset in range(0, len(raw), 1024 * 1024):
                chunk = raw[offset:offset + 1024 * 1024]
                if stored.read(len(chunk)) != chunk:
                    return False
            matches = not stored.read(1)
    except FileNotFoundError:
        return False
    if matches:
        library._qa_path_guard(path)
    return matches


def ingest(profile: ReportProfile, filename: str, raw: bytes | StagedUpload, *, max_new_text: int | None = None) -> tuple[SourceContent, tuple[tuple[str, bytes], ...]]:
    """Cache local extraction. Caller enforces aggregate count/byte/text budgets."""
    mark("upload_received")
    from app.monthly_report_content_policy import suggested_pages
    filename = Path(filename.replace("\\", "/")).name
    suffix = Path(filename).suffix.casefold()
    if suffix not in SUPPORTED:
        raise ValueError("Unsupported file type. Choose PDF, DOCX, XLSX, CSV, EML, MSG, TXT or a supported image.")
    staged = raw if isinstance(raw, StagedUpload) else None
    size = staged.size if staged is not None else len(raw)
    if not size:
        raise ValueError("This source file is empty. Choose a nonempty copy.")
    limit = file_size_limit(suffix)
    if size > limit:
        raise ValueError(source_size_error(suffix, limit))
    with span("hash_cache_lookup"):
        digest = staged.sha256 if staged is not None else hashlib.sha256(raw).hexdigest()
        path, cache = _path(profile, digest, suffix), _path(profile, digest, ".json")
        attachments = ()
        # CSV policy requires bytes; warm cached non-CSV sources do not.
        if staged is not None:
            raw = staged.path.read_bytes() if suffix == ".csv" else None
        unicode_csv = suffix == ".csv" and _csv_unicode_encoding(raw) is not None
        rebuild_cache = False
        if cache.exists() and path.exists() and suffix not in (".eml", ".msg"):
            library._qa_path_guard(cache)
            try:
                data = library._read(cache)
                content = _cached_extraction(data, digest, suffix)
            except (ValueError, TypeError, LookupError, AttributeError):
                # Cache damage is recoverable; a stale/foreign QA namespace is not.
                library._qa_path_guard(cache)
                content = None
            # Only previously cached one-column CSVs can retain the old failed
            # Sniffer fallback; already-correct multi-column caches stay warm.
            # This disposable-extraction refresh never alters saved human edits.
            old_csv_one_column = (suffix == ".csv" and content is not None
                                  and data.get("csv_dialect_policy") != 1
                                  and any(len(table.columns) == 1 for table in content.tables))
            # Older multi-column caches may have consumed a headerless first row.
            # Rebuild only that disposable view; keep correct legacy caches warm.
            old_csv_headerless = (suffix == ".csv" and content is not None
                                  and data.get("csv_headerless_policy") != 1
                                  and any(_csv_first_row_is_data(table.columns)
                                          for table in content.tables))
            # Provenance policy 1 also counted a saved empty-string formula
            # result as missing. Rebuild only caches that recorded missing
            # results; every other workbook cache stays warm.
            old_xlsx_missing = (suffix == ".xlsx" and content is not None
                                and data.get("xlsx_provenance_policy") == 1
                                and any(table.missing_formula_cache_count for table in content.tables))
            # Keep signed-Unicode migration independent of the delimiter policy.
            if (content is not None and not old_csv_one_column and not old_csv_headerless
                    and not old_xlsx_missing
                    and (not unicode_csv or data.get("csv_unicode_policy") == 1)
                    and (suffix != ".xlsx" or (type(data.get("xlsx_currency_policy")) is int
                                              and data["xlsx_currency_policy"] == 1
                                               and type(data.get("xlsx_provenance_policy")) is int
                                               and data["xlsx_provenance_policy"] in (1, 2)))
                    and (suffix != ".pdf" or (data.get("vendor_passage_policy", 0) >= 8
                                               and data.get("pdf_scan_policy", 0) >= 1
                                               and data.get("pdf_reader_policy") == 1))):
                source = content.source
                if data.get("client_page_policy", 0) < 1 and suffix not in (".csv", ".xlsx"):
                    source = replace(source, selected_pages=suggested_pages(source))
                if data.get("native_action_policy", 0) < 1:
                    # This is the original extraction cache, never a reviewed draft.
                    source = replace(source, actions="\n".join(line for line, _ in native_action_lines(source))[:6000])
                if _labeled_facility("\n".join(source.page_texts), profile) == "":
                    # Correct only the disposable extraction view. Saved/manual
                    # sources are overlaid by restore_sources and remain unchanged.
                    source = replace(source, facility="")
                return replace(content, source=replace(source, filename=filename)), ()
            rebuild_cache = True
    with span("parse"):
        if staged is None and (not rebuild_cache or not _same_source_bytes(path, raw)):
            library._atomic_write(path, raw)
        # Native DOCX reads the stage; other parsers get one buffer after admission.
        if staged is not None and suffix != ".docx" and raw is None:
            with staged.path.open("rb") as stream:
                raw = stream.read(limit + 1)
            if len(raw) != size:
                raise ValueError("The staged source changed while it was being read.")
        page_texts, needs_vision, tables, image_items, notices = [], [], (), [], []
        pdf_text_blocks = []
        pdf_ocr_spans = []
        span_budget_exceeded = False
        extraction_started = perf_counter()
        if suffix == ".pdf":
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                if pdf.is_encrypted and not pdf.authenticate(""):
                    raise ValueError("PDF needs a password. Upload an unlocked copy.")
                if len(pdf) > MAX_PAGES:
                    raise ValueError(f"PDF exceeds {MAX_PAGES:,} pages; select a smaller document range.")
                ocr_attempts = 0
                ocr_deadline = time.monotonic() + pdf_reader.MAX_LOCAL_OCR_SECONDS
                extracted_chars = 0
                from app.monthly_report_vendor_passages import block_spans, MAX_VENDOR_BLOCK_SPANS, passage_notice
                for number, page in enumerate(pdf, 1):
                    native = page.get_text().strip()
                    needs_ocr, review_notice = ocr._page_visual_decision(page, native_text=native)
                    reading = pdf_reader.read_page(
                        page, number, native_text=native,
                        needs_ocr=needs_ocr,
                        may_ocr=ocr_attempts < pdf_reader.MAX_LOCAL_OCR_PAGES,
                        deadline=ocr_deadline,
                    )
                    ocr_attempts += int(reading.attempted_ocr)
                    if reading.needs_vision or review_notice:
                        # Keep an image-backed page unreviewed even if it appears
                        # blank, has a searchable overlay or was read by local OCR:
                        # none of these is human proof.
                        needs_vision.append(number)
                    if reading.notice:
                        notices.append(reading.notice)
                    if review_notice:
                        notices.append(f"Page {number}: {review_notice}.")
                    text = reading.text
                    page_texts.append(text)
                    pdf_ocr_spans.extend(reading.ocr_spans)
                    extracted_chars += len(text)
                    if extracted_chars > ocr._MAX_EXTRACTED_CHARS:
                        raise ValueError(
                            f"PDF text exceeds {ocr._MAX_EXTRACTED_CHARS:,} characters; "
                            "keep within the text limit while retaining up to 500 pages."
                        )
                    if not span_budget_exceeded:
                        # Native paragraph proofs are invalid for OCR-augmented or
                        # reordered text unless geometry still tiles exactly.
                        geometry_uncertain = set()
                        spans = block_spans(page, text, number, ambiguous_pages=geometry_uncertain)
                        if geometry_uncertain:
                            notices.append(passage_notice(number, reason="geometry"))
                        if len(pdf_text_blocks) + len(spans) > MAX_VENDOR_BLOCK_SPANS:
                            # No partial-page certainty after exhausting metadata capacity.
                            # Raw original/page text and ordinary review remain available.
                            pdf_text_blocks.clear()
                            span_budget_exceeded = True
                        else:
                            pdf_text_blocks.extend(spans)
        elif suffix in ocr.SUPPORTED_IMAGE_SUFFIXES:
            if suffix == ".mpo":
                from app.mpo_images import frame_count
                count = frame_count(raw)
                for index in range(count):
                    try:
                        normalize_report_image(raw, suffix, frame_index=index)
                    except (OSError, EOFError, SyntaxError) as exc:
                        # Pillow can report truncated MPO raster data only when a
                        # selected frame is decoded, after its header inventory.
                        raise ValueError("MPO image data is damaged or truncated. Export a fresh copy.") from exc
                page_texts, needs_vision = [""] * count, list(range(1, count + 1))
                notices.append("MPO pictures are separate source pages in their original order; review each picture before inclusion.")
            else:
                try:
                    normalize_report_image(raw, suffix)  # Validate before caching or paid work.
                except (OSError, EOFError, SyntaxError) as exc:
                    # These exceptions originate inside the bounded image decoder,
                    # not the surrounding original/cache storage operations. Do not
                    # mislabel invalid image bytes as a transient storage outage.
                    raise ValueError("Image data is damaged or unreadable. Export a fresh copy.") from exc
                page_texts, needs_vision = [""], [1]
        elif suffix == ".txt":
            page_texts = [raw.decode("utf-8-sig")]
        elif suffix in (".csv", ".xlsx"):
            tables = _spreadsheet(raw, suffix)
            page_texts = ["\n".join(["\t".join(t.columns), *("\t".join(r) for r in t.rows)]) for t in tables]
            if suffix == ".xlsx":
                notices.append("Workbook values use stored formula results; formulas are never executed. Missing cached results remain blank.")
                hidden = [table.name for table in tables if table.hidden]
                if hidden:
                    notices.append("Hidden worksheets retained for explicit review, not automatic totals: "
                                   + ", ".join(hidden) + ".")
                missing_count = sum(table.missing_formula_cache_count for table in tables)
                if missing_count:
                    examples = ", ".join(f"{table.name}!{cell}" for table in tables
                                         for cell in table.missing_formula_cache_cells[:3])
                    notices.append(f"{missing_count} formula cells without trusted cached results "
                                   f"({examples}); recalculate and save the source workbook before accepting these cells.")
        elif suffix == ".docx":
            inspected = inspect_docx(staged.path if staged is not None else path)
            for number, item in enumerate(inspected.items, 1):
                page_texts.append(item.text or "\n".join("\t".join(r) for r in item.rows))
                if item.kind == "unsupported":
                    notices.append(f"Item {number}: {item.note or 'This original item could not be read.'}")
                elif item.note == "Unplaced package asset; confirm whether it belongs in this report.":
                    notices.append(f"Item {number}: {item.note}")
                if item.kind == "image":
                    image_items.append((number, item.id))
                    needs_vision.append(number)
            notices.extend(inspected.notices)
            # Only this new inspection route has retained every unsupported-item
            # notice. Old cached records keep their broader artwork-review notice.
            notices.append("DOCX selections are extracted items, not Word page numbers.")
        else:
            text, attachments, extra = _email(raw) if suffix == ".eml" else _msg(raw)
            page_texts = [text]
            notices.extend(extra)
        record_span("source_extraction", perf_counter() - extraction_started)
        extracted_chars = sum(map(len, page_texts))
        if extracted_chars > ocr._MAX_EXTRACTED_CHARS:
            raise ValueError(f"Source text exceeds {ocr._MAX_EXTRACTED_CHARS:,} characters; split the input before reading.")
        if max_new_text is not None and extracted_chars > max_new_text:
            raise ValueError(f"Total extracted text exceeds {MAX_REPORT_TEXT:,} characters. Remove unused sources or split the report.")
        source = ReportSource(digest, filename, digest, suffix, page_texts=tuple(page_texts),
                              pdf_text_blocks=tuple(pdf_text_blocks),
                              selected_pages=tuple(range(1, len(page_texts)+1)), needs_vision=tuple(needs_vision), notices=tuple(notices))
        if suffix not in (".csv", ".xlsx"):
            source = replace(source, selected_pages=suggested_pages(source))
        with measure_span("source_mapping"):
            source = suggest_facts(source, profile)
        content = SourceContent(source, tables, tuple(image_items), tuple(pdf_ocr_spans))
        if staged is not None:
            # Publish only after extraction and aggregate-text validation.
            from app.monthly_report_streamed_upload import publish_staged_original
            publish_staged_original(path, staged)
        library._atomic_write(cache, library._json({"schema": 1, "client_page_policy": 1,
            "native_action_policy": 1, "vendor_passage_policy": 8,
            **({"pdf_scan_policy": 1, "pdf_reader_policy": 1} if suffix == ".pdf" else {}),
            **({"xlsx_currency_policy": 1, "xlsx_provenance_policy": 2} if suffix == ".xlsx" else {}),
            **({"csv_unicode_policy": 1} if unicode_csv else {}),
            **({"csv_dialect_policy": 1, "csv_headerless_policy": 1} if suffix == ".csv" else {}), **asdict(content)}))
        return content, attachments



def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verified_original(profile, source) -> None:
    """Verify a saved duplicate without an upload-sized allocation."""
    path = _path(profile, source.sha256, source.suffix)
    library._qa_path_guard(path)
    if path.is_symlink() or path.stat().st_size > file_size_limit(source.suffix):
        raise ValueError("Saved source failed integrity verification.")
    if _file_sha256(path) != source.sha256:
        raise ValueError("Saved source failed integrity verification.")


def _discard_rejected(path, cache, digest, already_present, existing_cache):
    """Delete only what a just-rejected upload wrote (#284 owner decision).

    Rejected uploads are removed right away. Older files and accepted originals
    are never touched: a blob that existed before this attempt, a blob whose
    bytes no longer match the rejected upload, and a pre-existing cache all stay.
    """
    if not already_present:
        try:
            if path.is_file() and not path.is_symlink() and (
                    _file_sha256(path) == digest):
                path.unlink()
        except OSError:
            pass
    if not existing_cache:
        try:
            if not cache.is_symlink():
                cache.unlink(missing_ok=True)
        except OSError:
            pass


def ingest_batch(profile: ReportProfile, files: tuple[tuple[str, bytes], ...], existing: tuple[SourceContent, ...] = ()) -> tuple[tuple[SourceContent, ...], tuple[str, ...]]:
    sources = {c.source.sha256: c for c in existing}
    sizes, messages = 0, []
    counted_sizes = {}
    for item in existing:
        # Missing originals remain in the draft inventory and its output
        # dependency checks. They cannot prevent other files from being read.
        try:
            counted_sizes[item.source.sha256] = _path(profile, item.source.sha256, item.source.suffix).stat().st_size
            sizes += counted_sizes[item.source.sha256]
        except (ValueError, OSError):
            label = Path(item.source.filename.replace("\\", "/")).name
            messages.append(f"Saved source unavailable: {label}. Replace it before generating dependent content.")
    text_size = sum(len(t) for c in existing for t in c.source.page_texts)
    queue = [(name, raw, 0, "", 0) for name, raw in files]
    while queue:
        filename, raw, depth, parent_digest, attachment_index = queue.pop(0)
        filename = Path(filename.replace("\\", "/")).name
        digest = raw.sha256 if isinstance(raw, StagedUpload) else hashlib.sha256(raw).hexdigest()
        size = raw.size if isinstance(raw, StagedUpload) else len(raw)
        parent = sources.get(parent_digest) if parent_digest else None
        parent_label = parent.source.filename if parent else parent_digest[:12]
        label = (f"{filename} (attachment {attachment_index} of {parent_label})"
                 if parent_digest else filename)
        if digest in sources:
            # Re-uploading the identical accepted original can repair a missing
            # or corrupted stored copy without changing the report's reviewed
            # source identity, citations, or completed historical snapshots.
            existing_source = sources[digest].source
            try:
                # A repeat upload already supplies the same SHA-addressed
                # bytes. UI duplicate checks need only the verified original
                # revision; actual consumers still read/hash the full source.
                if isinstance(raw, StagedUpload):
                    _verified_original(profile, existing_source)
                else:
                    from app.monthly_report_source_revision import verified_source_revision
                    verified_source_revision(profile, existing_source)
            except (ValueError, OSError):
                try:
                    if isinstance(raw, StagedUpload):
                        from app.monthly_report_streamed_upload import publish_staged_original
                        publish_staged_original(_path(profile, digest, existing_source.suffix), raw)
                        _verified_original(profile, existing_source)
                    else:
                        library._atomic_write(_path(profile, digest, existing_source.suffix), raw)
                        source_bytes(profile, existing_source)
                except (ValueError, OSError):
                    messages.append(f"Could not restore saved source: {label}. The report still needs a valid copy.")
                    continue
                messages.append(f"Saved source restored: {label}. Prior reviews and report history are unchanged.")
                # Replace the size already counted for a damaged copy. Missing
                # originals contribute zero until their successful restoration.
                sizes += size - counted_sizes.get(digest, 0)
                counted_sizes[digest] = size
            else:
                messages.append(f"Duplicate skipped: {label}")
            continue
        if len(sources) >= MAX_SOURCES:
            messages.append(f"Not read: {label}. Report limit is {MAX_SOURCES:,} source files including attachments. Remove unused sources before adding more.")
            continue
        if sizes + size > MAX_REPORT_BYTES:
            messages.append(f"Not read: {label}. Report limit is {byte_limit_label(MAX_REPORT_BYTES)} of source files including attachments. Remove unused sources or use a smaller copy.")
            continue
        suffix = Path(filename).suffix.casefold()
        if suffix not in SUPPORTED or depth > 1:
            messages.append(f"Not read: {label}. Unsupported or nested attachment; retained in the original email.")
            continue
        path = _path(profile, digest, suffix)
        already_present = path.exists()
        cache = _path(profile, digest, ".json")
        existing_cache = cache.exists()
        try:
            if isinstance(raw, StagedUpload):
                content, attachments = ingest(profile, filename, raw, max_new_text=MAX_REPORT_TEXT - text_size)
            else:
                content, attachments = ingest(profile, filename, raw)
            added = sum(map(len, content.source.page_texts))
            if text_size + added > MAX_REPORT_TEXT:
                raise ValueError(f"Total extracted text exceeds {MAX_REPORT_TEXT:,} characters. Remove unused sources or split the report.")
        except (ValueError, OSError, LookupError, csv.Error, RuntimeError, BadZipFile,
                zlib.error, fitz.mupdf.FzErrorBase) as exc:
            _discard_rejected(path, cache, digest, already_present, existing_cache)
            if isinstance(exc, OSError):
                reason = "Storage or file reader was unavailable; retry this file."
            elif isinstance(exc, zlib.error):
                reason = "Compressed file data is damaged. Export a fresh copy and upload it again."
            elif isinstance(exc, fitz.mupdf.FzErrorBase):
                reason = "PDF pages could not be decoded. Retry this file or export a fresh PDF copy."
            elif isinstance(exc, (KeyError, IndexError)):
                reason = "The file is missing required document data. Export a fresh copy and upload it again."
            elif isinstance(exc, LookupError):
                reason = "The file uses an unknown text encoding; provide a UTF-8 copy."
            elif isinstance(exc, BadZipFile):
                reason = "The Word or workbook package is damaged. Export a fresh copy and upload it again."
            elif isinstance(exc, RecursionError):
                reason = "The file structure is too deeply nested. Export a simpler copy and upload it again."
            elif isinstance(exc, fitz.FileDataError):
                reason = "The PDF is damaged or is not a valid PDF. Export a fresh copy and upload it again."
            else:
                reason = str(exc)[:300]
            messages.append(f"Not read: {label}. {reason}")
            continue
        except BaseException:
            # An unexpected fault is still raised (never hidden as a file
            # failure), but the upload it rejected must not stay on disk.
            _discard_rejected(path, cache, digest, already_present, existing_cache)
            raise
        if parent_digest:
            content = replace(content, source=replace(
                content.source, attachment_parent_sha256=parent_digest,
                attachment_index=attachment_index))
        sources[digest] = content
        sizes += size
        counted_sizes[digest] = size
        text_size += added
        queue.extend((name, data, depth + 1, digest, index)
                     for index, (name, data) in enumerate(attachments, 1))
    return tuple(sources.values()), tuple(messages)


@traced("optional_visual_read")
def page_image(profile: ReportProfile, content: SourceContent, number: int, *, preview: bool = False, _pdf_image=None):
    source = content.source
    if number < 1 or number > len(source.page_texts):
        raise ValueError("Source page does not exist.")
    directory = _path(profile, source.sha256, source.suffix).parent / "prepared" / source.sha256
    # Older DOCX previews were incorrectly prepared at print resolution.
    # Keep those assets intact and give the corrected derivative its own key.
    purpose = "preview-docx-v2" if preview and source.suffix == ".docx" else "preview" if preview else "print"
    cache = directory / f"{number}-{purpose}.json"
    if cache.exists():
        # Disposable page rasters can be lost or damaged independently of the
        # retained source. A bad *cache* is never authority to reject the source:
        # rederive it below, after the original's normal integrity checks.
        # Bound the actual read too; stat-before-read cannot cap a replacement.
        try:
            saved = library._read(cache)
            if not isinstance(saved, dict):
                raise ValueError("Invalid prepared image metadata.")
            ref, extension = saved.get("asset"), saved.get("extension")
            if (not isinstance(ref, str)
                    or not re.fullmatch(r"[0-9a-f]{64}\.(?:jpg|png)", ref)
                    or extension not in ("jpg", "png") or not ref.endswith("." + extension)
                    or any(type(saved.get(field)) is not int or saved[field] <= 0
                           for field in ("width", "height"))):
                raise ValueError("Invalid prepared image metadata.")
            with (directory / ref).open("rb") as stream:
                data = stream.read(MAX_CACHED_PAGE_IMAGE_BYTES + 1)
            if (len(data) > MAX_CACHED_PAGE_IMAGE_BYTES
                    or library.asset_reference(data, extension) != ref):
                raise ValueError("A prepared source image failed its integrity check.")
            return ReportImage(data, extension, saved["width"], saved["height"])
        except (OSError, ValueError, KeyError, TypeError):
            # Do not delete a bad cache or touch a report. The authenticated
            # source is decoded and an atomic fresh derivative is published
            # only after it has been prepared successfully.
            pass
    raw = source_bytes(profile, source) if source.suffix != ".docx" and _pdf_image is None else b""
    if source.suffix == ".pdf":
        if _pdf_image is not None:
            # Only the internal verified process-worker path supplies this.
            result = _pdf_image
        else:
            with fitz.open(stream=raw, filetype="pdf") as pdf:
                page = pdf[number-1]
                dpi = 96 if preview else 150
                width, height = page.rect.width * dpi / 72, page.rect.height * dpi / 72
                if width <= 0 or height <= 0 or width * height > ocr._MAX_PIXELS_PER_FRAME:
                    raise ValueError("This PDF page is too large to rasterize safely.")
                with span("raster"):
                    png = page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
            result = normalize_report_image(png, ".png", line_art=True, dpi=dpi)
    elif source.suffix in ocr.SUPPORTED_IMAGE_SUFFIXES:
        result = normalize_report_image(raw, source.suffix, dpi=96 if preview else 200,
                                        **({"frame_index": number - 1} if source.suffix == ".mpo" else {}))
    elif source.suffix == ".docx":
        item_id = dict(content.image_items).get(number)
        if not item_id:
            raise ValueError("This DOCX item has no raster image. Use its extracted text/table instead.")
        path = _path(profile, source.sha256, source.suffix)
        inspected = inspect_docx(path)
        if inspected.sha256 != source.sha256:
            raise ValueError("A source file failed its integrity check.")
        item = next(i for i in inspected.items if i.id == item_id)
        result = read_import_image(path, item, preview=preview)
    else:
        raise ValueError("This source contains text/tables rather than image pages.")
    ref = library.asset_reference(result.data, result.extension)
    library._atomic_write(directory / ref, result.data)
    library._atomic_write(cache, library._json({"schema": 1, "asset": ref, "extension": result.extension,
                                              "width": result.width, "height": result.height}))
    return result


def source_reference(source: ReportSource, number: int) -> str:
    return f"{source.id}:{number}:{source.fingerprint}"


def image_numbers(content: SourceContent) -> tuple[int, ...]:
    if content.source.suffix == ".docx":
        return tuple(n for n, _ in content.image_items)
    if content.source.suffix == ".pdf" or content.source.suffix in ocr.SUPPORTED_IMAGE_SUFFIXES:
        return tuple(range(1, len(content.source.page_texts) + 1))
    return ()



def _prepared_page_images(profile, planned):
    """Keep the canonical page order and content-addressed cache writer in parent.

    The process path is exclusive to a *large*, uncached, single-PDF range.
    Never move two-page PreviewStore paints, source identity or human review
    policy into a worker. Do not hold a cache or report-library lock in children.
    """
    from app.monthly_report_parallel_pages import MIN_PDF_BYTES, RASTER_SLOT, eligible, parallel_pages

    for _, records in groupby(planned, key=lambda item: item[0].source.id):
        items = tuple(records)
        content = items[0][0]
        source = content.source
        if source.suffix == ".pdf":
            path = _path(profile, source.sha256, source.suffix)
            prepared = path.parent / "prepared" / source.sha256
            cold = sum(not (prepared / f"{number}-print.json").is_file()
                       for _, _, number in items)
            if (path.stat().st_size >= MIN_PDF_BYTES and eligible(cold)
                    and RASTER_SLOT.acquire(blocking=False)):
                try:
                    # Authenticate the exact original before dispatch; each
                    # process revalidates it before opening its own PDF.
                    source_bytes(profile, source)
                    rasters = parallel_pages(
                        path, source.sha256, (number for _, _, number in items),
                        dpi=150, max_pixels=ocr._MAX_PIXELS_PER_FRAME,
                        max_source_bytes=file_size_limit(source.suffix))
                    with closing(rasters):
                        for (record_content, slot, number), (returned, image) in zip(
                                items, rasters, strict=True):
                            if returned != number:
                                raise ValueError("Prepared PDF page order changed.")
                            yield record_content, slot, number, page_image(
                                profile, record_content, number, _pdf_image=image)
                finally:
                    RASTER_SLOT.release()
                continue
        for record_content, slot, number in items:
            yield record_content, slot, number, page_image(profile, record_content, number)


def prepare_pages(profile: ReportProfile, contents: tuple[SourceContent, ...],
                  destinations: tuple[tuple[str, str], ...], *,
                  only_pages: frozenset[tuple[str, int]] | None = None) -> tuple[ResolvedBlock, ...]:
    """Prepare into content-addressed storage, with an aggregate limit.

    An optional subset restricts which pages are actually inserted without
    changing the canonical source fingerprint used in provenance references.
    No shared profile defaults, manifest, or snapshot is changed here.
    """
    from app.monthly_report_content_policy import page_allowed
    sources = {c.source.id: c for c in contents}
    # Legacy (source, section) routes still embed all selected pages. The
    # per-page route adds an explicit page number, so mixed original PDFs can
    # contribute *different* reviewed pages without cloning any page.
    arities = {len(entry) for entry in destinations}
    if arities not in ({2}, {3}, set()):
        raise ValueError("Choose one consistent source/page routing format.")
    if arities == {2} and len(dict(destinations)) != len(destinations):
        raise ValueError("Each source needs one page destination.")
    if arities == {3} and len({(identity, number) for identity, _, number in destinations}) != len(destinations):
        raise ValueError("Each source page may be routed only once; duplicate page destination.")
    allowed_pairs = set(only_pages) if only_pages is not None else None
    matched_pairs = set()
    planned = []
    if arities == {3}:
        for identity, slot, number in destinations:
            if identity not in sources or slot not in PAGE_DESTINATIONS:
                raise ValueError("Unknown page source or destination.")
            content = sources[identity]
            if (type(number) is not int or number not in image_numbers(content)
                    or number not in content.source.selected_pages):
                raise ValueError("Selected source page does not exist or is no longer selected.")
            if allowed_pairs is None or (identity, number) in allowed_pairs:
                matched_pairs.add((identity, number))
                planned.append((content, slot, number))
    else:
        for identity, slot in destinations:
            if identity not in sources or slot not in PAGE_DESTINATIONS:
                raise ValueError("Unknown page source or destination.")
            content = sources[identity]
            allowed = set(image_numbers(content))
            selected = tuple(
                n for n in content.source.selected_pages
                if n in allowed and (allowed_pairs is None or (identity, n) in allowed_pairs))
            matched_pairs.update((identity, n) for n in selected)
            if any(n < 1 or n > len(content.source.page_texts) for n in content.source.selected_pages):
                raise ValueError("Selected source page does not exist.")
            planned.extend((content, slot, n) for n in selected)
    if allowed_pairs is not None and matched_pairs != allowed_pairs:
        raise ValueError("The requested source pages changed. Review them again before inclusion.")
    if len(planned) > MAX_EMBED_PAGES:
        raise ValueError("Embedding limit is 150 selected image/PDF pages per report. Reduce the selection before preparing.")
    for content, slot, number in planned:
        if not page_allowed(content.source, number, profile=profile, destination=slot):
            raise ValueError(f"Check page {number} of {content.source.filename} before including it. Prices, legal-only and blank/signature-only pages cannot be included.")
    grouped, total = {}, 0
    # Explicit closing propagates aborted/stale requests into worker teardown.
    with closing(_prepared_page_images(profile, planned)) as prepared:
        for content, slot, number, normalized in prepared:
            total += len(normalized.data)
            if total > 60 * 1024 * 1024:
                raise ValueError("Prepared images exceed 60 MB. Reduce the selected pages or image dimensions.")
            ref = library.asset_reference(normalized.data, normalized.extension)
            library._atomic_write(library._profile_path(profile.contract, profile.key) / "assets" / ref, normalized.data)
            caption = dict(content.source.captions).get(number, f"{content.source.filename} · page/item {number}")
            grouped.setdefault(slot, []).append((ref, caption, source_reference(content.source, number)))
    from app.monthly_report_asset_instances import new_asset_instance, with_asset_instances
    blocks = tuple(with_asset_instances(ResolvedBlock(slot, "This month", asset_hashes=tuple(v[0] for v in values),
                               asset_captions=tuple(v[1] for v in values), references=tuple(v[2] for v in values),
                               ), tuple(new_asset_instance(v[0], (v[2],), source_caption=v[1]) for v in values))
                 for slot, values in grouped.items())
    from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
    return tuple(approve_all_assets(refresh_asset_source_context(b, tuple(c.source for c in contents))) for b in blocks)
