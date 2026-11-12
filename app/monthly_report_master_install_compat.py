"""Conservative, install-only Word master compatibility preparation.

The uploaded DOCX is never edited. Unknown AlternateContent remains a hard
diagnostic, not an invitation to discard a legacy drawing or its relationships.
Only a paired, recognized modern/legacy representation with matching visible
content and supported geometry can be unwrapped.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import hashlib
import posixpath
import re
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as XML

from app.monthly_report_import import ImportError, _package, _resolve
from app.monthly_report_native_package import _xml
from app.monthly_report_native_design import equivalent_native_alternatives

MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
WPG = "{http://schemas.microsoft.com/office/word/2010/wordprocessingGroup}"
VML = "{urn:schemas-microsoft-com:vml}"
MARKERS = {W + "commentRangeStart", W + "commentRangeEnd", W + "commentReference"}


def _geometry_equivalent(choice, fallback) -> bool:
    """Require matching available width/height, never assume equal art from text."""
    modern_shapes = list(choice.iter(WPS + "wsp")) + list(choice.iter(WPG + "wgp"))
    legacy_shapes = [n for n in fallback.iter() if n.tag in {VML + "shape", VML + "rect"}]
    if not modern_shapes and not legacy_shapes:
        return True  # Text-only equivalent compatibility alternatives.
    if len(modern_shapes) != len(legacy_shapes) or not modern_shapes:
        return False
    modern_extents = list(choice.iter(A + "ext"))
    if len(modern_extents) != len(modern_shapes):
        return False  # Cannot prove the modern shape dimensions.
    for extent, shape in zip(modern_extents, legacy_shapes):
        style = shape.get("style", "")
        width = re.search(r"(?:^|;)\s*width\s*:\s*([\d.]+)pt\b", style, re.I)
        height = re.search(r"(?:^|;)\s*height\s*:\s*([\d.]+)pt\b", style, re.I)
        if width is None or height is None:
            return False
        try:
            sizes = (int(extent.get("cx", "-1")), int(extent.get("cy", "-1")))
            declared = (round(float(width.group(1)) * 12700),
                        round(float(height.group(1)) * 12700))
        except (TypeError, ValueError, OverflowError):
            return False
        if any(a <= 0 or abs(a - b) > 127 for a, b in zip(sizes, declared)):
            return False
    return True


def _image_identity(archive, names, part):
    rel_path = posixpath.join(posixpath.dirname(part), "_rels",
                              posixpath.basename(part) + ".rels")
    relationships = _xml(archive.read(rel_path)) if rel_path in names else ()
    by_id = {}
    for rel in relationships:
        rid = rel.get("Id", "")
        if not rid or rel.get("TargetMode", "").casefold() == "external":
            continue
        target = _resolve(part, rel.get("Target", ""))
        if target in names and rel.get("Type", "").endswith("/image"):
            by_id[rid] = hashlib.sha256(archive.read(target)).hexdigest()
    return by_id.get


def prepare_master_working_copy(source: Path) -> tuple[bytes | None, tuple[str, ...]]:
    """Return a changed DOCX copy, or None if the original needs no normalization.

    The caller persists an immutable original and separately records the working
    hash. This is deliberately not a general-purpose DOCX or comment stripper.
    """
    changes = set()
    with _package(Path(source)) as archive:
        names = set(archive.namelist())
        comments = set()
        if "word/comments.xml" in names:
            root = _xml(archive.read("word/comments.xml"))
            comments = {n.get(W + "id") for n in root.iter(W + "comment")}
        output = {}
        for part in archive.namelist():
            raw = archive.read(part)
            if not (part.startswith("word/") and part.endswith(".xml")
                    and (part == "word/document.xml" or
                         re.fullmatch(r"word/(?:header|footer)\d+\.xml", part) or
                         part in {"word/footnotes.xml", "word/endnotes.xml"})):
                continue
            root = _xml(raw)
            part_changed = False
            identity = _image_identity(archive, names, part)
            for alternate in reversed(list(root.iter(MC + "AlternateContent"))):
                choices = alternate.findall(MC + "Choice")
                fallbacks = alternate.findall(MC + "Fallback")
                if not choices and len(fallbacks) == 1 and len(alternate) == 1:
                    continue  # The fallback is the only available representation.
                if len(choices) != 1 or len(fallbacks) != 1 or len(alternate) != 2:
                    raise ImportError(f"Unsupported Word AlternateContent branches in {part}; keep the original and provide an equivalent modern/legacy drawing.")
                choice, fallback = choices[0], fallbacks[0]
                prefixes = choice.get("Requires", "").split()
                if not prefixes or any(p not in {"wps", "wpg"} for p in prefixes):
                    raise ImportError(f"Unsupported Word AlternateContent choice in {part}; the original was not changed.")
                if any(choice.nsmap.get(p) !=
                       {"wps": WPS[1:-1], "wpg": WPG[1:-1]}[p] for p in prefixes):
                    raise ImportError(f"Unrecognized modern drawing namespace in {part}; the original was not changed.")
                guard = XML.Element(W + "p")
                guard.append(deepcopy(alternate))
                if (not equivalent_native_alternatives(guard, identity)
                        or not _geometry_equivalent(choice, fallback)):
                    raise ImportError(f"Modern/legacy Word drawing differs or has unverified geometry in {part}; export a corrected master with equivalent representations.")
                parent = alternate.getparent()
                if parent is None:
                    raise ImportError(f"Root AlternateContent is unsupported in {part}.")
                index = parent.index(alternate)
                parent.remove(alternate)
                for child in list(choice):
                    parent.insert(index, deepcopy(child))
                    index += 1
                part_changed = True
                changes.add("equivalent_modern_choice")
            for node in list(root.iter()):
                if node.tag in MARKERS and node.get(W + "id") not in comments:
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                        part_changed = True
                        changes.add("orphan_comment_marker")
            if part_changed:
                output[part] = XML.tostring(root, encoding="UTF-8",
                                            xml_declaration=True, standalone=True)
        if not output:
            return None, ()
        buffer = BytesIO()
        with ZipFile(buffer, "w", ZIP_DEFLATED) as written:
            for info in archive.infolist():
                written.writestr(info, output.get(info.filename, archive.read(info.filename)))
        return buffer.getvalue(), tuple(sorted(changes))
