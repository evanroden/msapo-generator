"""Narrow floating-frame compatibility for disposable conversion copies."""

from lxml import etree

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WPS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
_NS = {"w": _W, "wp": _WP, "a": _A, "wps": _WPS}


def _negative_picture(anchor):
    position = anchor.find("wp:positionV", _NS)
    offset = position.find("wp:posOffset", _NS) if position is not None else None
    if position is None or position.get("relativeFrom") != "paragraph" or offset is None:
        return False
    try:
        negative = int(offset.text or "0") < 0
    except ValueError:
        return False
    return negative and bool(anchor.findall(".//a:blip", _NS))


def _invisible_empty_shape(anchor):
    shape = anchor.find("a:graphic/a:graphicData/wps:wsp", _NS)
    if shape is None or any((node.text or "").strip() for node in shape.iter()
                            if etree.QName(node).localname in {"t", "instrText", "delText"}):
        return False
    # Only a simple rectangle without any embedded content or visible effects.
    if any(etree.QName(node).localname in {
        "blip", "imagedata", "object", "OLEObject", "fldChar", "sym", "drawing", "pict",
    } for node in shape.iter()):
        return False
    properties = shape.find("wps:spPr", _NS)
    if properties is None or properties.find("a:noFill", _NS) is None:
        return False
    geometry = properties.find("a:prstGeom", _NS)
    if geometry is None or geometry.get("prst") != "rect":
        return False
    if any(etree.QName(child).localname not in {"xfrm", "prstGeom", "noFill", "ln", "effectLst"}
           for child in properties):
        return False
    effects = properties.find("a:effectLst", _NS)
    if effects is not None and len(effects):
        return False
    line = properties.find("a:ln", _NS)
    if line is None:
        return False  # An omitted line can inherit visible theme styling.
    if line.find("a:noFill", _NS) is not None:
        return True
    fills = line.findall("a:solidFill", _NS)
    if len(fills) != 1 or len(fills[0]) != 1:
        return False
    alpha = fills[0][0].find("a:alpha", _NS)
    return (alpha is not None and alpha.get("val") == "0"
            and not any(etree.QName(node).localname in {"alphaMod", "alphaOff"}
                        for node in fills[0].iter()))


def normalize_invisible_wraps(root):
    """Disable a proven Writer collision without moving or deleting any artwork.

    A fully invisible empty rectangle sharing a paragraph with an upward-offset
    picture can move that entire anchor paragraph to the next page in Writer.
    The picture then clips above the page. Word keeps the composition together.
    Only this observed structure is normalized; ordinary spacers, visible shapes,
    image bytes, text, and anchor coordinates are retained. Native downloads must
    never call this helper: it mutates a disposable conversion XML tree only.
    """
    changed = False
    for paragraph in root.findall(".//w:p", _NS):
        anchors = [anchor for anchor in paragraph.findall(".//wp:anchor", _NS)
                   if next(anchor.iterancestors("{" + _W + "}p"), None) is paragraph]
        if not any(_negative_picture(anchor) for anchor in anchors):
            continue
        for anchor in anchors:
            wrap = anchor.find("wp:wrapTopAndBottom", _NS)
            if wrap is not None and _invisible_empty_shape(anchor):
                wrap.tag = "{" + _WP + "}wrapNone"
                changed = True
    return changed


def normalize_divider_wraps(root):
    """Keep native full-page divider artwork from reserving flowing-text space."""
    from app.monthly_report_import import _is_native_divider_background, _text

    changed = False
    for paragraph in root.findall(".//w:p", _NS):
        if not _is_native_divider_background(paragraph, _text(paragraph)):
            continue
        for anchor in paragraph.findall(".//wp:anchor", _NS):
            position = anchor.find("wp:positionV", _NS)
            extent = anchor.find("wp:extent", _NS)
            wrap = anchor.find("wp:wrapTopAndBottom", _NS)
            if (position is None or position.get("relativeFrom") != "page"
                    or extent is None or wrap is None
                    or not anchor.findall(".//a:blip", _NS)):
                continue
            try:
                large = int(extent.get("cx", "0")) > 6_000_000 and int(extent.get("cy", "0")) > 6_000_000
            except ValueError:
                continue
            if large:
                wrap.tag = "{" + _WP + "}wrapNone"
                changed = True
    return changed
