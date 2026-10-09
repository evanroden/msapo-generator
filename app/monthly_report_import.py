"""Bounded, local DOCX inspection. Imported content never executes or fetches.

Read one XML part/body element or selected image at a time. A Word section is
not a report section: headings, text boxes and section breaks are all retained
as context, and destinations remain suggestions until an operator confirms.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from PIL import Image, UnidentifiedImageError

from app.monthly_report_docx import normalize_report_image
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock,
    default_sections, layout_blocks, profile_sections,
)


MAX_DOCX_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
MAX_XML_TOTAL = 64 * 1024 * 1024
MAX_ITEMS = 6000
MAX_TEXT = 2_000_000
MAX_CELLS = 100_000
MAX_NORMALIZED_BYTES = 60 * 1024 * 1024
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
V = "{urn:schemas-microsoft-com:vml}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
RASTER = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}


class ImportError(ValueError):
    """A bounded, operator-visible import failure."""


@dataclass(frozen=True)
class ImportItem:
    id: str
    kind: str
    part: str
    position: int
    word_section: int
    section: str = ""
    suggested_slot: str = ""
    text: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    image_part: str = ""
    note: str = ""
    image_width: int = 0
    image_height: int = 0
    image_digest: str = ""

    @property
    def label(self) -> str:
        detail = self.text.replace("\n", " ")[:90] or self.image_part or self.note
        return f"{self.id} · {self.kind} · {detail}"


@dataclass(frozen=True)
class DocxInspection:
    sha256: str
    items: tuple[ImportItem, ...]
    title_candidates: tuple[str, ...]
    notices: tuple[str, ...]
    word_sections: int


@dataclass(frozen=True)
class ImportMapping:
    item_id: str
    slot: str
    # Explicit source column indices; no guessed truncation into template tables.
    columns: tuple[int, ...] = ()
    first_row_header: bool = True


@dataclass(frozen=True)
class MappedImport:
    blocks: tuple[ResolvedBlock, ...]
    overrides: tuple[BlockSpec, ...]
    assets: tuple[tuple[str, bytes], ...]
    mapped_ids: tuple[str, ...]


def _package(path: Path) -> ZipFile:
    if path.stat().st_size > MAX_DOCX_BYTES:
        raise ImportError("DOCX exceeds the 128 MB import limit. Split the source document and retry.")
    try:
        archive = ZipFile(path)
        members = archive.infolist()
        names = [m.filename for m in members]
        if len(names) > 4000 or len(names) != len(set(names)):
            raise ImportError("The DOCX contains too many or duplicate package parts.")
        if any(n.startswith("/") or "\\" in n or ".." in n.split("/") for n in names):
            raise ImportError("The DOCX contains an unsafe package path.")
        if sum(m.file_size for m in members) > MAX_EXPANDED_BYTES:
            raise ImportError("Expanded DOCX exceeds 256 MB. Split it before importing.")
        if any(m.file_size > MAX_MEMBER_BYTES or m.flag_bits & 1 for m in members):
            raise ImportError("The DOCX contains an oversized or encrypted part.")
        xml = [m for m in members if m.filename.endswith((".xml", ".rels"))]
        if any(m.file_size > MAX_XML_BYTES for m in xml) or sum(m.file_size for m in xml) > MAX_XML_TOTAL:
            raise ImportError("DOCX XML exceeds the safe parsing budget.")
        if "word/document.xml" not in names or "[Content_Types].xml" not in names:
            raise ImportError("Choose a valid Word DOCX document.")
        return archive
    except Exception:
        if "archive" in locals():
            archive.close()
        raise


def _resolve(part: str, target: str) -> str:
    decoded = unquote(target)
    url = urlsplit(decoded)
    if url.scheme or url.netloc or url.query or url.fragment or "\\" in decoded or "\x00" in decoded:
        return ""
    resolved = posixpath.normpath(decoded.lstrip("/") if decoded.startswith("/")
                                  else posixpath.join(posixpath.dirname(part), decoded))
    return resolved if not resolved.startswith(("../", "/")) and resolved != ".." else ""


def _relations(archive: ZipFile, part: str) -> dict[str, tuple[str, str]]:
    name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if name not in archive.namelist():
        return {}
    with archive.open(name) as source:
        root = ET.parse(source, forbid_dtd=True).getroot()
    result = {}
    for rel in root:
        identity = rel.get("Id", "")
        if identity in result:
            raise ImportError("Duplicate relationship identity in DOCX.")
        target = "" if rel.get("TargetMode", "").lower() == "external" else _resolve(part, rel.get("Target", ""))
        result[identity] = (target, rel.get("Type", ""))
    return result


def _visible(element) -> None:
    # Word emits the same drawing twice: modern Choice and legacy Fallback.
    # Prefer the first Choice; keep Fallback when it is the only representation.
    for parent in list(element.iter()):
        if parent.tag == MC + "AlternateContent":
            selected = next((c for c in parent if c.tag == MC + "Choice"), None)
            if selected is None:
                selected = next((c for c in parent if c.tag == MC + "Fallback"), None)
            for child in list(parent):
                if child is not selected:
                    parent.remove(child)
        for child in list(parent):
            if child.tag == W + "del":
                parent.remove(child)


def _text(element) -> str:
    parts = []
    for node in element.iter():
        if node.tag == W + "p" and parts and parts[-1] != "\n":
            parts.append("\n")
        elif node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
        elif node.tag == W + "tab":
            parts.append("\t")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parts).splitlines() if line.strip())


_SECTION_TERMS = {
    "organization": ("organizationalchart", "organizationalstructure"),
    "activity": ("monthlyactivitysummary", "activitysummary"),
    "scorecards": ("monthlyscorecards",), "mbcx": ("mbcxreports",),
    "maintenance": ("maintenanceschedule", "inhousemaintenance"),
    "subcontractors": ("subcontractorstatus",), "water": ("watertreatmentreports",),
    "issues": ("equipmentperformanceissues",), "capital": ("prioritycapitalrenewallist",),
    "proposals": ("pendingdeclinedproposals", "pendinganddeclinedproposals"),
    "training": ("trainingsummary",), "rfi": ("rfimatrix",),
}


def _heading(text: str) -> str | None:
    compact = re.sub(r"[^a-z]", "", text.casefold())
    if "tableofcontents" in compact or text.casefold().count("section") > 2 or len(text) > 250:
        return None
    if re.fullmatch(r"(?:section\s*)?\d*[.\s:–-]*water\s+treatment(?:\s+reports?)?", text.strip(), re.I):
        return "water"
    hits = [key for key, terms in _SECTION_TERMS.items() if any(term in compact for term in terms)]
    if len(hits) == 1:
        return hits[0]
    # Unknown numbered headings and common extra sections must not inherit the
    # previous recognized destination (e.g. AR tables becoming capital costs).
    if ((re.match(r"^(?:section\s+)?\d+[.:\s]+[A-Z]", text, re.I) and text.upper() == text)
            or any(term in compact for term in ("accountsreceivable", "accountreceivable", "plumbingandelectricalallowance"))):
        return "unmatched"
    return None


def _suggest(kind: str, text: str, section: str, *, heading: bool = False, part: str = "") -> str:
    compact = re.sub(r"[^a-z]", "", text.casefold())
    if kind == "image":
        if part.startswith("word/header"):
            return "brand_logo"
        if heading and section not in ("", "unmatched"):
            return "divider_" + section
        for term, slot in (("afterhours", "after_hours_workflow"), ("businesshours", "business_hours_workflow"), ("contact", "contact_matrix")):
            if term in compact:
                return slot
        return {"organization": "org_chart", "activity": "improvements", "mbcx": "mbcx_report",
                "maintenance": "vendor_reports", "water": "water_reports"}.get(section, "cover_photo" if not section else "")
    if kind == "table":
        if section in ("", "unmatched"):
            return ""
        return {"organization": "contact_matrix", "activity": "work_orders", "scorecards": "thermal_capacity",
                "maintenance": "service_calls", "subcontractors": "subcontractor_matrix", "capital": "capital_renewal",
                "proposals": "proposals", "rfi": "rfi_matrix"}.get(section, "")
    if heading:
        return ""
    if part.startswith("word/footer"):
        return "footer_text"
    return {"activity": "activity_summary", "scorecards": "utility_analysis", "issues": "equipment_issues",
            "training": "training_summary"}.get(section, "")


def _is_native_divider_background(element, text=""):
    """Recognize ENFRA's geometric divider, never an ordinary full-page photo.

    Geometry alone is insufficient: a vendor scan can also fill a page. Native
    dividers carry the lime/green shape palette and only a heading or numerals.
    """
    remaining = re.sub(r"[^a-z]", "", text.casefold())
    for term in sorted({term for terms in _SECTION_TERMS.values() for term in terms}, key=len, reverse=True):
        remaining = remaining.replace(term, "")
    if remaining.replace("section", ""):
        return False
    colors = {node.get("val", "").casefold() for node in element.iter(A + "srgbClr")}
    for node in element.iter():
        fill = node.get("fillcolor", "").lower()
        colors.update(re.findall(r"#([0-9a-f]{6})", fill))
    if not colors.intersection({"d6ef4b", "d5ee4a"}) or not colors.intersection({"547e7e", "557f7f"}):
        return False
    wp = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
    return any(extent is not None and int(extent.get("cx", "0")) > 6_000_000
               and int(extent.get("cy", "0")) > 6_000_000
               and any(node.tag == A + "blip" for node in anchor.iter())
               for anchor in element.iter(wp + "anchor")
               for extent in (anchor.find(wp + "extent"),))


def inspect_docx(path: Path) -> DocxInspection:
    """No python-docx object model or whole-archive extraction for large inputs."""
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        for chunk in iter(lambda: raw.read(1024 * 1024), b""):
            digest.update(chunk)
    items, titles, notices = [], [], []
    background_positions = []
    content_slot = ""
    note_owners = {}
    word_section, section, text_total, cell_total = 1, "", 0, 0
    toc_section = 0
    toc_headings = set()

    def add(kind, part, position, **kwargs):
        nonlocal text_total, cell_total
        text_total += len(kwargs.get("text", "")) + sum(len(c) for row in kwargs.get("rows", ()) for c in row)
        cell_total += sum(len(row) for row in kwargs.get("rows", ()))
        if len(items) >= MAX_ITEMS or text_total > MAX_TEXT or cell_total > MAX_CELLS:
            raise ImportError("Document exceeds the item/text/table review budget. Split it and retry; nothing was saved.")
        items.append(ImportItem(f"item-{len(items) + 1:04d}", kind, part, position, word_section, section, **kwargs))

    try:
        with _package(path) as archive:
            names = set(archive.namelist())
            image_metadata = {}
            def metadata(target):
                if target not in image_metadata:
                    with archive.open(target) as stream:
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                    width, height = 0, 0
                    try:
                        with archive.open(target) as stream, Image.open(stream) as picture:
                            width, height = picture.size  # Header only; no raster decode.
                    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                        pass
                    image_metadata[target] = dict(image_width=width, image_height=height, image_digest=digest)
                return image_metadata[target]
            rels = _relations(archive, "word/document.xml")
            parts = ["word/document.xml"]
            parts += sorted({target for target, kind in rels.values() if target in names and kind.rsplit("/", 1)[-1] in ("header", "footer", "footnotes", "endnotes")})
            risky = [n for n in names if n.startswith("word/embeddings/") or "vbaproject" in n.casefold()]
            if risky:
                notices.append(f"{len(risky)} embedded object/macro parts were not opened or executed.")
            for part in parts:
                relations = _relations(archive, part)
                external = sum(not target for target, _ in relations.values())
                if external:
                    notices.append(f"{part}: {external} external or unsafe relationships were not fetched.")
                stack, position, nodes = [], 0, 0
                heading_fragments = []
                with archive.open(part) as source:
                    events = ET.iterparse(source, events=("start", "end"), forbid_dtd=True)
                    for event, element in events:
                        if event == "start":
                            stack.append(element)
                            nodes += 1
                            if len(stack) > 100 or nodes > 1_000_000:
                                raise ImportError("DOCX XML complexity exceeds the parsing budget.")
                            continue
                        parent = stack[-2] if len(stack) > 1 else None
                        is_unit = parent is not None and parent.tag in (W + "body", W + "hdr", W + "ftr", W + "footnote", W + "endnote")
                        if is_unit:
                            position += 1
                            _visible(element)
                            text = _text(element)
                            source_note = ""
                            if part in ("word/footnotes.xml", "word/endnotes.xml"):
                                kind = "footnote" if "footnotes" in part else "endnote"
                                identity = parent.get(W + "id", "") if parent is not None else element.get(W + "id", "")
                                section, content_slot = note_owners.get((kind, identity), ("unmatched", ""))
                                source_note = kind + ":" + identity
                            detected = None
                            if part == "word/document.xml" and element.tag != W + "tbl":
                                if "tableofcontents" in re.sub(r"[^a-z]", "", text.casefold()):
                                    toc_section, section, heading_fragments = word_section, "", []
                                    toc_headings = set()
                                style = element.find(f"{W}pPr/{W}pStyle")
                                candidate = _heading(text)
                                if (word_section == toc_section and style is not None
                                        and style.get(W + "val", "").casefold().startswith("heading")
                                        and candidate and (candidate in toc_headings or not toc_headings
                                                           or not re.match(r"section\s+\d", text, re.I))):
                                    toc_section = 0
                                detected = _heading(text) if word_section != toc_section else None
                                if word_section == toc_section:
                                    compact = re.sub(r"[^a-z]", "", text.casefold())
                                    toc_headings.update(key for key, terms in _SECTION_TERMS.items() if any(term in compact for term in terms))
                                    heading_fragments = []
                                elif text and len(text) < 100:
                                    if not detected:
                                        detected = _heading(" ".join([*heading_fragments, text]))
                                    heading_fragments = [*heading_fragments, text][-3:]
                                elif text:
                                    heading_fragments = []
                            if detected:
                                section = detected
                                content_slot = ""
                            compact_text = re.sub(r"[^a-z]", "", text.casefold())
                            if section == "activity":
                                if compact_text in ("workorderstatus", "pmstatus"):
                                    content_slot = "work_orders"
                                elif compact_text == "activitysummary":
                                    content_slot = "activity_summary"
                                elif "improvementhighlights" in compact_text:
                                    content_slot = "improvements"
                            elif section == "capital" and "assetendofusefullifeschedule" in compact_text:
                                content_slot = "end_of_life"
                            if detected:
                                if detected != "unmatched":
                                    heading_fragments = []
                            if part == "word/document.xml":
                                for kind in ("footnote", "endnote"):
                                    for reference in element.iter(W + kind + "Reference"):
                                        note_owners[(kind, reference.get(W + "id", ""))] = (section, content_slot)
                            picture_table = element.tag == W + "tbl" and section == "activity" and content_slot == "improvements" and any(
                                node.tag in (A + "blip", V + "imagedata") for node in element.iter())
                            parents = {child: parent for parent in element.iter() for child in parent} if picture_table else {}
                            if part == "word/document.xml" and _is_native_divider_background(element, text):
                                background_positions.append((position, word_section))
                            if element.tag == W + "tbl":
                                rows = []
                                for row in element.findall(W + "tr"):
                                    cells = []
                                    before = row.find(f"{W}trPr/{W}gridBefore")
                                    cells.extend([""] * min(100, int(before.get(W + "val", "0"))) if before is not None else [])
                                    for cell in row.findall(W + "tc"):
                                        cells.append(_text(cell))
                                        span = cell.find(f"{W}tcPr/{W}gridSpan")
                                        count = int(span.get(W + "val", "1")) if span is not None else 1
                                        if count < 1 or count > 100 or len(cells) > 100:
                                            raise ImportError("Table is too wide to review safely.")
                                        cells.extend([""] * (count - 1))
                                    rows.append(tuple(cells))
                                if rows and not picture_table:
                                    width = max(map(len, rows))
                                    rows = tuple(row + ("",) * (width - len(row)) for row in rows)
                                    add("table", part, position, rows=rows, suggested_slot=content_slot or _suggest("table", text, section),
                                        note="Merged cells retain text in the first column of their span. Confirm headers and columns.")
                            elif text:
                                add("text", part, position, text=text, note=source_note, suggested_slot=(content_slot if content_slot and not detected else _suggest("text", text, section, heading=bool(detected), part=part)))
                                if part == "word/document.xml" and not section and len(titles) < 12:
                                    titles.extend(line for line in text.splitlines() if 3 < len(line) < 180 and line not in titles)
                            image_nodes = [e for e in element.iter() if e.tag in (A + "blip", V + "imagedata")]
                            seen = set()
                            for node in image_nodes:
                                rid = node.get(R + "embed") or node.get(R + "id") or node.get(R + "link") or ""
                                target, kind = relations.get(rid, ("", ""))
                                if target in seen and target:
                                    continue
                                seen.add(target)
                                safe = target in names and kind.endswith("/image") and target.startswith("word/media/")
                                supported = safe and Path(target).suffix.lower() in RASTER
                                caption = ""
                                if picture_table:
                                    ancestor = parents.get(node)
                                    while ancestor is not None and ancestor.tag != W + "tc":
                                        ancestor = parents.get(ancestor)
                                    if ancestor is not None:
                                        caption = _text(ancestor)
                                add("image" if supported else "unsupported", part, position, text=caption,
                                    image_part=target if safe else "", suggested_slot=_suggest("image", text, section, heading=bool(detected), part=part) if supported else "",
                                    note="" if supported else "External, missing or unsupported image. Export this drawing as PNG/JPEG and replace it after review.",
                                    **(metadata(target) if supported else {}))
                            graphics = [e for e in element.iter() if e.tag == A + "graphicData" and not e.get("uri", "").endswith("/picture")]
                            legacy_groups = element.findall(".//" + V + "group")
                            legacy_text = any(node.find(".//" + W + "txbxContent") is not None for node in element.iter() if node.tag in (V + "shape", V + "rect"))
                            if graphics or legacy_groups or legacy_text:
                                add("unsupported", part, position, text=text,
                                    note=("Native divider artwork" if detected and detected != "unmatched" else
                                          "Native Word drawing: preserve and review its complete page layout, or add a replacement picture. Nothing is executed during inspection."))
                            if element.find(".//" + W + "altChunk") is not None or element.tag == W + "altChunk":
                                add("unsupported", part, position, note="Embedded document content was not executed. Review it in the original.")
                            if part == "word/document.xml" and element.find(".//" + W + "sectPr") is not None:
                                word_section += 1
                            element.clear()
                            parent.remove(element)
                        stack.pop()
            referenced = {i.image_part for i in items if i.image_part}
            for name in sorted(names):
                if name.startswith("word/media/") and name not in referenced:
                    add("image" if Path(name).suffix.lower() in RASTER else "unsupported", name, 0, image_part=name,
                        note="Unplaced package asset; confirm whether it belongs in this report.")
            if risky:
                for name in sorted(risky):
                    add("unsupported", name, 0, note="Embedded object or macro; not opened or executed.")
    except (BadZipFile, KeyError, DefusedXmlException, ET.ParseError, OSError, RuntimeError) as exc:
        raise ImportError("This DOCX could not be safely read. No library content was changed.") from exc
    # Full-page native divider art can precede its title (and many empty anchor
    # paragraphs). Associate it with the next heading in that same Word section.
    for position, word_number in background_positions:
        heading = next((item for item in items if item.part == "word/document.xml"
                        and item.word_section == word_number and item.position >= position
                        and item.kind == "text" and _heading(item.text) not in (None, "unmatched")), None)
        if heading is None:
            continue
        target = _heading(heading.text)
        for index, item in enumerate(items):
            if item.part == "word/document.xml" and position <= item.position <= heading.position:
                slot = "divider_" + target if item.kind == "image" else ""
                items[index] = replace(item, section=target, suggested_slot=slot,
                                       note="Native divider artwork" if item.position <= heading.position else item.note)
    return DocxInspection(digest.hexdigest(), tuple(items), tuple(titles[:12]), tuple(notices), word_section)


def read_import_image(path: Path, item: ImportItem, *, line_art: bool = True, preview: bool = False):
    if item.kind != "image" or not item.image_part.startswith("word/media/"):
        raise ImportError("Select an extractable image.")
    try:
        with _package(path) as archive:
            info = archive.getinfo(item.image_part)
            if info.file_size > 30 * 1024 * 1024:
                raise ImportError("This image exceeds 30 MB. Export a smaller copy from Word.")
            raw = archive.read(item.image_part)
    except (BadZipFile, KeyError, OSError, RuntimeError) as exc:
        raise ImportError("This report picture could not be read. Upload the original DOCX again and choose Analyze report. Saved versions were not changed.") from exc
    return normalize_report_image(raw, Path(item.image_part).suffix, line_art=line_art,
                                  frame=(4, 5) if preview else (7, 9), dpi=96 if preview else 200)


def map_items(path: Path, inspection: DocxInspection, mappings: tuple[ImportMapping, ...]) -> MappedImport:
    """Build only selected mappings, retaining every unmapped item in inspection."""
    known = {b.key: b for s in default_sections() for b in s.blocks} | {b.key: b for b in layout_blocks()}
    items = {i.id: i for i in inspection.items}
    grouped, overrides, assets, mapped = {}, {}, {}, []
    total = 0
    for mapping in mappings:
        if mapping.item_id not in items or mapping.slot not in known or mapping.item_id in mapped:
            raise ImportError("Each selected item needs one valid destination.")
        item, spec = items[mapping.item_id], known[mapping.slot]
        if item.kind == "unsupported":
            raise ImportError("Unsupported items must remain in review until replaced with supported content.")
        block = grouped.get(mapping.slot, ResolvedBlock(mapping.slot, "Library"))
        reference = f"docx:{inspection.sha256}:{item.id}"
        if item.kind == "image":
            if spec.type not in ("image_page", "image_grid", "pdf_pages"):
                raise ImportError("An image needs an image destination.")
            if spec.type == "image_page" and block.asset_hashes:
                raise ImportError("Choose one image for each single-image destination.")
            normalized = read_import_image(path, item, line_art=mapping.slot not in ("cover_photo", "improvements") and not mapping.slot.startswith("divider_"))
            digest = hashlib.sha256(normalized.data).hexdigest() + "." + normalized.extension
            if digest not in assets:
                total += len(normalized.data)
                if total > MAX_NORMALIZED_BYTES:
                    raise ImportError("Selected normalized images exceed 60 MB. Import fewer assets at a time.")
                assets[digest] = normalized.data
            contexts = dict(block.asset_provenance)
            contexts[digest] = tuple(dict.fromkeys((*contexts.get(digest, ()), reference)))
            block = replace(block, asset_hashes=block.asset_hashes + (digest,), asset_provenance=tuple(contexts.items()),
                            asset_captions=block.asset_captions + (item.text,))
        elif item.kind == "table":
            if spec.type not in ("table", "work_order_grid") and mapping.slot != "contact_matrix":
                raise ImportError("A table needs a table destination.")
            if block.rows:
                raise ImportError("Map one table per destination; review additional tables separately.")
            width = len(item.rows[0])
            indices = mapping.columns or tuple(range(width))
            if len(set(indices)) != len(indices) or any(i < 0 or i >= width for i in indices):
                raise ImportError("Invalid imported table column mapping.")
            labels = item.rows[0] if mapping.first_row_header else tuple(f"Column {i+1}" for i in range(width))
            specs = tuple(ColumnSpec(f"imported_{j}", labels[i].strip() or f"Column {i+1}") for j, i in enumerate(indices))
            # Duplicate merged headers would overwrite values in the editor's dict.
            labels_seen = set()
            columns = []
            for j, col in enumerate(specs):
                title = col.title
                if title in labels_seen:
                    title += f" ({j+1})"
                labels_seen.add(title)
                columns.append(replace(col, title=title))
            overrides[mapping.slot] = replace(spec, type="table", columns=tuple(columns))
            rows = item.rows[1:] if mapping.first_row_header else item.rows
            block = replace(block, rows=tuple(tuple(row[i] for i in indices) for row in rows))
        else:
            if spec.type not in ("rich_text", "stock_text"):
                raise ImportError("Text needs a narrative or footer destination.")
            block = replace(block, text="\n\n".join(t for t in (block.text, item.text) if t))
        grouped[mapping.slot] = replace(block, references=block.references + (reference,))
        mapped.append(item.id)
    if not grouped:
        raise ImportError("Select at least one item and confirm its destination.")
    return MappedImport(tuple(grouped.values()), tuple(overrides.values()), tuple(assets.items()), tuple(mapped))


def imported_draft(profile: ReportProfile, period: ReportPeriod, prepared_by: str, mapped: MappedImport) -> ReportDraft:
    overrides = {b.key: b for b in (*profile.block_overrides, *mapped.overrides)}
    keys = {b.key for b in mapped.blocks}
    sections = tuple(replace(s, included=any(b.key in keys for b in s.blocks),
                             blocks=tuple(overrides.get(b.key, b) for b in s.blocks)) for s in profile_sections(profile))
    footer = next((b.text for b in mapped.blocks if b.key == "footer_text"), "")
    blocks = []
    from app.monthly_report_asset_review import preserve_asset_reviews
    for block in mapped.blocks:
        reviewed = block.client_reviewed_fingerprint == block.fingerprint
        block = preserve_asset_reviews(block, replace(block, source="Last month"))
        blocks.append(replace(block, client_reviewed_fingerprint=block.fingerprint if reviewed else ""))
    return ReportDraft(profile, period, prepared_by, sections, tuple(blocks), footer)
