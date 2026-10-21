"""Exact native PDF block spans for explicitly labelled vendor paragraphs.

This is not a PDF reading-order guesser. Raw extraction remains authoritative;
missing, changed or incomplete paragraph evidence requires source review.
"""
from dataclasses import dataclass
from hashlib import sha256
import re
import fitz

_LABEL = re.compile(r'(?im)^[ \t]*(actions?|findings?|recommendations?|follow[- ]?ups?)\s*[:=]')
_FIELD = re.compile(r"^[ \t]*[A-Za-z][^:\r\n=]{0,60}\s*[:=]")
_STATUS = re.compile(r"(?im)^[ \t]*(?:(?:(?:work|service|completion|job|repair)\s+)?status|completion|outcome)\s*[:=]")
MAX_VENDOR_BLOCK_SPANS = 2000
MAX_VENDOR_FIELD_CHARS = 6000
FIELD_PATTERNS = {"actions": r"\b(completed|repaired|replaced|inspected)\b",
                  "findings": r"\b(findings?|observed)\b", "recommendations": r"\brecommend",
                  "follow_ups": r"\b(follow.up|pending|scheduled)\b"}
def typed_metadata(line):
    if not field_boundary(line):
        return False
    heading, value = re.split('[:=]', line, maxsplit=1)
    heading, value = heading.strip().casefold(), value.strip()
    date = heading in {'report date', 'service date', 'date'} and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}', value)
    counter = heading in {'header', 'footer', 'page'} and re.fullmatch(
        r'(?i)(?:page\s+)?\d{1,3}(?:\s+of\s+\d{1,3})?', value)
    identifier = heading in {'report id', 'report number'} and re.fullmatch(
        r'[A-Za-z0-9_-]{1,48}', value) and any(c.isdigit() for c in value)
    return bool(date or counter or identifier)


def unsupported_fields(text):
    """Only structurally typed metadata may be ignored; free prose is pending."""
    lines = [line for line in text.splitlines() if line.strip()]
    for number, line in enumerate(lines):
        if not field_boundary(line) or _LABEL.match(line):
            continue
        if not typed_metadata(line):
            return True
        # One next-nonblank lookup per line, never copying page suffixes.
        if number + 1 < len(lines) and not field_boundary(lines[number + 1]):
            return True
    return False


def safe_remainder(text):
    """No ignored prose: only exact conventional titles and typed metadata."""
    for line in text.splitlines():
        line = line.strip()
        if not line or typed_metadata(line):
            continue
        if re.fullmatch(r'(?i)(?:(?:monthly|vendor|service|maintenance|inspection|field|activity)\s+){1,3}report', line):
            continue
        if re.fullmatch(r'(?i)page\s+\d{1,3}(?:\s+of\s+\d{1,3})?', line):
            continue
        return False
    return True


_BOUNDARY = re.compile(r'(?i)^\s*(?:page\s+\d|[-*•‣▪]\s|\d+[.)]\s|(?:copyright|confidential|disclaimer|terms and conditions)\b)')


@dataclass(frozen=True)
class VendorPassage:
    page: int
    start: int
    end: int
    field: str
    text: str


def field_boundary(line):
    match = _FIELD.match(line)
    if not match:
        return False
    prefix = line[:match.end() - 1]
    value = line[match.end():]
    # Exempt explicit embedded time/serial tokens, not a heading whose value
    # merely happens to be two digits (Supervisor ID:42 / Finding #2:12).
    technical = re.search(
        r"(?i)(?:\b(?:at|before|after|by|until|since|from|to)\s+\d{1,2}|"
        r"\b(?:serial|tag|identifier)\s+[A-Za-z0-9_-]*\d)$", prefix)
    return not (technical and re.match(r"\d{2}\b", value))


