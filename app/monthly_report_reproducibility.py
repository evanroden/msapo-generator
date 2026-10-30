"""Deterministic Monthly assembly evidence, separate from optional interpretation.

These helpers inspect accepted canonical draft values and a *generated* DOCX.
They never parse sources, run AI/OCR, approve draft decisions, create shared
history, or alter assembly. The output manifest ignores volatile ZIP metadata,
relationship IDs and package timestamps but preserves ordered text, tables,
section boundaries, images and meaningful image geometry.
"""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import posixpath
import re
from zipfile import ZipFile, BadZipFile

from defusedxml import ElementTree as ET

from app.monthly_report_model import (
    COVER_ASSET_KEYS, included_sections, used_asset_references,
    used_source_ids,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
VML = "{urn:schemas-microsoft-com:vml}"
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_PACKAGE_BYTES = 200 * 1024 * 1024


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def _file_sha256(path):
    with Path(path).open("rb") as stream:
        from hashlib import file_digest
        return file_digest(stream, "sha256").hexdigest()


def _design_pin(profile):
    """Fingerprints *actual* pinned design bytes, not only the design label."""
    from app.monthly_report_designs import source_for, fingerprint
    from app.monthly_report_docx import SHELL_PATH
    source = source_for(profile)
    chosen = Path(source) if source is not None else Path(SHELL_PATH)
    return {
        "kind": "pinned_native" if source is not None else "generic_shell",
        "reference": fingerprint(profile),
        "template_key": profile.template,
        "bytes_sha256": _file_sha256(chosen),
    }


def canonical_input_manifest(draft, *, asset_loader=None):
    """Snapshot only report-selected content and its underlying source identities.

    Suggested/inferred *source* text is never considered an accepted report
    block. Deliberate exclusions stay exclusions; unrelated saved sources are
    not silently promoted into report facts. Each included section's ordered
    block data is included without replacing zeros, blanks or narrative text.
    """
    sections = included_sections(draft.sections)
    blocks = {item.key: item for item in draft.blocks}
    source_ids = used_source_ids(draft)
    used_assets = used_asset_references(draft)

    def visible_block(key):
        block = blocks.get(key)
        return asdict(block) if block is not None and block.source != "Omit" else None

    manifest = {
        "schema": 1,
        "profile": {
            "contract": draft.profile.contract,
            "key": draft.profile.key,
            "title": draft.profile.title,
            "facilities": [asdict(v) for v in draft.profile.facilities],
            "scope": draft.profile.scope_type,
        },
        "period": draft.period.key,
        "prepared_by": draft.prepared_by,
        "address": draft.address_line,
        "design": _design_pin(draft.profile),
        "cover": [(key, visible_block(key)) for key in
                  (*sorted(COVER_ASSET_KEYS), "footer_text")],
        "sections": [{
            "key": s.key, "number": s.number, "title": s.title,
            "appendix": s.appendix, "divider_asset": s.divider_asset,
            "divider": visible_block("divider_" + s.key),
            "blocks": [
                (spec.key, spec.type, asdict(spec), visible_block(spec.key))
                for spec in s.blocks
            ],
        } for s in sections],
        "followups": [asdict(item) for item in draft.follow_ups if item.included],
        "sources": [
            (s.id, s.sha256, s.fingerprint)
            for s in draft.sources if s.id in source_ids
        ],
        "assets": [
            (ref, sha256(asset_loader(ref)).hexdigest() if asset_loader else None)
            for ref in sorted(used_assets)
        ],
        "synthetic": draft.synthetic,
    }
    return {"sha256": _digest(manifest), "manifest": manifest}


def _text(node):
    parts = []
    for child in node.iter():
        if child.tag in (W + "t", A + "t"):
            parts.append(child.text or "")
        elif child.tag == W + "tab":
            parts.append("\t")
        elif child.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts)


def _relationships(package, part, names):
    """Resolve only bundled images; never dereference external relationships."""
    directory, filename = posixpath.split(part)
    relpath = posixpath.join(directory, "_rels", filename + ".rels")
    if relpath not in names:
        return {}
    if package.getinfo(relpath).file_size > MAX_XML_BYTES:
        raise ValueError("DOCX relationships exceed the reproducibility budget.")
    links = {}
    for rel in ET.fromstring(package.read(relpath)):
        if rel.tag != PKGREL + "Relationship":
            continue
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            links[rid] = "external"  # never fetch a URL
            continue
        if not target or target.startswith("/"):
            links[rid] = "unresolved"
            continue
        normalized = posixpath.normpath(posixpath.join(directory, target))
        if not normalized.startswith("word/media/") or normalized not in names:
            links[rid] = "non_media"
            continue
        size = package.getinfo(normalized).file_size
        if size > MAX_PACKAGE_BYTES:
            raise ValueError("DOCX image exceeds the reproducibility budget.")
        links[rid] = sha256(package.read(normalized)).hexdigest()
    return links


