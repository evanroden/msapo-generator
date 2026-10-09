"""Compatibility for disposable monthly-report conversion copies only."""

from io import BytesIO
import posixpath
from zipfile import ZipFile, is_zipfile

from lxml import etree


_V = "urn:schemas-microsoft-com:vml"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


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


def rendering_docx(raw):
    """Give alpha-PNG VML frames an explicit transparent background.

    Word leaves these image frames transparent; LibreOffice otherwise fills
    their entire rectangle white, hiding native artwork below the PNG shadow.
    Preserve explicit fills, every image byte and all source geometry. Callers
    keep the native downloadable DOCX and write this copy only for conversion.
    """
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
            if _V.encode() not in data:
                continue
            root = etree.fromstring(data, parser)
            shapes = root.findall(".//{" + _V + "}shape")
            relpart = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
            if not shapes or relpart not in names:
                continue
            relationships = {node.get("Id"): node.get("Target", "")
                             for node in etree.fromstring(source.read(relpart), parser)
                             if node.get("TargetMode") != "External"}
            changed = False
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
                    alpha[member] = _transparent_png(source.read(member))
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