def block_spans(page, text, number):
    """Only accept native blocks that tile the unchanged text in native order."""
    spans, cursor = [], 0
    geometry = {b['number']: b for b in page.get_text(
        'dict', flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)['blocks']
        if b.get('type') == 0}
    for block in page.get_text('blocks'):
        if len(block) < 7 or block[6] != 0:
            continue
        raw = block[4].strip()
        if not raw:
            continue
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if text[cursor:cursor + len(raw)] != raw:
            return ()  # No fuzzy search through repeated or reordered text.
        end = cursor + len(raw)
        lines = geometry.get(block[5], {}).get('lines', ())
        # PyMuPDF can put side-by-side columns into one text block. Require a
        # single left-aligned, downward horizontal line sequence; never guess
        # reading order or join columns sharing a baseline.
        safe = bool(lines)
        previous = None
        for line in lines:
            box = line['bbox']
            safe = safe and line.get('wmode') == 0 and tuple(line.get('dir', ())) == (1.0, 0.0)
            safe = safe and abs(box[0] - lines[0]['bbox'][0]) <= 2
            if previous is not None:
                safe = safe and 0 < box[1] - previous[1] <= 1.8 * max(previous[3] - previous[1], 1)
            previous = box
        if safe and _LABEL.search(raw):
            spans.append((number, cursor, end, sha256(raw.encode()).hexdigest()))
        cursor = end
    if text[cursor:].strip():
        return ()
    return tuple(spans)


def labeled_page(source, number):
    return (source.suffix == '.pdf'
            and 1 <= number <= len(source.page_texts)
            and bool(_LABEL.search(source.page_texts[number - 1])))


_UNSET = object()


def _whole_line_edges(text, start, end):
    line_end = text.find('\n', end)
    return (not text[text.rfind('\n', 0, start) + 1:start].strip(' \t\r')
            and not text[end:line_end if line_end >= 0 else len(text)].strip(' \t\r'))


def validated_block_index(source):
    """Request-local validation; no retained source cache or stale span reuse."""
    if not isinstance(source.pdf_text_blocks, (tuple, list)):
        return None
    index, last_page, last_end = {}, 0, 0
    for entry in source.pdf_text_blocks:
        if (not isinstance(entry, (tuple, list)) or len(entry) != 4
                or type(entry[0]) is not int or not 1 <= entry[0] <= len(source.page_texts)
                or not isinstance(entry[3], str)):
            return None
        page, start, end, digest = entry
        text = source.page_texts[page - 1]
        if (type(start) is not int or type(end) is not int or page < last_page
                or (page == last_page and start < last_end)
                or not 0 <= start < end <= len(text)
                or not _whole_line_edges(text, start, end)
                or sha256(text[start:end].encode()).hexdigest() != digest):
            return None
        index.setdefault(page, []).append((start, end))
        last_page, last_end = page, end
    return index


def read_vendor_document(source, *, limit_pages=None):
    """Validate once, then parse only each labeled page's own exact spans."""
    pages = [n for n in range(1, len(source.page_texts) + 1) if labeled_page(source, n)]
    index = validated_block_index(source) if pages and source.classification == 'Vendor service' else None
    result = {n: vendor_passages(source, n, index=index) for n in pages}
    sizes, field_pages = {}, {}
    if not pages:
        return result  # Preserve wholly unlabeled legacy sources.
    for number, text in enumerate(source.page_texts, 1):
        for field, term in FIELD_PATTERNS.items():
            values = ([p.text for p in result[number][0] if p.field == field]
                      if number in result else
                      [line.strip() for line in text.splitlines() if re.search(term, line, re.I)])
            if values:
                sizes[field] = sizes.get(field, -1) + sum(len(v) + 1 for v in values)
                field_pages.setdefault(field, set()).add(number)
    oversized = {field for field, size in sizes.items() if size > MAX_VENDOR_FIELD_CHARS}
    if oversized:
        affected = set().union(*(field_pages[field] for field in oversized))
        if limit_pages is not None:
            limit_pages.update(affected)
        result = {n: (tuple(p for p in passages if p.field not in oversized),
                      pending or n in affected)
                  for n, (passages, pending) in result.items()}
        # An unlabeled page contributing to an over-limit field cannot escape
        # back through physical-line Activity/evidence. Keep that page pending.
        for number in affected - result.keys():
            result[number] = ((), True)
    return result


