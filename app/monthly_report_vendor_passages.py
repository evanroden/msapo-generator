"""Exact native PDF block spans for explicitly labelled vendor paragraphs.

This is not a PDF reading-order guesser. Raw extraction remains authoritative;
missing, changed or incomplete paragraph evidence requires source review.
"""
from dataclasses import dataclass
from hashlib import sha256
import re
import fitz

_LABEL = re.compile(r'(?im)^[ \t]*(actions?|findings?|recommendations?|follow[- ]?ups?)\s*[:=]')
_FIELD = re.compile(r'^[ \t]*[A-Za-z][A-Za-z /_-]{0,45}\s*[:=]')
_BOUNDARY = re.compile(r'(?i)^\s*(?:page\s+\d|[-*•‣▪]\s|\d+[.)]\s|(?:copyright|confidential|disclaimer|terms and conditions)\b)')


@dataclass(frozen=True)
class VendorPassage:
    page: int
    start: int
    end: int
    field: str
    text: str


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
        if safe:
            spans.append((number, cursor, end, sha256(raw.encode()).hexdigest()))
        cursor = end
    if text[cursor:].strip():
        return ()
    return tuple(spans)


def labeled_page(source, number):
    return (source.suffix == '.pdf' and source.classification in ('Vendor service', 'Reference only')
            and 1 <= number <= len(source.page_texts)
            and bool(_LABEL.search(source.page_texts[number - 1])))


def vendor_passages(source, number):
    """Return (confirmed spans, needs_review); never cross a native block/page.

    A closed native paragraph is required. Unfinished blocks and unlabeled text
    are not silently appended. These conservative limits do not certify arbitrary
    PDFs or infer the meaning of unknown adjacent paragraphs.
    """
    if not labeled_page(source, number):
        return (), False
    # Ambiguous/no heuristic classification must never fall back to certifying
    # a physical first line. Only confirmed vendor sources may auto-extract.
    if source.classification != 'Vendor service':
        return (), True
    text = source.page_texts[number - 1]
    blocks, previous = [], 0
    if not isinstance(source.pdf_text_blocks, (tuple, list)):
        return (), True
    last_page, last_end = 0, 0
    for entry in source.pdf_text_blocks:
        if (not isinstance(entry, (tuple, list)) or len(entry) != 4
                or type(entry[0]) is not int or not 1 <= entry[0] <= len(source.page_texts)
                or not isinstance(entry[3], str)):
            return (), True
        page, start, end, digest = entry
        if (type(start) is not int or type(end) is not int or page < last_page
                or (page == last_page and start < last_end)):
            return (), True
        last_page, last_end = page, end
        if not 0 <= start < end <= len(source.page_texts[page - 1]):
            return (), True
        page, start, end, digest = entry
        if page != number:
            continue
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(text) or start < previous
                or (start and text[start - 1] != '\n')
                or (end != len(text) and text[end] != '\n')
                or sha256(text[start:end].encode()).hexdigest() != digest):
            return (), True
        blocks.append((start, end)); previous = end
    if not blocks:
        return (), True
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
            boundary = not line.strip() or _FIELD.match(line) or _BOUNDARY.match(line)
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
    return tuple(passages), pending
