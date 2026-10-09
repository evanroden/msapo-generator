"""Populate an inspected Word layout without rebuilding its page design.

The source is a geometry template, never a source of current report facts. Native
text boxes, section properties and formatting survive, but body payloads are
cleared before current values are written. Unsupported bindings fail explicitly.
"""
from __future__ import annotations

import hashlib
import re
import tempfile
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_import import (
    _heading,
    _is_native_divider_background,
    _text,
    inspect_docx,
)


class NativeLayoutError(ValueError):
    """The source layout cannot represent the current content safely."""


_STATIC = {
    "work order status", "pm status", "activity summary", "improvement highlights and pics",
    "rate trend", "thermal services requirements and capacity", "client services calls",
    "equipment performance issues", "issues identified", "training provided",
    "rejected quotes", "pending quotes", "contract asset end of useful life schedule",
}
_DEFAULT_TEXT = {"organization": "contact_matrix", "activity": "activity_summary",
                 "scorecards": "utility_analysis", "mbcx": "mbcx_report",
                 "maintenance": "service_calls", "subcontractors": "subcontractor_matrix",
                 "water": "water_reports", "issues": "equipment_issues",
                 "capital": "capital_renewal", "proposals": "proposals",
                 "training": "training_summary", "rfi": "rfi_matrix"}
_MONTH = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d\d\b", re.IGNORECASE)


def _set_text(element, value):
    """Change run payloads while retaining paragraph/run/text-box properties."""
    if _text(element) == value:
        return
    texts = list(element.iter(qn("w:t")))
    if not texts:
        paragraph = element if element.tag == qn("w:p") else next(element.iter(qn("w:p")), None)
        if paragraph is None:
            paragraph = OxmlElement("w:p")
            element.append(paragraph)
        run = OxmlElement("w:r")
        paragraph.append(run)
        node = OxmlElement("w:t")
        run.append(node)
        texts = [node]
    groups = {}
    for node in texts:
        branch = next((ancestor for ancestor in node.iterancestors()
                       if ancestor.tag in ("{http://schemas.openxmlformats.org/markup-compatibility/2006}Choice",
                                           "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback")), None)
        groups.setdefault(branch, []).append(node)
    for group in groups.values():
        group[0].text = value
        group[0].set(qn("xml:space"), "preserve")
        for node in group[1:]:
            node.text = ""


def _clear_images(element, *, preserve_decoration=False):
    # Remove the drawing itself, not its paragraph or section break.
    for node in list(element.iter()):
        if node.tag in (qn("w:drawing"), qn("w:pict")):
            # Pure native rectangles and rules are decoration, not payloads.
            presets = list(node.iter(qn("a:prstGeom")))
            colors = {n.get("val", "").lower() for n in node.iter(qn("a:srgbClr"))}
            shapes = list(node.iter("{urn:schemas-microsoft-com:vml}shape"))
            custom = list(node.iter(qn("a:custGeom")))
            basic = bool(presets) and all(p.get("prst") in {"rect", "line", "parallelogram"} for p in presets)
            basic |= bool(custom) and colors <= {"547e7e", "557f7f", "d5ee4a", "d6ef4b"} and bool(colors) and all(
                len(list(g.iter(qn("a:pt")))) <= 6 and not list(g.iter(qn("a:cubicBezTo")))
                and not list(g.iter(qn("a:quadBezTo"))) and not list(g.iter(qn("a:arcTo"))) for g in custom)
            basic |= bool(shapes) and all(s.get("fillcolor", "").lower() in {"#547e7e", "#557f7f", "#d5ee4a", "#d6ef4b"}
                and re.fullmatch(r"[0-9,mlrxe -]{1,150}", s.get("path", "")) for s in shapes)
            if (preserve_decoration and basic
                    and not any(n.tag in (qn("w:t"), qn("a:t"), qn("a:blip"))
                                or any(k in n.attrib for k in (qn("r:embed"), qn("r:link"), qn("r:id")))
                                for n in node.iter())):
                continue
            # Text-box shapes are layout, not image payloads.
            if any(True for _ in node.iter(qn("w:txbxContent"))):
                for image in list(node.iter()):
                    image.attrib.pop(qn("r:embed"), None)
                    image.attrib.pop(qn("r:link"), None)
                    if image.tag in (qn("a:blip"), "{urn:schemas-microsoft-com:vml}imagedata"):
                        image.getparent().remove(image)
            elif node.getparent() is not None:
                node.getparent().remove(node)


