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
                 "training": "training_summary", "rfi": "rfi_matrix",
                 "accounts_receivable": "accounts_receivable_notes"}
_MONTH = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d\d\b", re.IGNORECASE)


def _clear_hyperlinks(element):
    """Source click destinations are facts, not reusable text formatting."""
    for link in list(element.iter(qn("w:hyperlink"))):
        parent = link.getparent()
        if parent is not None:
            index = parent.index(link)
            for child in list(link):
                parent.insert(index, child)
                index += 1
            parent.remove(link)
    for tag in (qn("a:hlinkClick"), qn("a:hlinkHover")):
        for link in list(element.iter(tag)):
            link.getparent().remove(link)


def _set_text(element, value):
    """Change run payloads while retaining paragraph/run/text-box properties."""
    _clear_hyperlinks(element)
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


def _clear_source_drawing_metadata(document):
    """Source frame descriptions are facts, not reusable master geometry."""
    drawing_namespaces = {
        "http://schemas.openxmlformats.org/drawingml/2006/picture",
        "http://schemas.openxmlformats.org/drawingml/2006/main",
        "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
        "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    }
    for part in document.part.package.parts:
        if not hasattr(part, "element"):
            continue
        for node in part.element.iter():
            namespace, _, local = node.tag[1:].partition("}") if node.tag.startswith("{") else ("", "", node.tag)
            if namespace in drawing_namespaces and local in {"docPr", "cNvPr"}:
                node.attrib.pop("descr", None)
                node.attrib.pop("title", None)
                # Keep the required nonvisual name without importing a client's
                # name, file name or old caption. IDs/references stay unchanged.
                if "name" in node.attrib:
                    node.set("name", "Drawing " + node.get("id", ""))
            elif namespace == "urn:schemas-microsoft-com:vml":
                for attr in list(node.attrib):
                    if attr.rsplit("}", 1)[-1] in {"alt", "title"}:
                        del node.attrib[attr]


def _clear_diagrams(element):
    # A diagram may share a drawing canvas with a retained text-box frame.
    # Its relationship payload must still disappear when that content is cleared.
    for diagram in list(element.iter("{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds")):
        diagram.getparent().remove(diagram)


def _clear_images(element, *, preserve_decoration=False):
    _clear_diagrams(element)
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


def _contain_replacement_picture(element, data):
    """Keep a current improvement photograph inside its native physical frame.

    The previous asset's crop and aspect are not evidence for the current one.
    Unchanged source pictures never pass through this function.  Do not guess
    geometry for unsupported picture containers or grouped VML art.
    """
    from PIL import Image
    with Image.open(BytesIO(data)) as image:
        width, height = image.size
        # Reading orientation metadata avoids a second full image decode just to
        # measure a current photograph on Render's memory-constrained instance.
        if image.getexif().get(274, 1) in (5, 6, 7, 8):
            width, height = height, width
    if width <= 0 or height <= 0:
        raise NativeLayoutError("This replacement picture has no usable dimensions.")
    pictures = list(element.iter(qn("pic:pic")))
    for picture in pictures:
        extent = picture.find("./" + qn("pic:spPr") + "/" + qn("a:xfrm") + "/" + qn("a:ext"))
        frame = next((parent for parent in picture.iterancestors()
                      if parent.tag in (qn("wp:anchor"), qn("wp:inline"))), None)
        outer = frame.find(qn("wp:extent")) if frame is not None else None
        if extent is None or outer is None:
            raise NativeLayoutError("The native photo frame cannot be fitted safely. Add this picture to a new photo page.")
        try:
            full_width, full_height = int(outer.get("cx", "0")), int(outer.get("cy", "0"))
        except ValueError as exc:
            raise NativeLayoutError("The native photo frame dimensions are invalid.") from exc
        if min(full_width, full_height) <= 0:
            raise NativeLayoutError("The native photo frame has no usable area.")
        scale = min(full_width / width, full_height / height)
        new_width, new_height = round(width * scale), round(height * scale)
        for node in (outer, extent):
            node.set("cx", str(new_width)); node.set("cy", str(new_height))
        # The physical frame must contain every edge of the current photo.
        # A prior photo's source-rectangle values would crop those edges.
        for crop in list(picture.iter(qn("a:srcRect"))):
            crop.getparent().remove(crop)
    for shape in list(element.iter("{urn:schemas-microsoft-com:vml}shape")):
        images = list(shape.iter("{urn:schemas-microsoft-com:vml}imagedata"))
        if not images:
            continue
        if any(parent.tag == "{urn:schemas-microsoft-com:vml}group" for parent in shape.iterancestors()):
            raise NativeLayoutError("Grouped native photo frames need a reviewed replacement page; their image proportions cannot be assumed.")
        original = shape.get("style", "")
        found = {}
        for axis in ("width", "height"):
            result = re.search(r"(?:(?<=;)|^)\s*" + axis + r"\s*:\s*(\d+(?:\.\d+)?)(in|pt)(?=;|$)", original)
            if result:
                found[axis] = (result, float(result[1]) * (72 if result[2] == "in" else 1))
        if len(found) != 2:
            raise NativeLayoutError("The native photo frame dimensions cannot be fitted safely.")
        scale = min(found["width"][1] / width, found["height"][1] / height)
        target = {"width": width * scale, "height": height * scale}
        # Replace later spans first; VML permits height before width as well.
        for axis, (result, _) in sorted(found.items(), key=lambda item: item[1][0].start(), reverse=True):
            value = target[axis] / (72 if result[2] == "in" else 1)
            replacement = f"{axis}:{value:.6f}{result[2]}"
            original = original[:result.start()] + replacement + original[result.end():]
        shape.set("style", original)
        for image in images:
            for key in ("cropleft", "cropright", "croptop", "cropbottom"):
                image.attrib.pop(key, None)
    if not pictures and not any(True for _ in element.iter("{urn:schemas-microsoft-com:vml}imagedata")):
        raise NativeLayoutError("The native photo replacement lacks a supported image frame.")


def _replace_image(document, element, data, *, contain=False):
    # Mixed picture/SmartArt paragraphs are cloned as image frames. Updating a
    # raster is not proof that the neighboring source diagram is current.
    _clear_diagrams(element)
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
    if contain:
        _contain_replacement_picture(element, data)


def _fit_cover_photo(node, image_width, image_height):
    """Center a replacement photo inside its existing native picture frame."""
    if image_width <= 0 or image_height <= 0:
        raise NativeLayoutError("The cover photograph has no usable dimensions.")
    frame = None
    if node.tag == qn("a:blip"):
        for ancestor in node.iterancestors():
            transforms = ancestor.findall(qn("a:xfrm"))
            for child in ancestor:
                if child.tag.rsplit("}", 1)[-1] == "spPr":
                    transforms.extend(child.findall(qn("a:xfrm")))
            ext = next((transform.find(qn("a:ext")) for transform in transforms
                        if transform.find(qn("a:ext")) is not None), None)
            if ext is not None:
                frame = (float(ext.get("cx", "0")), float(ext.get("cy", "0")))
                break
    else:
        def dimensions(element):
            values = {}
            for key, value, unit in re.findall(r"(?:^|;)\s*(width|height)\s*:\s*([\d.]+)([a-z]*)", element.get("style", "")):
                values[key] = float(value) * {"in": 72, "cm": 72 / 2.54, "mm": 72 / 25.4,
                                              "px": .75}.get(unit, 1)
            return (values.get("width", 0), values.get("height", 0))

        shape = next((ancestor for ancestor in node.iterancestors()
                      if ancestor.tag == "{urn:schemas-microsoft-com:vml}shape"), None)
        if shape is not None:
            width, height = dimensions(shape)
            for group in shape.iterancestors():
                if group.tag != "{urn:schemas-microsoft-com:vml}group":
                    continue
                coordinates = group.get("coordsize", "").split(",")
                group_width, group_height = dimensions(group)
                if len(coordinates) == 2 and all(float(value) > 0 for value in coordinates) and group_width and group_height:
                    width *= group_width / float(coordinates[0])
                    height *= group_height / float(coordinates[1])
            frame = width, height
    if not frame or min(frame) <= 0:
        raise NativeLayoutError("The cover photograph's native frame dimensions are unavailable.")
    frame_ratio = frame[0] / frame[1]
    image_ratio = image_width / image_height
    horizontal = max(0, (1 - frame_ratio / image_ratio) / 2)
    vertical = max(0, (1 - image_ratio / frame_ratio) / 2)
    crop = {"l": horizontal, "r": horizontal, "t": vertical, "b": vertical}
    if node.tag == qn("a:blip"):
        fill = node.getparent()
        rectangle = fill.find(qn("a:srcRect"))
        if rectangle is None:
            rectangle = OxmlElement("a:srcRect")
            node.addnext(rectangle)
        for key, value in crop.items():
            rectangle.set(key, str(round(value * 100000)))
    else:
        for key, name in {"l": "cropleft", "r": "cropright", "t": "croptop", "b": "cropbottom"}.items():
            node.set(name, format(crop[key], ".8f"))


def _table(element, columns, rows):
    explicit_header = bool(columns)
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
    if explicit_header and rows:
        from app.monthly_report_table_pagination import keep_current_header_with_rows
        keep_current_header_with_rows(element)


def _cover(element, draft, *, preserve_issue_date=False):
    paragraphs = list(element.iter(qn("w:p")))
    for paragraph in paragraphs:
        # Nested paragraphs are handled separately; never flatten the outer shape.
        if paragraph.find('.//' + qn('w:txbxContent')) is not None:
            continue
        text = _text(paragraph)
        if not text:
            continue
        if re.search(r"prepared\s+by", text, re.IGNORECASE):
            value = "Prepared by: " + draft.prepared_by
            issued = re.search(r"\s+Date\s*:.*$", text, re.IGNORECASE)
            if issued and preserve_issue_date and not re.search(r"\bDate\s*:", value, re.IGNORECASE):
                value += issued.group()
            _set_text(paragraph, value)
        elif re.match(r"^\s*Date\s*:", text, re.IGNORECASE):
            if not preserve_issue_date:
                _set_text(paragraph, "")
        elif _MONTH.search(text):
            _set_text(paragraph, _MONTH.sub(draft.period.label, text))
        elif (text.strip().upper() not in {"ENFRA", "=", "INSERT IMAGE HERE"}
              and "operations and maintenance" not in text.casefold()
              and "monthly review" not in text.casefold()
              and "confidential" not in text.casefold()
              and "create." not in text.casefold()
              and "section" not in text.casefold()
              and "table of contents" not in text.casefold()):
            changed_title = text != draft.profile.title
            _set_text(paragraph, draft.profile.title)
            if changed_title and len(draft.profile.title) > 22:
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
                    if ((neighbor.kind in ("text", "table", "image") and neighbor.id not in supported)
                            or neighbor.note.startswith("Unmapped native SmartArt")):
                        valid = False
            if not valid:
                del candidates[key]
                changed = True
    return candidates


def _patch_current_table_cells(element, source_item, expected, current):
    """Apply same-shape current cell edits without rebuilding mixed picture cells."""
    old_values = (expected.columns, *expected.rows)
    new_values = (current.columns, *current.rows)
    native_rows = element.findall(qn("w:tr"))
    if len(old_values) != len(new_values) or len(native_rows) != len(old_values):
        return False
    changes = []
    for row_index, (row, old, new) in enumerate(zip(native_rows, old_values, new_values)):
        if len(old) != len(new):
            return False
        before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
        column = int(before.get(qn("w:val"), "0")) if before is not None else 0
        addressed = set()
        for cell in row.findall(qn("w:tc")):
            span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
            width = int(span.get(qn("w:val"), "1")) if span is not None else 1
            if column >= len(old) or _text(cell) != source_item.rows[row_index][column]:
                return False
            addressed.add(column)
            if old[column] != new[column]:
                changes.append((cell, new[column]))
            column += width
        # A value cannot be written into a skipped/merged continuation column.
        if any(a != b and index not in addressed for index, (a, b) in enumerate(zip(old, new))):
            return False
    for cell, value in changes:
        _set_text(cell, value)
    return True


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
    cover_periods = {match.group().casefold() for title in inspection.title_candidates
                     for match in _MONTH.finditer(re.split(r"\bDate\s*:", title, flags=re.IGNORECASE)[0])}
    cover_names = {re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
                   for title in inspection.title_candidates}
    source_preparers = {re.split(r"\s+Date\s*:", re.sub(r"^\s*Prepared\s+by\s*:\s*", "", title,
                        flags=re.IGNORECASE), flags=re.IGNORECASE)[0].strip()
                        for title in inspection.title_candidates if re.match(r"^\s*Prepared\s+by\s*:", title, re.IGNORECASE)}
    current_preparer = re.split(r"\s+Date\s*:", draft.prepared_by, flags=re.IGNORECASE)[0].strip()
    preserve_issue_date = (not master and cover_periods == {draft.period.label.casefold()}
        and re.sub(r"[^a-z0-9]+", " ", draft.profile.title.casefold()).strip() in cover_names
        and current_preparer in source_preparers
        and any(ref.startswith(reference_prefix) for block in draft.blocks for ref in block.references))
    native_tables = {reference_prefix + item.id: item for item in inspection.items
                     if item.kind == "table" and item.part == "word/document.xml"}
    preserved_table_refs = set()
    redacted_table_columns = {}
    supplied_tables_by_position = {}
    retained_mixed_cells = set()
    mixed_price_headers = set()
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
                            supplied_tables_by_position[item.position] = table
    # Keep independently supplied unchanged text runs even when a neighboring
    # table has an intentionally excluded pricing column.
    preserved_text = {}
    for block in draft.blocks:
        if block.source == "Omit" or block.key not in destinations:
            continue
        selected = [item for item in inspection.items if item.kind == "text"
                    and (item.section == destinations[block.key] or item.note == "Native divider artwork")
                    and reference_prefix + item.id in block.references]
        expected = "\n\n".join(item.text.strip() for item in selected)
        if selected and block.text.strip() == expected.strip():
            preserved_text[block.key] = True
            unchanged_items.update(item.id for item in selected)
    # Current images can be unchanged even when another table in their block
    # was edited. Prove the complete selected image sequence independently.
    image_proofs = {}
    for block in draft.blocks:
        if block.source == "Omit" or block.org_nodes or block.key not in destinations:
            continue
        selected_images = [item for item in inspection.items if item.kind == "image"
                           and item.part == "word/document.xml"
                           and (item.section == destinations[block.key] or item.note == "Native divider artwork")
                           and reference_prefix + item.id in block.references]
        image_values = [(item, _source_image_digest(str(source_path), inspection.sha256, item,
                        block.key not in ("cover_photo", "improvements"))) for item in selected_images]
        expected_assets = tuple(dict.fromkeys(value for _, value in image_values))
        expected_captions = tuple(item.text for item in selected_images)
        captions = tuple(block.asset_captions) + ("",) * max(0, len(expected_captions) - len(block.asset_captions))
        if image_values and block.asset_hashes == expected_assets and captions == expected_captions:
            image_proofs.update({item.id: (block.key, value) for item, value in image_values})
            unchanged_items.update(item.id for item, _ in image_values)
    retained_images = defaultdict(set)
    document = Document(BytesIO(passive_docx(source_path)))
    _clear_source_drawing_metadata(document)
    body = document.element.body
    original = list(body)
    # A merged technical cell may cross a removed price column. Preserve its
    # geometry only when its text is explicitly present in the supplied filtered
    # table. A cell beginning in a removed column is redacted in full.
    from app.monthly_report_content_policy import contains_price
    for position, excluded in list(redacted_table_columns.items()):
        mixed = False
        supplied = supplied_tables_by_position[position]
        source_item = next(item for item in native_tables.values() if item.position == position)
        kept_columns = [i for i in range(len(source_item.rows[0])) if i not in excluded]
        for row_index, row in enumerate(original[position - 1].findall(qn("w:tr"))):
            before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
            column = int(before.get(qn("w:val"), "0")) if before is not None else 0
            for cell in row.findall(qn("w:tc")):
                span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
                width = int(span.get(qn("w:val"), "1")) if span is not None else 1
                covered = set(range(column, column + width))
                if covered.intersection(excluded) and covered.difference(excluded) and _text(cell) and column not in excluded:
                    current_row = supplied.columns if row_index == 0 else supplied.rows[row_index - 1]
                    current_column = kept_columns.index(column) if column in kept_columns else -1
                    value = _text(cell)
                    from app.monthly_report_content_policy import logical_table_columns
                    logical_headers = logical_table_columns(source_item.rows[0])
                    if (row_index == 0 and column == 0 and width == len(logical_headers)
                            and logical_headers != tuple(source_item.rows[0])
                            and tuple(logical_headers[i] for i in kept_columns) == supplied.columns):
                        retained_mixed_cells.add((position, row_index, column))
                        mixed_price_headers.add((position, row_index, column))
                    elif (current_column >= 0 and current_column < len(current_row)
                            and current_row[current_column] == (value.strip() if row_index == 0 else value)
                            and not contains_price(value)):
                        retained_mixed_cells.add((position, row_index, column))
                    else:
                        mixed = True
                column += width
        if mixed:
            del redacted_table_columns[position]
            for reference, item in native_tables.items():
                if item.position == position:
                    preserved_table_refs.discard(reference)
                    unchanged_items.discard(item.id)
    inplace_table_positions = set()
    # Mixed technical tables retain their exact source anchor, grid, rows and
    # cell artwork only when every neighboring payload is explicitly current.
    # Bind by source reference, never by the ordinal of the remaining tables.
    for block in draft.blocks:
        if block.source == "Omit" or block.key not in destinations:
            continue
        for current in block.extra_tables:
            source_item = native_tables.get(current.reference)
            if source_item is None or source_item.section != destinations[block.key]:
                continue
            neighbors = [item for item in inspection.items
                         if item.part == source_item.part and item.position == source_item.position]
            if not any(item.kind == "image" for item in neighbors):
                continue
            if any(item.kind == "text" and item.id not in unchanged_items for item in neighbors):
                continue
            expected, removed = table_without_prices(source_item)
            if expected is None or removed:
                continue
            element = original[source_item.position - 1]
            if element.tag != qn("w:tbl") or not _patch_current_table_cells(element, source_item, expected, current):
                continue
            unchanged_items.add(source_item.id)
            preserved_table_refs.add(current.reference)
            inplace_table_positions.add(source_item.position)
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
            if section_key and key not in present:
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
    cover_roles = {}
    cover_items = [item for item in inspection.items if item.kind == "image"
                   and item.part == "word/document.xml"
                   and (not item.section or item.position <= (first_word_end or len(original)))]
    first_cover_images = [item for item in cover_items
                          if item.position <= (first_word_end or len(original))]
    primary_brand = next((item.image_part for item in first_cover_images
                          if item.image_height and item.image_width / item.image_height > 4), None)
    photo_candidates = [item for item in first_cover_images if item.image_part != primary_brand
                        and item.image_width >= 256 and item.image_height >= 256]
    primary_photo = max(photo_candidates, key=lambda item: item.image_width * item.image_height,
                        default=None)
    # Explicit import destinations are authoritative. Aspect ratio cannot tell
    # a wide hospital logo from ENFRA branding or a landscape hospital photo.
    for item in cover_items:
        for role in ("brand_logo", "client_logo", "cover_photo"):
            block = blocks.get(role)
            if block and reference_prefix + item.id in block.references:
                cover_roles[item.image_part] = role
                break
    for item in cover_items:
        if item.image_part in cover_roles:
            continue
        for role in ("brand_logo", "client_logo", "cover_photo"):
            block = blocks.get(role)
            if block and block.asset_hashes and _source_image_digest(
                    str(source_path), inspection.sha256, item, role != "cover_photo") in block.asset_hashes:
                cover_roles[item.image_part] = role
                break
        if item.image_part not in cover_roles and item.image_height:
            ratio = item.image_width / item.image_height
            if master:
                cover_roles[item.image_part] = ("brand_logo" if item.image_part == primary_brand else
                                                "cover_photo" if primary_photo and item.image_part == primary_photo.image_part else
                                                "client_logo")
            else:
                cover_roles[item.image_part] = "brand_logo" if ratio > 4 else "client_logo" if ratio > 2 else "cover_photo"

    def unchanged_cover(role):
        block = blocks.get(role)
        return bool(block and block.source != "Omit" and block.asset_hashes and any(
            cover_roles.get(item.image_part) == role
            and _source_image_digest(str(source_path), inspection.sha256, item, role != "cover_photo") in block.asset_hashes
            for item in cover_items))

    unchanged_master_brand = unchanged_cover("brand_logo")
    unchanged_client_brand = unchanged_cover("client_logo")

    def cover_images(element, group):
        roles = cover_roles
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
                new_rid, image = document.part.get_or_add_image(BytesIO(asset_loader(block.asset_hashes[0])))
                node.set(attr, new_rid)
                for layer in node.iter():
                    if layer.get(qn("r:embed")):
                        layer.set(qn("r:embed"), new_rid)
                    layer.attrib.pop(qn("r:link"), None)
                if role == "cover_photo":
                    _fit_cover_photo(node, image.px_width, image.px_height)
            elif role != "brand_logo" and (master or block is not None):
                # A global master must never lend another client's logo/photo.
                node.getparent().remove(node)

    for position, element in enumerate(original, 1):
        group = items[position]
        detected = next((i.section for i in group if i.section), "")
        if detected:
            section = detected
        section_by_pos[position] = section
        if (any(i.note == "Native divider artwork" for i in group)
                and _is_native_divider_background(element, _text(element))):
            headings.add(position)
        if any(i.note == "Native section heading" or
               (i.kind == "text" and not i.suggested_slot and _heading(i.text)) for i in group):
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
    from app.monthly_report_native_pages import NativePages
    unchanged_positions = {item.position for item in inspection.items
                           if item.part == "word/document.xml" and item.id in unchanged_items}
    page_plan = NativePages(body, original, section_by_pos, headings, unchanged_positions, fresh=master)
    from app.monthly_report_native_text import (narrative_prototype, write_narrative,
                                                 header_contains_label)
    narrative_styles = {style.style_id: style.element for style in document.styles}
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
    global_text = [prototype for position, e in enumerate(original, 1)
                   if section_by_pos[position] != "cover" and position not in headings
                   and e.tag == qn("w:p")
                   and (prototype := narrative_prototype(e, narrative_styles, _STATIC)) is not None]
    for position, element in enumerate(original, 1):
        sec = section_by_pos[position]
        if element.tag == qn('w:sectPr'):
            continue
        section_ends[sec] = element
        if section_key and (sec != section_key or (section_key == "cover" and position > (first_word_end or len(original)))):
            body.remove(element)
            continue
        group = items[position]
        current_payload = [item for item in group if item.kind in ("text", "table", "image")]
        if not (current_payload and all(item.id in unchanged_items for item in current_payload)
                and not any(item.note.startswith("Unmapped native SmartArt") for item in group)):
            _clear_hyperlinks(element)
        if sec == "cover":
            # Cover/company marks have a separate asset binding. Unsupported
            # SmartArt there must not lend source client facts to a fresh report.
            _clear_diagrams(element)
            _clear_hyperlinks(element)
            if position <= (first_word_end or len(original)):
                _cover(element, draft, preserve_issue_date=preserve_issue_date)
            cover_images(element, group)
            continue
        group = items[position]
        if position in headings:
            if _is_native_divider_background(element, _text(element)):
                # Older saved mappings may have mistaken the images in a
                # grouped divider for organization photos. Their proven native
                # frames are already present; do not append another full-page
                # canvas for each previously selected constituent image.
                for item in group:
                    if item.kind != "image" or item.note != "Native divider artwork":
                        continue
                    for block in draft.blocks:
                        if (block.source != "Omit" and reference_prefix + item.id in block.references
                                and block.asset_hashes):
                            digest = _source_image_digest(str(source_path), inspection.sha256, item,
                                                         block.key not in ("cover_photo", "improvements"))
                            if digest in block.asset_hashes:
                                retained_images[block.key].add(digest)
            diagrams = [item for item in group if item.note == "Validated native SmartArt text"]
            unproved_diagram = (any(True for _ in element.iter(
                "{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds"))
                and (not diagrams or any(item.id not in unchanged_items for item in diagrams)
                     or any(item.note.startswith("Unmapped native SmartArt") for item in group)))
            if (unproved_diagram or (any(item.kind == "image" for item in group)
                    and not _is_native_divider_background(element, _text(element)))):
                _clear_images(element)
            continue
        substantive = [item for item in group if item.kind in ("text", "table", "image")]
        if (substantive and all(item.id in unchanged_items for item in substantive)
                and not any(item.note.startswith("Unmapped native SmartArt") for item in group)):
            for item in substantive:
                if item.id in image_proofs:
                    owner, digest = image_proofs[item.id]
                    retained_images[owner].add(digest)
            for row_index, row in enumerate(element.findall(qn("w:tr"))):
                before = row.find("./" + qn("w:trPr") + "/" + qn("w:gridBefore"))
                logical_column = int(before.get(qn("w:val"), "0")) if before is not None else 0
                excluded = set(redacted_table_columns.get(position, ()))
                for cell in row.findall(qn("w:tc")):
                    span = cell.find("./" + qn("w:tcPr") + "/" + qn("w:gridSpan"))
                    width = int(span.get(qn("w:val"), "1")) if span is not None else 1
                    if (excluded.intersection(range(logical_column, logical_column + width))
                            and (position, row_index, logical_column) not in retained_mixed_cells):
                        _set_text(cell, "")
                    if (position, row_index, logical_column) in mixed_price_headers:
                        for node in cell.iter(qn("w:t")):
                            if node.text:
                                node.text = re.sub(r"Cost", "", node.text, flags=re.IGNORECASE)
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
        if position in inplace_table_positions:
            # The values were updated at this exact source reference. When the
            # neighboring images lack current proof, replace only those frames;
            # never erase/reappend the already current technical table itself.
            _clear_images(element)
            continue
        if element.tag == qn("w:p") and text and text.casefold().strip() not in _STATIC:
            if re.fullmatch(r"(?:Monthly Training Update [–—-] )?" + _MONTH.pattern + r"(?: Activity)?", text, re.IGNORECASE):
                _set_text(element, _MONTH.sub(draft.period.label, text))
                page_plan.support.add(element)
            else:
                label = re.fullmatch(r"(Client Utility Rate Analysis)(?:\s+Author:.*)?", text, re.IGNORECASE)
                prototype = None if label else narrative_prototype(element, narrative_styles, _STATIC)
                if prototype is not None:
                    text_prototypes[slot].append((element, prototype))
                    section_text[sec].append(deepcopy(prototype))
                _set_text(element, "")
                if label:
                    region = page_plan.owner.get(element)
                    properties = page_plan.regions[region].properties if region is not None else document.sections[-1]._sectPr
                    if not header_contains_label(document, properties, label[1]):
                        _set_text(element, label[1])
                        page_plan.support.add(element)
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
        page_plan.assigned(clone, section_ends[sec])
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
        relocated_notes = []
        for identity, item in supplied_notes.items():
            kind, note_id = identity.split(":", 1)
            if (reference_prefix + item.id in block.references
                    and any(node.get(qn("w:id")) == note_id for node in body.iter(qn("w:" + kind + "Reference")))):
                text_value = text_value.replace(item.text.strip(), "", 1).strip()
                if block.key not in preserved_text:
                    references = [node for anchor, _ in text_prototypes.get(block.key, ())
                                  for node in anchor.iter(qn("w:" + kind + "Reference"))
                                  if node.get(qn("w:id")) == note_id]
                    if references:
                        relocated_notes.append(deepcopy(references[0]))
                        for node in references:
                            node.getparent().remove(node)
        if text_value or relocated_notes:
            anchors = text_prototypes.get(block.key)
            if not anchors:
                anchors = [text_anchor(sec)]
            anchor, prototype = anchors[0]
            # Current prose is one flow, not one old canvas/page per new line.
            # Unchanged, source-proved text has already bypassed this writer.
            for index, value in enumerate(text_value.splitlines() or [""]):
                if index:
                    clone = deepcopy(prototype)
                    anchor.addnext(clone)
                    page_plan.assigned(clone, anchor)
                    anchor = clone
                write_narrative(anchor, prototype, value)
                if index == 0:
                    # Explicitly retained foot/endnotes move with rewritten
                    # prose; source-only references and reviewer history do not.
                    for note in relocated_notes:
                        run = OxmlElement("w:r")
                        properties = OxmlElement("w:rPr")
                        align = OxmlElement("w:vertAlign"); align.set(qn("w:val"), "superscript")
                        properties.append(align); run.append(properties); run.append(note)
                        anchor.append(run)
                page_plan.emitted(anchor)
        tables = []
        if block.rows:
            tables.append((tuple(c.title for c in spec.columns), block.rows, ""))
        tables.extend((t.columns, t.rows, t.reference) for t in block.extra_tables
                      if t.reference not in preserved_table_refs and (t.rows or not master))
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
            for index, (columns, rows, table_reference) in enumerate(tables):
                anchor, prototype = anchors[min(index, len(anchors) - 1)]
                if index >= len(anchors):
                    anchor = deepcopy(prototype)
                    last.addnext(anchor)
                    page_plan.assigned(anchor, last)
                _table(anchor, columns, rows)
                page_plan.emitted(anchor, kind="table")
                from app.monthly_report_training_style import style_training_table
                style_training_table(anchor, table_reference)
                last = anchor
        images = []
        image_indexes = []
        if block.org_nodes:
            from app.monthly_report_visuals import org_groups, org_page
            images = [org_page(block.org_nodes, n) for n in range(len(org_groups(block.org_nodes)))]
        elif block.asset_hashes:
            if asset_loader is None:
                raise NativeLayoutError("Native images require the saved asset resolver.")
            image_indexes = [index for index, ref in enumerate(block.asset_hashes)
                             if ref not in retained_images[block.key]]
            images = [asset_loader(block.asset_hashes[index]) for index in image_indexes]
        if images:
            anchors = image_prototypes.get(block.key)
            if not anchors:
                choices = section_images.get(sec) or global_images
                if not choices and block.key in ("improvements", "cover_photo", "brand_logo", "client_logo"):
                    raise NativeLayoutError(f"The source has no native picture frame for {block.key}.")
                # Technical content needs the section's page geometry, not an
                # old photograph. Empty chart pages can accept a new inline frame.
                prototype = choices[0] if choices else OxmlElement("w:p")
                anchors = [(append_native(sec, prototype), prototype)]
            last = None
            for index, data in enumerate(images):
                anchor, prototype = anchors[min(index, len(anchors) - 1)]
                technical = block.key not in ("improvements", "cover_photo", "brand_logo", "client_logo")
                if technical:
                    clone = page_plan.technical_picture(document, anchor if index < len(anchors) else last, data, new_page=index > 0,
                                                        caption=bool(block.asset_captions))
                else:
                    clone = deepcopy(prototype)
                    for properties in list(clone.iter(qn("w:sectPr"))):
                        properties.getparent().remove(properties)
                    _set_text(clone, "")
                    _replace_image(document, clone, data, contain=block.key == "improvements")
                if index < len(anchors):
                    anchor.addprevious(clone)
                    page_plan.emitted(clone, anchor, kind="picture")
                    # The old frame may own the section boundary. Keep that
                    # boundary until page accounting has finished its reflow.
                    if anchor.find(".//" + qn("w:sectPr")) is None:
                        anchor.getparent().remove(anchor)
                else:
                    last.addnext(clone)
                    page_plan.emitted(clone, last, kind="picture")
                last = clone
                caption_index = image_indexes[index] if image_indexes else index
                if caption_index < len(block.asset_captions) and block.asset_captions[caption_index].strip():
                    choices = section_text.get(sec) or global_text
                    caption = deepcopy(choices[0]) if choices else OxmlElement("w:p")
                    for properties in list(caption.iter(qn("w:sectPr"))):
                        properties.getparent().remove(properties)
                    _clear_images(caption)
                    _set_text(caption, block.asset_captions[caption_index])
                    clone.addnext(caption)
                    page_plan.emitted(caption, clone, kind="caption")
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

    contact = next((block for block in draft.blocks if block.key == "contact_matrix"), None)
    if contact is not None and not contact.rows and not any(table.rows for table in contact.extra_tables):
        # An explicitly empty current contact table must not leave an orphan
        # heading below an independently retained chart. Other source tables and
        # any boundary-bearing or emitted table keep their existing page proof.
        for anchor, _ in table_prototypes.get("contact_matrix", ()):
            if (anchor.getparent() is not None and anchor not in page_plan.live
                    and anchor.find(".//" + qn("w:sectPr")) is None):
                anchor.getparent().remove(anchor)

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
        _clear_diagrams(part.element)
        _clear_hyperlinks(part.element)
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
    page_plan.finish(document=document)
    result = BytesIO()
    document.save(result)
    # Prune image relationships which became unused after old payload removal.
    with tempfile.TemporaryDirectory(prefix="native-report-") as folder:
        output = Path(folder) / "report.docx"
        output.write_bytes(result.getvalue())
        return passive_docx(output)
