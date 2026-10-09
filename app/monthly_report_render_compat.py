"""Compatibility for disposable monthly-report conversion copies only."""

from io import BytesIO
from copy import deepcopy
import posixpath
from zipfile import ZipFile, is_zipfile

from lxml import etree

from app.monthly_report_render_wrap import normalize_divider_wraps, normalize_invisible_wraps
from app.monthly_report_render_profile import validate_profile
from app.monthly_report_cover_metrics import apply_cover_metrics


_V = "urn:schemas-microsoft-com:vml"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"


def _divider_text_fill(root):
    """Bridge verified white divider fills to Writer's ordinary text color."""
    changed = False
    for style in root.findall(_W + "style"):
        if style.get(_W + "styleId") not in {"Divider", "DividerChar"}:
            continue
        properties = style.find(_W + "rPr")
        if properties is None:
            continue
        fill = properties.find(_W14 + "textFill/" + _W14 + "solidFill/" + _W14 + "srgbClr")
        color = properties.find(_W + "color")
        if (fill is None or len(fill) or fill.get(_W14 + "val") != "FFFFFF"
                or (color is not None and dict(color.attrib) != {_W + "val": "auto"})):
            continue
        if color is None:
            color = etree.Element(_W + "color")
            properties.insert(0, color)
        color.set(_W + "val", "FFFFFF")
        changed = True
    return changed


def _floating_cover_header(root):
    """Avoid Writer reserving a nonexistent first-page header on a cover."""
    body = root.find(_W + "body")
    if body is None:
        return False
    cover = []
    first = None
    for paragraph in body:
        if paragraph.tag == _W + "sectPr" and cover:
            first = paragraph
            break
        if paragraph.tag != _W + "p" or len(cover) == 3:
            return False
        cover.append(paragraph)
        first = paragraph.find(".//" + _W + "sectPr")
        if first is not None:
            break
    if first is None:
        return False
    cover_text = " ".join(" ".join((node.text or "") for node in p.iter(_W + "t"))
                          for p in cover).casefold()
    cover_text = " ".join(cover_text.split())
    if ("operations and maintenance monthly review" not in cover_text
            and not ("monthly report" in cover_text and "prepared by" in cover_text)):
        return False
    title = first.find(_W + "titlePg")
    margins = first.find(_W + "pgMar")
    headers = first.findall(_W + "headerReference")
    if (title is None or title.get(_W + "val") in {"0", "false", "off"}
            or margins is None or margins.get(_W + "top") != "0"
            or margins.get(_W + "bottom") != "0"
            or not headers or any(h.get(_W + "type") == "first" for h in headers)
            or first.find(_W + "footerReference") is not None):
        return False
    if any("".join(p.xpath("./w:r/w:t/text()", namespaces={"w": _W[1:-1]})).strip()
           not in {"", "="} for p in cover):
        return False
    if any(p.find(".//" + _WP + "inline") is not None for p in cover):
        return False
    if not any(anchor.find(_WP + "positionV") is not None
               and anchor.find(_WP + "positionV").get("relativeFrom") == "paragraph"
               for p in cover for anchor in p.iter(_WP + "anchor")):
        return False
    sections = list(body.iter(_W + "sectPr"))
    # Removing the cover reference must not remove inherited later headers.
    following = sections[1] if len(sections) > 1 else None
    for header in headers:
        if following is not None and not any(h.get(_W + "type") == header.get(_W + "type")
                                            for h in following.findall(_W + "headerReference")):
            following.insert(0, deepcopy(header))
        first.remove(header)
    first.remove(title)
    margins.set(_W + "header", "0")
    return True


def _transparent_png(raw):
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) < 26:
        return False
    if raw[25] in (4, 6):
        return True
    offset = 8
    while offset + 12 <= len(raw):
        size = int.from_bytes(raw[offset:offset + 4], "big")
        kind = raw[offset + 4:offset + 8]
        if kind == b"tRNS":
            return True
        if kind == b"IDAT":
            return False
        offset += size + 12
    return False


def rendering_docx(raw, *, profile=None):
    """Apply proven compatibility fixes to a disposable conversion copy.

    Word leaves these image frames transparent; LibreOffice otherwise fills
    their entire rectangle white, hiding native artwork below the PNG shadow.
    Also normalize the scoped invisible wrapping-frame collision. Preserve
    explicit fills, every image byte and all source geometry. Callers
    keep the native downloadable DOCX and write this copy only for conversion.
    """
    profile = validate_profile(profile)
    if not is_zipfile(BytesIO(raw)):
        return raw
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    changes = {}
    with ZipFile(BytesIO(raw)) as source:
        names = set(source.namelist())
        alpha = {}
        for part in names:
            if not part.startswith("word/") or not part.endswith(".xml"):
                continue
            data = source.read(part)
            color_styles = part == "word/styles.xml" and profile.get("divider_white_text", False)
            if part != "word/document.xml" and not color_styles and _V.encode() not in data:
                continue
            root = etree.fromstring(data, parser)
            changed = part == "word/document.xml" and normalize_invisible_wraps(root)
            if color_styles:
                changed = _divider_text_fill(root) or changed
            if part == "word/document.xml":
                changed = apply_cover_metrics(root, profile.get("cover_metrics", [])) or changed
                if profile.get("divider_wrap_none", False):
                    changed = normalize_divider_wraps(root) or changed
                if profile["cover_zero_origin"]:
                    changed = _floating_cover_header(root) or changed
            shapes = root.findall(".//{" + _V + "}shape")
            relpart = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            relationships = {node.get("Id"): node.get("Target", "")
                             for node in (etree.fromstring(source.read(relpart), parser)
                                          if relpart in names else ())
                             if node.get("TargetMode") != "External"}
            for shape in shapes:
                picture = shape.find("{" + _V + "}imagedata")
                if (picture is None or shape.get("filled") is not None
                        or shape.get("fillcolor") is not None
                        or shape.find("{" + _V + "}fill") is not None):
                    continue
                target = relationships.get(picture.get("{" + _R + "}id"), "")
                member = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
                if not target or member not in names:
                    continue
                if member not in alpha:
                    # Large report photos need no decoding or full read here.
                    with source.open(member) as image:
                        header = image.read(26)
                    alpha[member] = (_transparent_png(header) or
                                    (header.startswith(b"\x89PNG\r\n\x1a\n")
                                     and _transparent_png(source.read(member))))
                if not alpha[member]:
                    continue
                shape.set("filled", "f")
                if (shape.get("stroked") is None and shape.get("strokecolor") is None
                        and shape.find("{" + _V + "}stroke") is None):
                    shape.set("stroked", "f")
                changed = True
            if changed:
                changes[part] = etree.tostring(root, encoding="UTF-8", xml_declaration=True, standalone=True)
        if not changes:
            return raw
        output = BytesIO()
        with ZipFile(output, "w") as destination:
            for info in source.infolist():
                destination.writestr(info, changes.get(info.filename, source.read(info.filename)))
    return output.getvalue()