def _replace_image(document, element, data):
    rid, _ = document.part.get_or_add_image(BytesIO(data))
    images = [n for n in element.iter() if n.tag in (qn("a:blip"), "{urn:schemas-microsoft-com:vml}imagedata")]
    if not images:
        raise NativeLayoutError("This section has no native picture frame for its current images.")
    first = images[0]
    old_rid = first.get(qn("r:embed")) or first.get(qn("r:id"))
    for node in images:
        attr = qn("r:embed") if node.tag == qn("a:blip") else qn("r:id")
        if node.get(attr) == old_rid:
            node.set(attr, rid)
            node.attrib.pop(qn("r:link"), None)
        else:
            node.getparent().remove(node)
    # Office image effects may reference the visible image in a14:imgLayer while
    # the standard blip contains a placeholder. Those payloads must update too.
    for node in element.iter():
        if node.get(qn("r:embed")):
            node.set(qn("r:embed"), rid)
        node.attrib.pop(qn("r:link"), None)


def _table(element, columns, rows):
    native_rows = element.findall(qn("w:tr"))
    if not native_rows:
        raise NativeLayoutError("The source table has no row geometry.")
    header = max(native_rows[:2], key=lambda row: len(row.findall(qn("w:tc"))))
    prototype = native_rows[-1] if len(native_rows) > 1 else header
    width = len(columns) or max((len(row) for row in rows), default=0)
    if not width or width > 100 or any(len(row) > width for row in rows):
        raise NativeLayoutError("Current table columns do not match its row values.")
    if not columns:
        columns = tuple(_text(cell) for cell in header.findall(qn("w:tc")))
        columns = (columns + ("",) * width)[:width]
    resized = width != len(header.findall(qn("w:tc")))
    grid = element.find(qn("w:tblGrid"))
    total = sum(int(col.get(qn("w:w"), "0")) for col in grid) if grid is not None else 0
    total = total or 9000
    cell_width = max(1, total // width)
    if grid is not None and resized:
        for col in list(grid):
            grid.remove(col)
        for index in range(width):
            col = OxmlElement("w:gridCol"); col.set(qn("w:w"), str(cell_width))
            grid.append(col)
    for row in native_rows:
        element.remove(row)
    for index, values in enumerate((columns, *rows)):
        row = deepcopy(header if index == 0 else prototype)
        cells = row.findall(qn("w:tc"))
        for cell in cells:
            row.remove(cell)
        for column, value in enumerate(tuple(values) + ("",) * (width - len(values))):
            cell = deepcopy(cells[min(column, len(cells) - 1)])
            props = cell.find(qn("w:tcPr"))
            if props is not None:
                for merged in list(props):
                    if merged.tag in (qn("w:gridSpan"), qn("w:vMerge"), qn("w:hMerge"), qn("w:noWrap")):
                        props.remove(merged)
                size = props.find(qn("w:tcW"))
                if size is not None and (resized or len(cells) != width):
                    size.set(qn("w:w"), str(cell_width)); size.set(qn("w:type"), "dxa")
            _clear_images(cell)
            _set_text(cell, str(value))
            row.append(cell)
        # Source fixed row heights cannot clip the user's longer current text.
        for height in list(row.iter(qn("w:trHeight"))):
            height.set(qn("w:hRule"), "atLeast")
        element.append(row)


def _cover(element, draft):
    paragraphs = list(element.iter(qn("w:p")))
    for paragraph in paragraphs:
        # Nested paragraphs are handled separately; never flatten the outer shape.
        if paragraph.find('.//' + qn('w:txbxContent')) is not None:
            continue
        text = _text(paragraph)
        if not text:
            continue
        if re.search(r"prepared\s+by", text, re.IGNORECASE):
            _set_text(paragraph, "Prepared by: " + draft.prepared_by)
        elif _MONTH.search(text):
            _set_text(paragraph, _MONTH.sub(draft.period.label, text))
        elif (text.strip().upper() not in {"ENFRA", "=", "INSERT IMAGE HERE"}
              and "operations and maintenance" not in text.casefold()
              and "monthly review" not in text.casefold()
              and "confidential" not in text.casefold()
              and "create." not in text.casefold()
              and "section" not in text.casefold()
              and "table of contents" not in text.casefold()):
            _set_text(paragraph, draft.profile.title)
            if len(draft.profile.title) > 22:
                for run in paragraph.findall(qn("w:r")):
                    props = run.find(qn("w:rPr"))
                    if props is not None:
                        for size in props.findall(qn("w:sz")):
                            original_size = int(size.get(qn("w:val"), "48"))
                            size.set(qn("w:val"), str(max(22, int(original_size * min(1, 22 / len(draft.profile.title))))))
        elif "INSERT IMAGE" in text.upper():
            _set_text(paragraph, "")


@lru_cache(maxsize=128)
def _source_image_digest(source_path, source_digest, item, line_art):
    # The verified immutable source hash is part of this bounded cache key.
    from app.monthly_report_import import read_import_image
    normalized = read_import_image(Path(source_path), item, line_art=line_art)
    return hashlib.sha256(normalized.data).hexdigest() + "." + normalized.extension


def _unchanged_blocks(draft, inspection, source_path, *, section_key=None):
    """Prove source facts were explicitly supplied unchanged in current inputs."""
    by_id = {item.id: item for item in inspection.items}
    prefix = f"docx:{inspection.sha256}:"
    specs = {spec.key: spec for section in draft.sections for spec in section.blocks}
    destinations = {spec.key: section.key for section in draft.sections for spec in section.blocks}
    candidates, owners = {}, {}
    for block in draft.blocks:
        if (block.source == "Omit" or block.org_nodes or block.key not in destinations
                or (section_key is not None and destinations[block.key] != section_key)):
            continue
        identities = tuple(dict.fromkeys(ref[len(prefix):] for ref in block.references
                                        if ref.startswith(prefix) and ref[len(prefix):] in by_id))
        selected = [by_id[identity] for identity in identities]
        if not selected or any(item.kind == "unsupported" for item in selected):
            continue
        if block.key in destinations and any(item.part == "word/document.xml" and item.section
                                             and item.section != destinations[block.key] for item in selected):
            continue
        text = "\n\n".join(item.text.strip() for item in selected if item.kind == "text")
        if block.text.strip() != text.strip():
            continue
        tables = [item for item in selected if item.kind == "table"]
        actual_tables = []
        if block.rows:
            spec = specs.get(block.key)
            actual_tables.append((tuple(column.title for column in spec.columns) if spec else (), block.rows))
        actual_tables.extend((table.columns, table.rows) for table in block.extra_tables)
        expected_tables = []
        from app.monthly_report_sections import table_without_prices
        for item in tables:
            table, removed = table_without_prices(item)
            if removed or table is None:
                expected_tables = None
                break
            # Import supplies display names for blank/duplicate headers. Those
            # labels do not require changing the source's actual table geometry.
            expected_tables.append((table.columns, table.rows))
        original_tables = [(item.rows[0], item.rows[1:]) for item in tables]
        if expected_tables is None or actual_tables not in (expected_tables, original_tables):
            continue
        expected_images = []
        for item in selected:
            if item.kind != "image":
                continue
            reference = _source_image_digest(str(source_path), inspection.sha256, item,
                                             block.key not in ("cover_photo", "improvements"))
            if reference not in expected_images:
                expected_images.append(reference)
        if tuple(expected_images) != block.asset_hashes:
            continue
        expected_captions = tuple(item.text for item in selected if item.kind == "image")
        current_captions = tuple(block.asset_captions) + ("",) * max(0, len(expected_captions) - len(block.asset_captions))
        if current_captions != expected_captions:
            continue
        candidates[block.key] = set(identities)
        for identity in identities:
            owners[identity] = block.key
    by_position = defaultdict(list)
    for item in inspection.items:
        if item.part == "word/document.xml":
            by_position[item.position].append(item)
    # A native paragraph can contain several independently mapped payloads. Keep
    # it only when all are present, never because just one picture matched.
    changed = True
    while changed:
        changed = False
        supported = set().union(*candidates.values()) if candidates else set()
        for key, identities in list(candidates.items()):
            valid = True
            for identity in identities:
                item = by_id[identity]
                if item.part != "word/document.xml":
                    continue
                for neighbor in by_position[item.position]:
                    if neighbor.kind in ("text", "table", "image") and neighbor.id not in supported:
                        valid = False
            if not valid:
                del candidates[key]
                changed = True
    return candidates


def build_native_docx(draft, source_path, *, asset_loader=None, section_key=None, master=False) -> bytes:
    """Render current values into source geometry, or raise a visible mapping error.

    ``section_key`` selects the actual logical section's contiguous native range;
    ``cover`` selects its preface. Word's section count is not used as a page map.
    """
    from app.monthly_report_native_package import passive_docx

    source_path = Path(source_path)
    inspection = inspect_docx(source_path)
    unchanged = _unchanged_blocks(draft, inspection, source_path, section_key=section_key)
    unchanged_items = set().union(*unchanged.values()) if unchanged else set()
    # Editing one imported table must not rebuild its unchanged neighboring
    # tables (which may have different geometry and span several pages).
    from app.monthly_report_sections import table_without_prices
    reference_prefix = f"docx:{inspection.sha256}:"
    native_tables = {reference_prefix + item.id: item for item in inspection.items
                     if item.kind == "table" and item.part == "word/document.xml"}
    preserved_table_refs = set()
    redacted_table_columns = {}
    destinations = {spec.key: section.key for section in draft.sections for spec in section.blocks}
    for block in draft.blocks:
        if block.source == "Omit":
            continue
        for table in block.extra_tables:
            item = native_tables.get(table.reference)
            if item is not None and item.section == destinations.get(block.key):
                expected, removed = table_without_prices(item)
                if expected is not None and (table.columns, table.rows) == (expected.columns, expected.rows):
                    neighbors = [other for other in inspection.items
                                 if other.part == item.part and other.position == item.position]
                    if all(other.kind == "table" for other in neighbors):
                        preserved_table_refs.add(table.reference)
                        unchanged_items.add(item.id)
                        if removed:
                            redacted_table_columns[item.position] = removed
    # Keep independently supplied unchanged text runs even when a neighboring
    # table has an intentionally excluded pricing column.
    preserved_text = {}
    for block in draft.blocks:
        if block.source == "Omit" or block.key not in destinations:
            continue
        selected = [item for item in inspection.items if item.kind == "text"
                    and item.section == destinations[block.key]
                    and reference_prefix + item.id in block.references]
        expected = "\n\n".join(item.text.strip() for item in selected)
        if selected and block.text.strip() == expected.strip():
            preserved_text[block.key] = True
            unchanged_items.update(item.id for item in selected)
    document = Document(BytesIO(passive_docx(source_path)))
    body = document.element.body
    original = list(body)
    # A mixed-span cell cannot be partly redacted in place. Rebuild that table
    # from the supplied sanitized values so kept technical content is not lost.
    for position, excluded in list(redacted_table_columns.items()):
        mixed = False
        for row in original[position - 1].findall(qn("w:tr")):
            before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
            column = int(before.get(qn("w:val"), "0")) if before is not None else 0
            for cell in row.findall(qn("w:tc")):
                span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
                width = int(span.get(qn("w:val"), "1")) if span is not None else 1
                covered = set(range(column, column + width))
                if covered.intersection(excluded) and covered.difference(excluded) and _text(cell):
                    mixed = True
                column += width
        if mixed:
            del redacted_table_columns[position]
            for reference, item in native_tables.items():
                if item.position == position:
                    preserved_table_refs.discard(reference)
                    unchanged_items.discard(item.id)
    # Word inherits each header/footer kind independently. Materialize those
    # references before slicing so a section preview retains its page chrome.
    inherited = {}
    first_word_end = None
    for position, element in enumerate(original, 1):
        properties = element if element.tag == qn("w:sectPr") else element.find(".//" + qn("w:sectPr"))
        if properties is None:
            continue
        if first_word_end is None:
            first_word_end = position
        present = {}
        for node in properties:
            if node.tag in (qn("w:headerReference"), qn("w:footerReference")):
                present[(node.tag, node.get(qn("w:type"), "default"))] = node
        for key, node in inherited.items():
            if key not in present:
                properties.insert(0, deepcopy(node))
        inherited.update({key: deepcopy(node) for key, node in present.items()})
    items = defaultdict(list)
    for item in inspection.items:
        if item.part == "word/document.xml":
            items[item.position].append(item)
    section_by_pos, section, headings = {}, "cover", set()
    blocks = {block.key: block for block in draft.blocks}
    supplied_notes = {item.note: item for item in inspection.items
                      if item.note.startswith(("footnote:", "endnote:")) and item.text.strip()
                      and any(block.source != "Omit" and reference_prefix + item.id in block.references
                              and item.text.strip() in block.text for block in draft.blocks)}
    source_titles = {title.casefold().strip() for title in inspection.title_candidates
                     if len(title) < 70 and not _MONTH.search(title)
                     and not re.search(r"prepared|section|enfra|monthly|maintenance|insert|confidential|contents", title, re.IGNORECASE)}
    current_columns = {spec.key: tuple(column.title for column in spec.columns)
                       for section in draft.sections for spec in section.blocks}

    brand = blocks.get("brand_logo")
    unchanged_master_brand = bool(brand and brand.source != "Omit" and brand.asset_hashes and any(
        item.kind == "image" and item.part == "word/document.xml"
        and item.position <= (first_word_end or len(original))
        and item.image_height and item.image_width / item.image_height > 4
        and _source_image_digest(str(source_path), inspection.sha256, item, True) in brand.asset_hashes
        for item in inspection.items))
    unchanged_client_brand = False
    client_brand = blocks.get("client_logo")
    if client_brand and client_brand.source != "Omit" and client_brand.asset_hashes:
        unchanged_client_brand = any(
            item.kind == "image" and item.part == "word/document.xml"
            and item.position <= (first_word_end or len(original))
            and item.image_height and 2 < item.image_width / item.image_height <= 4
            and _source_image_digest(str(source_path), inspection.sha256, item, True) in client_brand.asset_hashes
            for item in inspection.items)

    def cover_images(element, group):
        roles = {}
        for item in group:
            if item.kind != "image" or not item.image_width or not item.image_height:
                continue
            ratio = item.image_width / item.image_height
            # ENFRA master: long horizontal marks are page branding; the
            # medium landscape frame is the client mark and the taller is art.
            role = "brand_logo" if ratio > 4 else "client_logo" if ratio > 2 else "cover_photo"
            roles[item.image_part] = role
        for node in list(element.iter()):
            if node.tag not in (qn("a:blip"), "{urn:schemas-microsoft-com:vml}imagedata"):
                continue
            attr = qn("r:embed") if node.tag == qn("a:blip") else qn("r:id")
            rid = node.get(attr)
            rel = document.part.rels.get(rid)
            target = str(rel.target_part.partname).lstrip("/") if rel and not rel.is_external else ""
            role = roles.get(target)
            block = blocks.get(role)
            if block and block.source != "Omit" and block.asset_hashes:
                if ((role == "client_logo" and unchanged_client_brand)
                        or (role == "brand_logo" and unchanged_master_brand)):
                    continue
                supplied = next((item for item in group if item.kind == "image" and item.image_part == target), None)
                if supplied is not None and _source_image_digest(str(source_path), inspection.sha256, supplied,
                                                                role != "cover_photo") in block.asset_hashes:
                    continue  # Explicit unchanged source art retains its native resolution/crop.
                if asset_loader is None:
                    raise NativeLayoutError("Cover images require the saved asset resolver.")
                new_rid, _ = document.part.get_or_add_image(BytesIO(asset_loader(block.asset_hashes[0])))
                node.set(attr, new_rid)
            elif role != "brand_logo" and (master or block is not None):
                # A global master must never lend another client's logo/photo.
                node.getparent().remove(node)

    for position, element in enumerate(original, 1):
        group = items[position]
        detected = next((i.section for i in group if i.section), "")
        if detected:
            section = detected
        section_by_pos[position] = section
        if any(i.kind == "text" and not i.suggested_slot and _heading(i.text) for i in group):
            headings.add(position)
    # Divider artwork is sometimes anchored before its heading, in a separate
    # paragraph (even dozens of empty paragraphs earlier in the same Word section).
    for heading_position in sorted(headings):
        for position in range(heading_position - 1, 0, -1):
            element = original[position - 1]
            if element.find(".//" + qn("w:sectPr")) is not None:
                break
            background = _is_native_divider_background(element, _text(element))
            if background:
                headings.add(position)
                for previous in range(position, heading_position):
                    section_by_pos[previous] = section_by_pos[heading_position]
                break
    divider_word_sections = {item.word_section for position in headings for item in items[position]}
    if section_key and section_key not in set(section_by_pos.values()):
        raise NativeLayoutError(f"The source layout does not contain the {section_key} section.")
    text_prototypes = defaultdict(list)
    image_prototypes = defaultdict(list)
    table_prototypes = defaultdict(list)
    section_ends = {}
    section_text = defaultdict(list)
    section_images = defaultdict(list)
    all_tables = [deepcopy(e) for e in original if e.tag == qn("w:tbl")
                  and not any(True for _ in e.iter(qn("a:blip")))]
    global_images = [deepcopy(paragraph) for position, e in enumerate(original, 1)
                     if section_by_pos[position] != "cover" and position not in headings
                     for paragraph in e.iter(qn("w:p"))
                     if any(True for _ in paragraph.iter(qn("a:blip")))
                     and not any(ancestor.tag == qn("w:p") for ancestor in paragraph.iterancestors())]
    global_text = [deepcopy(e) for position, e in enumerate(original, 1)
                   if section_by_pos[position] != "cover" and position not in headings
                   and e.tag == qn("w:p") and _text(e)
                   and not any(True for _ in e.iter(qn("w:drawing")))]
    for position, element in enumerate(original, 1):
        sec = section_by_pos[position]
        if element.tag == qn('w:sectPr'):
            continue
        section_ends[sec] = element
        if section_key and (sec != section_key or (section_key == "cover" and position > (first_word_end or len(original)))):
            body.remove(element)
            continue
        group = items[position]
        if sec == "cover":
            if position <= (first_word_end or len(original)):
                _cover(element, draft)
            cover_images(element, group)
            continue
        group = items[position]
        if position in headings:
            if any(item.kind == "image" for item in group) and not _is_native_divider_background(element, _text(element)):
                _clear_images(element)
            continue
        substantive = [item for item in group if item.kind in ("text", "table", "image")]
        if substantive and all(item.id in unchanged_items for item in substantive):
            for row in element.findall(qn("w:tr")):
                before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
                logical_column = int(before.get(qn("w:val"), "0")) if before is not None else 0
                excluded = set(redacted_table_columns.get(position, ()))
                for cell in row.findall(qn("w:tc")):
                    span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
                    width = int(span.get(qn("w:val"), "1")) if span is not None else 1
                    if excluded.intersection(range(logical_column, logical_column + width)):
                        _set_text(cell, "")
                    logical_column += width
            continue
        text = _text(element)
        slots = [i.suggested_slot for i in group if i.suggested_slot and not i.suggested_slot.startswith("divider_")]
        slot = slots[0] if slots else _DEFAULT_TEXT.get(sec)
        picture_table = element.tag == qn("w:tbl") and any(item.kind == "image" for item in group)
        if element.tag == qn("w:tbl") and not picture_table:
            table_slot = next((i.suggested_slot for i in group if i.kind == "table" and i.suggested_slot), slot)
            table_prototypes[table_slot].append((element, deepcopy(element)))

        if any(i.kind == "image" for i in group):
            image_slot = next((i.suggested_slot for i in group if i.kind == "image" and i.suggested_slot), slot)
            frames = [element] if element.tag == qn("w:p") else [
                paragraph for paragraph in element.iter(qn("w:p"))
                if any(True for _ in paragraph.iter(qn("a:blip")))
                and not any(ancestor.tag == qn("w:p") for ancestor in paragraph.iterancestors())]
            for frame in frames:
                image_prototypes[image_slot].append((frame, deepcopy(frame)))
                section_images[sec].append(deepcopy(frame))
        if text and text.casefold().strip() not in _STATIC:
            if re.fullmatch(r"(?:Monthly Training Update [–—-] )?" + _MONTH.pattern + r"(?: Activity)?", text, re.IGNORECASE):
                _set_text(element, _MONTH.sub(draft.period.label, text))
            else:
                text_prototypes[slot].append((element, deepcopy(element)))
                if element.tag == qn("w:p"):
                    section_text[sec].append(deepcopy(element))
                _set_text(element, "")
                for paragraph in element.iter(qn("w:p")):
                    if not _text(paragraph):
                        properties = paragraph.find(qn("w:pPr"))
                        if properties is not None:
                            for numbering in list(properties.findall(qn("w:numPr"))):
                                properties.remove(numbering)
                            numbering = OxmlElement("w:numPr")
                            number = OxmlElement("w:numId"); number.set(qn("w:val"), "0")
                            numbering.append(number); properties.append(numbering)
        # Every non-heading body picture/table is old report content.
        _clear_images(element, preserve_decoration=any(
            item.word_section in divider_word_sections for item in group))
        if element.tag == qn("w:tbl"):
            if picture_table:
                for cell in element.iter(qn("w:tc")):
                    _set_text(cell, "")
                continue
            columns = current_columns.get(table_slot)
            if master and columns:
                _table(element, columns, ())
                continue
            native_rows = element.findall(qn("w:tr"))
            header_rows = 1
            if len(native_rows) > 1 and len(native_rows[0].findall(qn("w:tc"))) < len(native_rows[1].findall(qn("w:tc"))):
                header_rows = 2
            for index, row in enumerate(native_rows):
                for cell in row.iter(qn("w:tc")):
                    if index < header_rows:
                        header_text = _text(cell)
                        safe = (len(header_text) < 85 and header_text.casefold().strip() not in source_titles and not re.search(
                            r"@|\b(?:director|manager|price|cost|amount|total recommendations|hospital|medical|regional)\b|\d{3}[ .()-]*\d{3}[ .-]*\d{4}",
                            header_text, re.IGNORECASE))
                        if safe:
                            for text_node in cell.iter(qn("w:t")):
                                text_node.text = _MONTH.sub(draft.period.label, text_node.text or "")
                        else:
                            _set_text(cell, "")
                    else:
                        _set_text(cell, "")

    def append_native(sec, prototype):
        clone = deepcopy(prototype)
        # A copied payload must not introduce another Word section boundary.
        for properties in list(clone.iter(qn("w:sectPr"))):
            properties.getparent().remove(properties)
        _clear_images(clone)
        _set_text(clone, "")
        section_ends[sec].addprevious(clone)
        return clone

    def text_anchor(sec):
        choices = section_text.get(sec) or global_text
        if choices:
            prototype = choices[0]
        else:
            prototype = OxmlElement("w:p")
        return append_native(sec, prototype), prototype

    specs = {b.key: (s.key, b) for s in draft.sections for b in s.blocks}
    render_blocks = list(draft.blocks)
    if draft.follow_ups:
        from app.monthly_report_followups import report_text
        from app.monthly_report_model import ResolvedBlock
        for sec in ("issues", "proposals"):
            texts = [report_text(item) for item in draft.follow_ups
                     if item.included and ("issues" if item.category == "issue" else "proposals") == sec]
            if texts:
                key = "native_followups_" + sec
                specs[key] = (sec, type("TextSpec", (), {"type": "rich_text", "columns": ()})())
                render_blocks.append(ResolvedBlock(key, "This month", text="\n".join(texts)))
    for block in render_blocks:
        if block.source == "Omit" or block.key not in specs or block.key in unchanged:
            continue
        sec, spec = specs[block.key]
        if section_key and sec != section_key:
            continue
        if not any((block.text, block.rows, block.extra_tables, block.asset_hashes, block.org_nodes)):
            continue
        if sec not in section_ends:
            raise NativeLayoutError(f"The source has no native layout for {sec}.")
        text_value = "" if block.key in preserved_text else block.text
        for identity, item in supplied_notes.items():
            kind, note_id = identity.split(":", 1)
            if (reference_prefix + item.id in block.references
                    and any(node.get(qn("w:id")) == note_id for node in body.iter(qn("w:" + kind + "Reference")))):
                text_value = text_value.replace(item.text.strip(), "", 1).strip()
        if text_value:
            anchors = text_prototypes.get(block.key)
            if not anchors:
                anchors = [text_anchor(sec)]
            anchor, prototype = anchors[0]
            values = text_value.splitlines()
            for index, value in enumerate(values):
                if index < len(anchors):
                    _set_text(anchors[index][0], value)
                    anchor = anchors[index][0]
                else:
                    clone = deepcopy(prototype)
                    for properties in list(clone.iter(qn("w:sectPr"))):
                        properties.getparent().remove(properties)
                    _clear_images(clone)
                    _set_text(clone, value)
                    anchor.addnext(clone)
                    anchor = clone
        tables = []
        if block.rows:
            tables.append((tuple(c.title for c in spec.columns), block.rows))
        tables.extend((t.columns, t.rows) for t in block.extra_tables if t.reference not in preserved_table_refs)
        if tables:
            anchors = table_prototypes.get(block.key)
            if not anchors:
                width = len(tables[0][0])
                prototype = next((table for table in all_tables
                                  if len(table.find(qn("w:tr")).findall(qn("w:tc"))) == width), None)
                if prototype is None:
                    prototype = all_tables[0] if all_tables else None
                if prototype is None:
                    raise NativeLayoutError(f"The source has no native table geometry for {block.key}.")
                anchors = [(append_native(sec, prototype), prototype)]
            last = None
            for index, (columns, rows) in enumerate(tables):
                anchor, prototype = anchors[min(index, len(anchors) - 1)]
                if index >= len(anchors):
                    anchor = deepcopy(prototype)
                    last.addnext(anchor)
                _table(anchor, columns, rows)
                last = anchor
        images = []
        if block.org_nodes:
            from app.monthly_report_visuals import org_groups, org_page
            images = [org_page(block.org_nodes, n) for n in range(len(org_groups(block.org_nodes)))]
        elif block.asset_hashes:
            if asset_loader is None:
                raise NativeLayoutError("Native images require the saved asset resolver.")
            images = [asset_loader(ref) for ref in block.asset_hashes]
        if images:
            anchors = image_prototypes.get(block.key)
            if not anchors:
                choices = section_images.get(sec) or global_images
                if not choices:
                    raise NativeLayoutError(f"The source has no native picture frame for {block.key}.")
                prototype = choices[0]
                anchors = [(append_native(sec, prototype), prototype)]
            last = None
            for index, data in enumerate(images):
                anchor, prototype = anchors[min(index, len(anchors) - 1)]
                clone = deepcopy(prototype)
                for properties in list(clone.iter(qn("w:sectPr"))):
                    properties.getparent().remove(properties)
                _set_text(clone, "")
                _replace_image(document, clone, data)
                if index < len(anchors):
                    anchor.addprevious(clone)
                    anchor.getparent().remove(anchor)
                else:
                    last.addnext(clone)
                last = clone
                if index < len(block.asset_captions) and block.asset_captions[index].strip():
                    choices = section_text.get(sec) or global_text
                    caption = deepcopy(choices[0]) if choices else OxmlElement("w:p")
                    for properties in list(caption.iter(qn("w:sectPr"))):
                        properties.getparent().remove(properties)
                    _clear_images(caption)
                    _set_text(caption, block.asset_captions[index])
                    clone.addnext(caption)
                    last = caption
    if section_key:
        selected_positions = [position for position, sec in section_by_pos.items()
                              if sec == section_key and original[position - 1].tag != qn("w:sectPr")
                              and (section_key != "cover" or position <= (first_word_end or len(original)))]
        closing = None
        if selected_positions:
            for element in original[max(selected_positions) - 1:]:
                properties = element if element.tag == qn("w:sectPr") else element.find(".//" + qn("w:sectPr"))
                if properties is not None:
                    closing = deepcopy(properties)
                    break
        if closing is not None:
            # The selected range's final paragraph break becomes the document's
            # terminal section properties. Keeping both opens an empty next page.
            last_selected = original[max(selected_positions) - 1]
            last_boundary = last_selected.find(".//" + qn("w:sectPr"))
            if last_boundary is not None:
                last_boundary.getparent().remove(last_boundary)
            for existing in list(body.findall(qn("w:sectPr"))):
                body.remove(existing)
            body.append(closing)

    # Source notes and comments are source facts, not current report content.
    explicit_notes = set(supplied_notes)
    for node in list(body.iter()):
        if node.tag in (qn("w:footnoteReference"), qn("w:endnoteReference")):
            kind = "footnote" if node.tag == qn("w:footnoteReference") else "endnote"
            if kind + ":" + node.get(qn("w:id"), "") not in explicit_notes:
                node.getparent().remove(node)
    for part in list(document.part.package.parts):
        name = str(part.partname)
        if not name.startswith(("/word/header", "/word/footer")) or not hasattr(part, "element"):
            continue
        for paragraph in part.element.iter(qn("w:p")):
            visible = deepcopy(paragraph)
            for fallback in list(visible.iter("{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback")):
                fallback.getparent().remove(fallback)
            from app.monthly_report_import import _remove_page_field_results
            _remove_page_field_results(visible, [])
            text = _text(visible)
            if "enfrasolutions.com" in text.casefold() and draft.address_line.strip():
                if text != draft.address_line:
                    _set_text(paragraph, draft.address_line)
                continue
            if (text and "enfrasolutions.com" not in text.casefold()
                    and not re.fullmatch(r"(?:enfra|author:|client utility rate analysis)(?:\s+(?:author:|client utility rate analysis))*", text.strip(), re.IGNORECASE)
                    and not text.strip().isdigit()):
                _set_text(paragraph, "")
        if brand and brand.source != "Omit" and brand.asset_hashes:
            if asset_loader is None:
                raise NativeLayoutError("ENFRA branding requires the saved asset resolver.")
            source_brands = {item.image_part for item in inspection.items
                             if item.part == name.lstrip("/") and item.kind == "image"
                             and item.image_height and item.image_width / item.image_height > 4}
            for node in part.element.iter(qn("a:blip")):
                rel = part.rels.get(node.get(qn("r:embed")))
                if rel and not rel.is_external and str(rel.target_part.partname).lstrip("/") in source_brands:
                    if unchanged_master_brand:
                        continue
                    source_item = next((item for item in inspection.items
                                        if item.kind == "image" and item.part == name.lstrip("/")
                                        and item.image_part == str(rel.target_part.partname).lstrip("/")), None)
                    if source_item is not None and _source_image_digest(str(source_path), inspection.sha256, source_item, True) in brand.asset_hashes:
                        continue
                    rid, _ = part.get_or_add_image(BytesIO(asset_loader(brand.asset_hashes[0])))
                    node.set(qn("r:embed"), rid)
    result = BytesIO()
    document.save(result)
    # Prune image relationships which became unused after old payload removal.
    with tempfile.TemporaryDirectory(prefix="native-report-") as folder:
        output = Path(folder) / "report.docx"
        output.write_bytes(result.getvalue())
        return passive_docx(output)
