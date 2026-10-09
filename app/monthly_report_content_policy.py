"""Client-facing content gates. Original evidence is never edited or deleted."""

import hashlib
import re
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.monthly_report_model import BlockSpec, ResolvedBlock


_MONEY = re.compile(r"(?:[$€£]\s*\d|\b(?:USD|CAD|EUR|GBP)\s*\d|\d[\d,.]*\s*(?:USD|CAD|EUR|GBP|dollars?)\b)", re.I)
_PRICE_LABEL = re.compile(r"\b(?:unit\s+price|pricing|prices?|costs?|(?:hourly|billing|labor|labour)\s+rates?|subtotal|total\s+(?:amount|charges?|due)|amount\s+(?:due|quoted)|labor\s+charges?|material\s+charges?|sales\s+tax|(?:quoted|quotation|invoice)\s+amount)\b", re.I)
_LEGAL_TERMS = ("terms and conditions", "limitation of liability", "indemnif", "governing law", "entire agreement", "waiver", "arbitration", "force majeure", "consequential damages", "jurisdiction", "severability", "warranty disclaimer")


def contains_price(text):
    if _MONEY.search(text):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for n, line in enumerate(lines):
        if _PRICE_LABEL.search(line):
            # A date elsewhere in an operational sentence does not turn the
            # word "cost" into a price. Require a value after the price label,
            # or a bare amount immediately before it.
            if any(re.search(r"\d", line[match.end():])
                   or re.search(r"\d[\d,.]*\s*[:–-]?\s*$", line[:match.start()])
                   for match in _PRICE_LABEL.finditer(line)):
                return True
            # PDF text often puts a monetary table heading and its bare amount
            # on separate lines, without a repeated currency symbol.
            if n + 1 < len(lines) and re.fullmatch(r"[\d,.()\s+-]+", lines[n+1]) and re.search(r"\d", lines[n+1]):
                return True
    return False


def _price_heading(title):
    return bool(re.search(r"\b(?:price|pricing|cost|subtotal|tax|total charge|(?:quoted|invoice|charge) amount|amount due|(?:hourly|billing|labor|labour) rate)\b", title, re.I)) or title.strip().casefold() in ("amount", "rate")


def _mixed_price_heading(title):
    """A flattened Word heading can name several different columns at once.

    Removing that physical column would discard technical content rather than
    reliably remove prices. Preserve it until its headings have been reviewed.
    """
    return _price_heading(title) and bool(re.search(
        r"\b(?:description|recommendation|deficienc(?:y|ies)|scope|condition|useful\s+life|replacement\s+timing)\b",
        title, re.I,
    ))


def price_column(title, kind=""):
    # Even a supplied currency type is not enough to discard a mixed heading.
    return not _mixed_price_heading(title) and (kind == "currency" or _price_heading(title))


def logical_table_columns(columns):
    """Recover the one unambiguous four-column ENFRA capital header variant.

    Other mixed headers stay ambiguous. This recognizes the complete ordered
    canonical label sequence and the exact four-cell grid, never data values.
    """
    values = tuple(columns)
    if (len(values) == 4
            and re.sub(r"[^a-z]", "", values[0].casefold()) ==
            "equipmentdescriptionendofusefullifecostsummaryofdeficiency"
            and all(not title.strip() or re.fullmatch(r"(?:Column|Detail)\s+[234]", title.strip(), re.I)
                    for title in values[1:])):
        return ("Equipment Description", "End of Useful Life", "Cost", "Summary of deficiency")
    return values


def _table_headings(columns, rows):
    """Inspect adjacent header lines before the first numeric data row."""
    columns = logical_table_columns(columns)
    header_rows = [columns]
    for row in rows[:3]:
        if any(re.search(r"\d", str(cell)) for cell in row):
            break
        header_rows.append(row)
    return tuple(" ".join(row[i] for row in header_rows if i < len(row)) for i in range(len(columns)))


def ambiguous_price_columns(columns, rows=()):
    """Columns needing header correction before any price filtering is safe."""
    return tuple(i for i, title in enumerate(_table_headings(columns, rows)) if _mixed_price_heading(title))


def receivable_amount_columns(columns):
    """Aged receivable buckets are monetary only in an explicit invoice context."""
    headings = tuple(" ".join(str(c).casefold().split()) for c in logical_table_columns(columns))
    invoice = any(re.search(r"\binvoice\b|accounts? receivable", c) for c in headings)
    money = any(re.search(r"\bamount(?: due)?\b|\bbalance\b", c) for c in headings)
    if not (invoice and money):
        return ()
    return tuple(i for i, title in enumerate(headings)
                 if title in {"current", "total", "grand total", "balance", "balance due", "amount due", "invoice amount"}
                 or re.fullmatch(r"[\dG]+\s*[-–]\s*(?:[\dG]+|over)(?:\s*days?)?", title, re.I))


def table_price_columns(columns, rows):
    excluded = {i for i, title in enumerate(_table_headings(columns, rows)) if price_column(title)}
    excluded.update(receivable_amount_columns(columns))
    return tuple(sorted(excluded))


