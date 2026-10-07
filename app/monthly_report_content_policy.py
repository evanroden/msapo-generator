"""Client-facing content gates. Original evidence is never edited or deleted."""

import hashlib
import re


_MONEY = re.compile(r"(?:[$€£]\s*\d|\b(?:USD|CAD|EUR|GBP)\s*\d|\d[\d,.]*\s*(?:USD|CAD|EUR|GBP|dollars?)\b)", re.I)
_PRICE_LABEL = re.compile(r"\b(?:unit\s+price|pricing|prices?|costs?|(?:hourly|billing|labor|labour)\s+rates?|subtotal|total\s+(?:amount|charges?|due)|amount\s+(?:due|quoted)|labor\s+charges?|material\s+charges?|sales\s+tax|(?:quoted|quotation|invoice)\s+amount)\b", re.I)
_LEGAL_TERMS = ("terms and conditions", "limitation of liability", "indemnif", "governing law", "entire agreement", "waiver", "arbitration", "force majeure", "consequential damages", "jurisdiction", "severability", "warranty disclaimer")


def contains_price(text):
    if _MONEY.search(text):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for n, line in enumerate(lines):
        if _PRICE_LABEL.search(line):
            if re.search(r"\d", line):
                return True
            # PDF text often puts a monetary table heading and its bare amount
            # on separate lines, without a repeated currency symbol.
            if n + 1 < len(lines) and re.fullmatch(r"[\d,.()\s+-]+", lines[n+1]) and re.search(r"\d", lines[n+1]):
                return True
    return False


def price_column(title, kind=""):
    return kind == "currency" or bool(re.search(r"\b(?:price|pricing|cost|subtotal|tax|total charge|(?:quoted|invoice|charge) amount|(?:hourly|billing|labor|labour) rate)\b", title, re.I)) or title.strip().casefold() in ("amount", "rate")


def table_price_columns(columns, rows):
    """Inspect adjacent header lines before the first numeric data row."""
    header_rows = [columns]
    for row in rows[:3]:
        if any(re.search(r"\d", str(cell)) for cell in row):
            break
        header_rows.append(row)
    return tuple(i for i in range(len(columns)) if price_column(" ".join(row[i] for row in header_rows if i < len(row))))


def table_has_pricing(columns, rows, *, work_orders=False):
    if any(contains_price("\t".join(row)) for row in rows):
        return True
    if any(any(i < len(row) and re.search(r"\d", row[i]) for row in rows) for i in table_price_columns(columns, rows)):
        return True
    # An unlabeled Total/500 row is ambiguous and must be clarified before export.
    # Explicit engineering/count headers distinguish legitimate technical totals.
    technical = work_orders or bool(re.search(r"\b(?:counts?|hours?|temperature|pressure|flow|gpm|readings?|work.orders?|PM|CM)\b", " ".join(columns), re.I))
    return not technical and any(any(re.fullmatch(r"(?:grand\s+)?total\s*:?[ ]*", cell.strip(), re.I) for cell in row)
                                 and any(re.fullmatch(r"[\d,.()\s+-]+", cell.strip()) and re.search(r"\d", cell) for cell in row) for row in rows)


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