def vendor_passages(source, number, *, index=_UNSET):
    """Return (confirmed spans, needs_review); never cross a native block/page.

    A closed native paragraph is required. Unfinished blocks and unlabeled text
    are not silently appended. These conservative limits do not certify arbitrary
    PDFs or infer the meaning of unknown adjacent paragraphs.
    """
    if not labeled_page(source, number):
        return (), False
    if source.classification != 'Vendor service':
        return (), True
    # Status fields can qualify an apparently completed action. Their linkage
    # is not inferred: keep this page pending rather than silently drop them.
    if _STATUS.search(source.page_texts[number - 1]) or unsupported_fields(source.page_texts[number - 1]):
        return (), True
    if index is _UNSET:
        index = validated_block_index(source)
    blocks = index.get(number, ()) if index is not None else ()
    if not blocks:
        return (), True
    text = source.page_texts[number - 1]
    passages, pending, covered = [], False, set()
    for start, end in blocks:
        raw = text[start:end]
        lines = raw.splitlines(keepends=True)
        offset, opening, field = start, None, ''
        ambiguous = False
        previous_line = ''
        def finish(stop):
            nonlocal pending, opening
            if opening is None:
                return
            exact = text[opening:stop].strip()
            # End punctuation is a necessary conservative boundary, not evidence
            # on its own: an exact native block span is required above as well.
            if ambiguous or not re.search(r'[.!?][\"\')\]]*$', exact):
                pending = True
            else:
                passages.append(VendorPassage(number, opening,
                    opening + len(text[opening:stop].rstrip()), field,
                    ' '.join(exact.split())))
            opening = None
        for line in lines:
            label = _LABEL.match(line)
            boundary = not line.strip() or field_boundary(line) or _BOUNDARY.match(line)
            if (opening is not None and not boundary
                    and re.search(r'[.!?][\"\')\]]*$', previous_line.rstrip())):
                ambiguous = True
            # Multiple field labels on one physical line are not a proven block
            # boundary. Preserve the original for review rather than blend fields.
            if opening is not None and re.search(
                    r'(?i)\S.*\s(?:actions?|findings?|recommendations?|follow[- ]?ups?)\s*[:=]', line):
                ambiguous = True
            if boundary:
                finish(offset)
            if label:
                opening = offset
                ambiguous = bool(re.search(
                    r"(?i)\S.*\s(?:actions?|findings?|recommendations?|follow[- ]?ups?)\s*[:=]", line))
                key = re.sub(r'[- ]', '', label[1].lower())
                field = ('follow_ups' if key.startswith('follow') else
                         'recommendations' if key.startswith('recommend') else
                         'findings' if key.startswith('finding') else 'actions')
                covered.add(offset + label.start())
            previous_line = line
            offset += len(line)
        finish(end)
    if len(covered) != len(tuple(_LABEL.finditer(text))):
        pending = True
    # Every unconsumed character remains accountable. A separate native block
    # can qualify the action even when it has no recognized field heading.
    cursor = 0
    for passage in passages:
        if not safe_remainder(text[cursor:passage.start]):
            return (), True
        cursor = passage.end
    if pending or not safe_remainder(text[cursor:]):
        return (), True
    return tuple(passages), False


_NOTICE_TEXT = {
    'boundary': ('Page {page}: some passage text was not auto-imported. Review the full source page '
                 'before including it, or leave it out. Add verified wording manually.'),
    'limit': ('Page {page}: passage text exceeds the suggestion limit and was not auto-imported. '
              'Review the full source page before including it, or leave it out. Add verified wording manually.'),
}


def passage_notice(page, *, reason='boundary'):
    return _NOTICE_TEXT[reason].format(page=page)


def passage_notice_page(notice, page_count):
    """Only this exact bounded notice family is eligible for existing review."""
    match = re.match(r'^Page ([1-9][0-9]{0,2}):', notice)
    if not match:
        return None
    page = int(match[1])
    if not 1 <= page <= page_count:
        return None
    return page if any(notice == value.format(page=page) for value in _NOTICE_TEXT.values()) else None