def _pictures(node, links):
    result = []
    for item in node.iter():
        if item.tag in (A + "blip", VML + "imagedata"):
            rid = item.get(R + "embed") or item.get(R + "id") or item.get(R + "link")
            result.append(links.get(rid, "unresolved"))
    return tuple(result)


def _paragraph(node, links):
    style = node.find(W + "pPr/" + W + "pStyle")
    breaks = sum(child.get(W + "type") == "page"
                 for child in node.iter(W + "br"))
    sizes = tuple((item.get("cx"), item.get("cy"))
                  for item in node.iter(WP + "extent"))
    # A page/section boundary is placement semantics even when text is empty.
    return ("p", _text(node), style.get(W + "val", "") if style is not None else "",
            breaks, node.find(".//" + W + "sectPr") is not None,
            _pictures(node, links), sizes)


def _table(node, links):
    rows = []
    for row in node.findall(W + "tr"):
        cells = []
        for cell in row.findall(W + "tc"):
            properties = cell.find(W + "tcPr")
            span = properties.find(W + "gridSpan") if properties is not None else None
            merge = properties.find(W + "vMerge") if properties is not None else None
            cells.append((
                _text(cell),
                span.get(W + "val", "1") if span is not None else "1",
                merge.get(W + "val", "continue") if merge is not None else "",
                _pictures(cell, links),
            ))
        rows.append(tuple(cells))
    return ("tbl", tuple(rows))


def _story(node, links):
    result = []
    for child in node:
        if child.tag == W + "p":
            result.append(_paragraph(child, links))
        elif child.tag == W + "tbl":
            result.append(_table(child, links))
        elif child.tag == W + "sectPr":
            result.append(("end_section",))
    return tuple(result)


def canonical_docx_manifest(data: bytes):
    """Compare Word content/placement rather than unstable ZIP byte identity."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_PACKAGE_BYTES:
        raise ValueError("Choose one bounded generated Word package.")
    try:
        with ZipFile(BytesIO(data)) as package:
            names = set(package.namelist())
            if "word/document.xml" not in names:
                raise ValueError("Generated Word package has no document body.")
            parts = ["word/document.xml", *sorted(
                name for name in names
                if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
            )]
            stories = []
            for part in parts:
                if package.getinfo(part).file_size > MAX_XML_BYTES:
                    raise ValueError("Word content exceeds the reproducibility budget.")
                root = ET.fromstring(package.read(part))
                story = root.find(W + "body") if part == "word/document.xml" else root
                if story is None:
                    raise ValueError("Generated Word package has no document body.")
                stories.append((part, _story(story, _relationships(package, part, names))))
            media = tuple(sorted(
                sha256(package.read(name)).hexdigest()
                for name in names if name.startswith("word/media/") and not name.endswith("/")
            ))
    except (BadZipFile, OSError, ET.ParseError) as exc:
        raise ValueError("Generated Word package cannot be inspected safely.") from exc
    manifest = {"schema": 1, "stories": stories, "media_sha256": media}
    return {"sha256": _digest(manifest), "manifest": manifest}


def verify_repeated_assembly(draft, *, asset_loader=None):
    """Two gated Word assemblies; leave normal single-pass generation unchanged.

    This is a test/diagnostic helper, not an alternative export or save path.
    A volatile core-property timestamp may differ between Word packages, but
    ordered visible content, page breaks, native tables and pictures must not.
    """
    from app.monthly_report_docx import assemble_docx
    before = canonical_input_manifest(draft, asset_loader=asset_loader)
    first = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                          asset_loader=asset_loader)
    second = assemble_docx(draft, acknowledged_fingerprint=draft.fingerprint,
                           asset_loader=asset_loader)
    after = canonical_input_manifest(draft, asset_loader=asset_loader)
    if before["sha256"] != after["sha256"]:
        raise ValueError("Canonical report data or pinned template changed during assembly.")
    one, two = canonical_docx_manifest(first), canonical_docx_manifest(second)
    if one["sha256"] != two["sha256"]:
        raise ValueError("Identical accepted report data generated different Word content.")
    return {
        "input_sha256": before["sha256"],
        "docx_content_sha256": one["sha256"],
        "same_package_bytes": first == second,
        "sections": tuple((section["key"], section["number"])
                          for section in before["manifest"]["sections"]),
    }
