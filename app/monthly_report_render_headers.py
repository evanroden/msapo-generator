"""Reference-proven hidden headers in disposable divider rendering copies."""

from hashlib import sha256
import posixpath
import re

from lxml import etree

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def header_fingerprint(archive, part):
    """Bind visibility evidence to header geometry and the exact image bytes."""
    if not re.fullmatch(r"word/header[0-9]+\.xml", part):
        return None
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(archive.read(part), parser)
        relations = etree.fromstring(archive.read("word/_rels/" + part[5:] + ".rels"), parser)
        targets = {node.get("Id"): node for node in relations}
        anchors = list(root.iter(_WP + "anchor"))
        if not 1 <= len(anchors) <= 8 or root.find(".//" + _WP + "inline") is not None:
            return None
        if any(etree.QName(node).localname in {
            "tbl", "fldChar", "instrText", "object", "pict", "sym", "txbxContent", "textbox",
        } or (etree.QName(node).localname in {"t", "delText"} and (node.text or "").strip())
               for node in root.iter()):
            return None
        images = []
        for anchor in anchors:
            blips = list(anchor.iter(_A + "blip"))
            if len(blips) != 1:
                return None
            rid = blips[0].get(_R + "embed")
            relation = targets.get(rid)
            if (relation is None or relation.get("TargetMode") == "External"
                    or not relation.get("Type", "").endswith("/image")):
                return None
            target = posixpath.normpath(posixpath.join("word", relation.get("Target", "")))
            if not target.startswith("word/media/"):
                return None
            digest = sha256(archive.read(target)).hexdigest()
            images.append(digest)
            blips[0].set(_R + "embed", digest)
        # Native packaging normalizes drawing identifiers, not visible content.
        for node in root.iter():
            if etree.QName(node).localname in {"docPr", "cNvPr"}:
                for key in ("id", "name", "descr"):
                    node.attrib.pop(key, None)
        payload = etree.tostring(root, method="c14n") + "".join(images).encode()
        return sha256(payload).hexdigest()
    except (KeyError, ValueError, etree.XMLSyntaxError):
        return None


def hidden_divider_header_overrides(archive, document, evidence=()):
    """Return header-only replacements after measured companion-PDF approval.

    This does not infer visibility or approve parts. A caller must supply a
    validated measured profile. Shared or inherited content-page headers are
    refused, even if their part was approved for a divider. Body and footer XML,
    relationships, margins, and native downloadable packages remain untouched.
    """
    from app.monthly_report_import import _is_native_divider_background, _text

    if not evidence:
        return {}
    approved = {item.get("part"): item.get("fingerprint") for item in evidence
                if isinstance(item, dict)}
    body = document.find(_W + "body")
    if body is None:
        return {}
    relations = etree.fromstring(archive.read("word/_rels/document.xml.rels"),
                                 etree.XMLParser(resolve_entities=False, no_network=True))
    targets = {node.get("Id"): posixpath.normpath(posixpath.join("word", node.get("Target", "")))
               for node in relations if node.get("TargetMode") != "External"}
    usage, inherited, content = {}, {}, []
    for node in body:
        content.append(node)
        section = node if node.tag == _W + "sectPr" else node.find(_W + "pPr/" + _W + "sectPr")
        if section is None:
            continue
        for header in section.findall(_W + "headerReference"):
            inherited[header.get(_W + "type")] = targets.get(header.get(_R + "id"))
        dividers = [p for p in content if p.tag == _W + "p"
                    and _is_native_divider_background(p, _text(p))]
        dedicated = len(dividers) == 1 and all(
            p is dividers[0] or p.tag == _W + "sectPr"
            or (p.tag == _W + "p" and not _text(p).strip()
                and p.find(".//" + _W + "drawing") is None
                and p.find(".//" + _W + "pict") is None)
            for p in content)
        for part in inherited.values():
            usage.setdefault(part, []).append(dedicated)
        content = []
    replacements = {}
    for part, fingerprint in approved.items():
        if (not isinstance(part, str) or not isinstance(fingerprint, str)
                or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
                or not usage.get(part) or not all(usage[part])
                or header_fingerprint(archive, part) != fingerprint):
            continue
        blank = etree.Element(_W + "hdr", nsmap={"w": _W[1:-1]})
        etree.SubElement(blank, _W + "p")
        replacements[part] = etree.tostring(blank, encoding="UTF-8", xml_declaration=True, standalone=True)
    return replacements