def table_has_pricing(columns, rows, *, work_orders=False):
    if ambiguous_price_columns(columns, rows) and any(any(str(cell).strip() for cell in row) for row in rows):
        return True
    if any(contains_price("\t".join(row)) for row in rows):
        return True
    if any(any(i < len(row) and re.search(r"\d", row[i]) for row in rows) for i in table_price_columns(columns, rows)):
        return True
    # An unlabeled Total/500 row is ambiguous and must be clarified before export.
    # Explicit engineering/count headers distinguish legitimate technical totals.
    technical = work_orders or bool(re.search(r"\b(?:counts?|hours?|temperature|pressure|flow|gpm|readings?|work.orders?|PM|CM)\b", " ".join(columns), re.I))
    return not technical and any(any(re.fullmatch(r"(?:grand\s+)?total\s*:?[ ]*", cell.strip(), re.I) for cell in row)
                                 and any(re.fullmatch(r"[\d,.()\s+-]+", cell.strip()) and re.search(r"\d", cell) for cell in row) for row in rows)


def price_free_table(spec: "BlockSpec", block: "ResolvedBlock") -> tuple["BlockSpec", "ResolvedBlock", tuple[str, ...]]:
    """Return an editable client copy and the removed pricing-column labels.

    Saved snapshots and originals are immutable inputs. Only identified pricing
    columns are removed; money inside narrative/detail cells remains visible
    for correction and is still rejected by the normal preflight gate. Extra
    cells with no supplied header get neutral headers instead of being lost.
    Callers must explain the removed columns before saving this revised draft.
    """
    from app.monthly_report_model import ColumnSpec

    removed = []

    def filter_rows(columns, rows, currency=()):
        width = max((len(row) for row in rows), default=len(columns))
        headings = tuple(columns) + tuple(
            f"Detail {n + 1}" for n in range(len(columns), width)
        )
        headings = logical_table_columns(headings)
        excluded = (set(table_price_columns(headings, rows)) | set(currency)) - set(ambiguous_price_columns(headings, rows))
        removed.extend(headings[n] for n in sorted(excluded))
        indexes = tuple(n for n in range(len(headings)) if n not in excluded)
        filtered = tuple(tuple(row[n] if n < len(row) else "" for n in indexes) for row in rows)
        return headings, indexes, filtered if indexes else ()

    updated_spec = spec
    updated_rows = block.rows
    if spec.type in ("table", "work_order_grid"):
        headings, indexes, updated_rows = filter_rows(
            tuple(c.title for c in spec.columns), block.rows,
            tuple(n for n, c in enumerate(spec.columns) if price_column(c.title, c.type)),
        )
        keys = {c.key for c in spec.columns}
        columns = [replace(column, title=headings[n]) for n, column in enumerate(spec.columns)]
        for n in range(len(columns), len(headings)):
            key = f"unmapped_detail_{n + 1}"
            while key in keys:
                key += "_extra"
            keys.add(key)
            columns.append(ColumnSpec(key, headings[n]))
        updated_spec = replace(spec, columns=tuple(columns[n] for n in indexes))
    tables = []
    for table in block.extra_tables:
        headings, indexes, rows = filter_rows(table.columns, table.rows)
        if indexes:
            tables.append(replace(table, columns=tuple(headings[n] for n in indexes), rows=rows))
        elif not headings:
            tables.append(table)
    updated_block = replace(block, rows=updated_rows, extra_tables=tuple(tables))
    if updated_spec != spec or updated_block != block:
        from app.monthly_report_asset_review import preserve_asset_reviews
        updated_block = replace(updated_block, reviewed_fingerprint="", client_reviewed_fingerprint="")
        updated_block = preserve_asset_reviews(block, updated_block)
    return updated_spec, updated_block, tuple(dict.fromkeys(removed))


def page_status(text, *, unreadable=False):
    """Proposals only; a readable page still needs a visual client-output check."""
    if contains_price(text):
        return "pricing", "Contains pricing — cannot be included in the client report"
    normalized = " ".join(text.casefold().split())
    if sum(term in normalized for term in _LEGAL_TERMS) >= 2:
        return "legal", "Contract/legal terms — leave out of the monthly report"
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return ("review", "Image or unreadable page — inspect before including") if unreadable else ("blank", "No report content found")
    if len(words) < 35 and re.search(r"\b(?:signature|signed by|authorized by|accepted by|approved by)\b", normalized) and not re.search(r"\b(?:work|repair|inspected|finding|result|equipment|service performed)\b", normalized):
        return "signature", "Signature-only page — leave out of the monthly report"
    return ("review", "Image content needs a visual check") if unreadable else ("technical", "Check relevance and confirm that no pricing is visible")


def page_fingerprint(source, page):
    caption = dict(source.captions).get(page, "")
    text = source.page_texts[page - 1]
    return hashlib.sha256(f"client-pages-v1\0{source.sha256}\0{page}\0{text}\0{caption}".encode()).hexdigest()


def page_allowed(source, page):
    status, _ = page_status(source.page_texts[page - 1], unreadable=page in source.needs_vision)
    return status not in ("pricing", "legal", "blank", "signature") and not contains_price(dict(source.captions).get(page, "")) and dict(source.client_page_reviews).get(page) == page_fingerprint(source, page)


def suggested_pages(source):
    return tuple(n for n, text in enumerate(source.page_texts, 1)
                 if page_status(text, unreadable=n in source.needs_vision)[0] == "technical")
