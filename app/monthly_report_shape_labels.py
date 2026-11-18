"""Read-only source-region evidence for floating Word text and drawing labels.

These observations are NOT an editable reconstruction, OCR, a physical page
number, or permission to publish artwork. They are tied to an original DOCX
inspection item and retain the exact source part and body-unit ordinal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
WPG = "{http://schemas.microsoft.com/office/word/2010/wordprocessingGroup}"
MAX_LABELS_PER_UNIT = 128
MAX_LABEL_CHARS = 16_000


@dataclass(frozen=True)
class DrawingLabel:
    # Exact readable source text (or descriptive metadata, never called OCR).
    text: str
    source: str                 # word_text, drawing_text or alternative_text
    object_type: str
    artwork_relationship: str
    region: str                 # an XML unit + approximate anchor, NOT page
    confidence: str             # high, medium or metadata
    native_reference: str       # source occurrence; original bytes are retained


def _value(box, tag):
    return "".join(node.text or "" for node in box.iter(tag))


def _box_text(box):
    parts = []
    for node in box.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in (W + "tab",):
            parts.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif node.tag == W + "p" and parts and parts[-1] != "\n":
            parts.append("\n")
    return "".join(parts).strip()


def _ancestor(node, parents, tags):
    while node in parents:
        node = parents[node]
        if node.tag in tags:
            return node
    return None


def _dimension(raw):
    try:
        value = int(raw)
        return f"{value / 914400:.2f} in" if abs(value) < 100_000_000 else ""
    except (TypeError, ValueError):
        return ""


def _anchor_region(node, parents):
    """Geometry is a hint within a Word unit, not a rendered-page coordinate."""
    anchor = _ancestor(node, parents, {WP + "anchor", WP + "inline"})
    if anchor is not None:
        position = "floating anchor" if anchor.tag == WP + "anchor" else "inline drawing"
        if anchor.tag == WP + "anchor":
            offsets = []
            for axis, tag in (("horizontal", WP + "positionH"), ("vertical", WP + "positionV")):
                placed = anchor.find(tag)
                offset = placed.find(WP + "posOffset") if placed is not None else None
                value = _dimension(offset.text) if offset is not None else ""
                if value:
                    offsets.append(f"{axis} {value} from {placed.get('relativeFrom', 'unspecified')}")
            if offsets:
                position += " (" + "; ".join(offsets) + ")"
        return position
    shape = _ancestor(node, parents, {V + "shape", V + "rect", V + "roundrect"})
    if shape is not None:
        style = shape.get("style", "")
        offsets = []
        for axis in ("left", "top"):
            match = re.search(r"(?:^|;)\s*" + axis + r"\s*:\s*(-?\d+(?:\.\d+)?(?:pt|in))\b", style, re.I)
            if match:
                offsets.append(axis + " " + match.group(1))
        return "VML frame" + (" (" + "; ".join(offsets) + ")" if offsets else " (position unspecified)")
    return "position unspecified"


def collect_drawing_labels(element, *, part, position, word_section):
    """Find each text-bearing shape without flattening it into an editable table.

    Alt-text is explicitly metadata, not a verified rendered label. SmartArt
    data outside this XML unit is not guessed; its own guarded reader decides
    whether a diagram is provably complete. Duplicated Choice/Fallback branches
    must be normalized by the caller before invoking this function.
    """
    parents = {child: parent for parent in element.iter() for child in parent}
    labels = []
    inspected = set()
    units = f"{part} · element {position}"
    if part == "word/document.xml":
        units += f" · Word section {word_section} (not physical page)"
    elif part.startswith("word/header"):
        units += " · header"
    elif part.startswith("word/footer"):
        units += " · footer"

    def record(text, source, object_type, node, relation, confidence):
        if not text:
            return
        if len(text) > MAX_LABEL_CHARS or len(labels) >= MAX_LABELS_PER_UNIT:
            raise ValueError("Text-bearing Word drawing exceeds the bounded label inventory.")
        idx = len(labels) + 1
        labels.append(DrawingLabel(
            text=text, source=source, object_type=object_type,
            artwork_relationship=relation,
            region=units + " · " + _anchor_region(node, parents),
            confidence=confidence,
            native_reference=f"{part}#unit-{position}/label-{idx}",
        ))

    for box in element.iter(W + "txbxContent"):
        parent = _ancestor(box, parents, {V + "textbox", WPS + "txbx", WPS + "wsp"})
        vml_shape = _ancestor(box, parents, {V + "shape", V + "rect", V + "roundrect"})
        group = _ancestor(box, parents, {V + "group", WPG + "wgp"})
        kind = ("VML text box" if vml_shape is not None
                else "DrawingML text box" if parent is not None and parent.tag in (WPS + "txbx", WPS + "wsp")
                else "Word text frame")
        relation = ("grouped drawing" if group is not None else "standalone shape")
        record(_box_text(box), "word_text", kind, box, relation, "high")
        inspected.update(n for n in box.iter() if n.tag in (W + "t", A + "t"))

    # DrawingML labels that Word emits as a:t rather than w:txbxContent.
    # Do not treat arbitrary DrawingML values outside a shape as visible.
    for value in element.iter(A + "t"):
        if value in inspected or not (value.text or "").strip():
            continue
        shape = _ancestor(value, parents, {WPS + "wsp", WPG + "wgp"})
        graphic = _ancestor(value, parents, {A + "graphicData"})
        if shape is None or graphic is None:
            continue
        group = _ancestor(value, parents, {WPG + "wgp"})
        record(value.text or "", "drawing_text", "DrawingML shape label", value,
               "grouped drawing" if group is not None else "standalone shape",
               "medium")

    # A descriptive docPr/title is useful review context, but not visual text.
    # Do not duplicate normal images' existing explicit-role handling.
    if any(node.tag == W + "txbxContent" for node in element.iter()) or any(
        node.tag == A + "graphicData" and not node.get("uri", "").endswith("/picture")
        for node in element.iter()
    ):
        for descriptor in element.iter():
            if descriptor.tag.rsplit("}", 1)[-1] not in ("docPr", "cNvPr"):
                continue
            # A sibling picture in the same Word paragraph has its own
            # picture/alt-text inventory. Do not misattribute its description
            # to an unrelated floating text frame.
            owner = _ancestor(descriptor, parents, {
                WP + "anchor", WP + "inline", WPS + "wsp", WPG + "wgp"
            })
            if owner is None or not (
                any(node.tag == W + "txbxContent" for node in owner.iter())
                or any(node.tag == A + "graphicData"
                       and not node.get("uri", "").endswith("/picture")
                       for node in owner.iter())
            ):
                continue
            for attribute in ("descr", "title"):
                label = descriptor.get(attribute, "").strip()
                if label:
                    record(label, "alternative_text", "drawing description", descriptor,
                           "source metadata (not verified visible)", "metadata")
    return tuple(labels)


def source_review_lines(item):
    """Display-only evidence; this never changes export mappings or approval."""
    labels = getattr(item, "drawing_labels", ())
    if not labels:
        return ()
    lines = []
    for label in labels:
        source = "Word text box value (display unverified)" if label.source == "word_text" else (
            "DrawingML label (layout unverified)" if label.source == "drawing_text"
            else "Alternative text (not proven visible)")
        lines.append(
            f"{label.native_reference} · {source} · {label.object_type} · "
            f"{label.artwork_relationship} · {label.region} · confidence: {label.confidence}\n"
            f"Exact source label: {label.text}"
        )
    return tuple(lines)
