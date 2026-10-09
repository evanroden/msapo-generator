"""Preserve reviewed Word chart pages without opening the uploaded package.

Build a small, passive DOCX from selected body sections and a closed dependency
graph. Only local raster images, SmartArt, styles and themes reach LibreOffice;
the original package, embedded objects, fields and external links never do.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import posixpath
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from xml.etree import ElementTree as XML
from zipfile import ZipFile, ZIP_DEFLATED

from defusedxml import ElementTree as ET
import fitz
from PIL import Image

from app.monthly_report_render_compat import rendering_docx
from app import monthly_report_library as library
from app.monthly_report_docx import normalize_report_image
from app.monthly_report_import import W, R, A, V, _package, _relations, _visible, ImportError

MAX_SECTIONS = 8
MAX_PAGES = 12
MAX_XML = 8 * 1024 * 1024
MAX_PACKAGE = 24 * 1024 * 1024
MAX_PARTS = 80
MAX_PAGE_BYTES = 24 * 1024 * 1024
_RENDER_LOCK = threading.Lock()
# Set child-only limits before exec; preexec_fn is unsafe in Streamlit threads.
_LIMIT_EXEC = """import os, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024**2, 32*1024**2))
resource.setrlimit(resource.RLIMIT_CPU, (40, 40))
os.execv(sys.argv[1], sys.argv[1:])
"""
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT = "http://schemas.openxmlformats.org/package/2006/content-types"
_OFFICE = R[1:-1]
_NAMESPACES = {
    W[1:-1], A[1:-1], V[1:-1],
    "urn:schemas-microsoft-com:office:word",
    "urn:schemas-microsoft-com:office:office",
    "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "http://schemas.openxmlformats.org/drawingml/2006/diagram",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",
    "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",
    "http://schemas.microsoft.com/office/drawing/2008/diagram",
    "http://schemas.microsoft.com/office/drawing/2010/main",
    "http://schemas.microsoft.com/office/word/2010/wordml",
}
_WORD_TAGS = set("""document body p pPr r rPr t tab br cr drawing pict txbxContent
tbl tblPr tblGrid gridCol tr trPr tc tcPr tblW tblInd tblLayout tblBorders tblCellMar
tblLook tblStyle tblHeader trHeight gridBefore gridAfter gridSpan vMerge vAlign
top left bottom right start end insideH insideV tcW tcBorders tcMar shd
pStyle rStyle spacing ind jc keepNext keepLines pageBreakBefore widowControl
contextualSpacing textAlignment outlineLvl tabs numPr ilvl numId
rFonts b bCs i iCs u strike dstrike caps smallCaps color sz szCs highlight
vertAlign position noProof lang rtl cs w fitText kern vanish textDirection
sectPr pgSz pgMar cols col docGrid type titlePg pgNumType
styles style name basedOn next link aliases uiPriority qFormat semiHidden
unhideWhenUsed locked personal personalCompose personalReply rsid
docDefaults rPrDefault pPrDefault latentStyles lsdException
numbering abstractNum abstractNumId num nsid multiLevelType tmpl lvl lvlText
numFmt lvlJc suff startOverride lvlOverride isLgl lvlRestart
""".split())
_DROP = {"instrText", "fldChar", "del", "delText", "headerReference", "footerReference",
         "printerSettings", "attachedTemplate", "hlinkClick", "hlinkMouseOver",
         "footnoteReference", "endnoteReference", "commentReference"}
_REJECT = {"object", "OLEObject", "altChunk", "control", "movie", "audioFile", "videoFile"}
_KINDS = {
    "styles": "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml",
    "numbering": "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml",
    "theme": "application/vnd.openxmlformats-officedocument.theme+xml",
    "diagramData": "application/vnd.openxmlformats-officedocument.drawingml.diagramData+xml",
    "diagramLayout": "application/vnd.openxmlformats-officedocument.drawingml.diagramLayout+xml",
    "diagramQuickStyle": "application/vnd.openxmlformats-officedocument.drawingml.diagramStyle+xml",
    "diagramColors": "application/vnd.openxmlformats-officedocument.drawingml.diagramColors+xml",
    "diagramDrawing": "application/vnd.ms-office.drawingml.diagramDrawing+xml",
}
_VML_STYLE = set("position margin-left margin-top margin-right margin-bottom left top width height z-index rotation flip visibility mso-position-horizontal mso-position-horizontal-relative mso-position-vertical mso-position-vertical-relative mso-wrap-style v-text-anchor".split())


@dataclass(frozen=True)
class WordPage:
    number: int
    data: bytes
    width: int
    height: int
    text: str
    blank: bool = False


def _clean(element):
    """Reconstruct passive markup. Relationships are resolved separately."""
    name = element.tag.rsplit("}", 1)[-1]
    namespace = element.tag.split("}", 1)[0].lstrip("{")
    if element.get(R + "link") or (namespace == V[1:-1] and any(element.get(k) for k in ("src", "href"))):
        raise ImportError("A drawing uses a linked picture. Add a local chart picture instead.")
    if name in _REJECT:
        raise ImportError("This section contains an embedded object that cannot be preserved automatically. Add a replacement picture instead.")
    if name in _DROP:
        return []
    # Flatten links, cached field results and compatibility wrappers to their
    # passive children. Unknown drawing namespaces cannot quietly disappear.
    if name in ("AlternateContent", "Choice", "Fallback", "hyperlink", "fldSimple", "sdt", "sdtContent", "ins"):
        return [out for child in element for out in _clean(child)]
    if namespace not in _NAMESPACES or (namespace == W[1:-1] and name not in _WORD_TAGS):
        if name in ("chart", "externalData", "blip", "imagedata", "graphicData"):
            raise ImportError("This drawing type needs a replacement picture. Its original remains unchanged.")
        return []
    attrs = {}
    for key, value in element.attrib.items():
        local = key.rsplit("}", 1)[-1]
        if local.lower() in ("href", "src", "althref", "action", "target", "macro", "code", "codebase") or local.lower().startswith("on"):
            continue
        if key.startswith(R):
            if local in ("embed", "id", "dm", "lo", "qs", "cs"):
                attrs[key] = value
            continue  # r:link must never trigger a fetch.
        if local == "style":
            declarations = []
            for entry in value.split(";"):
                prop, sep, val = entry.partition(":")
                if sep and prop.strip().lower() in _VML_STYLE and re.fullmatch(r"[-+\w. ,%]+", val.strip()):
                    declarations.append(prop.strip() + ":" + val.strip())
            attrs[key] = ";".join(declarations)
        elif local not in ("Ignorable", "Requires"):
            attrs[key] = value
    clean = XML.Element(element.tag, attrs)
    clean.text = element.text if name in ("t", "posOffset", "align") else None
    for child in element:
        clean.extend(_clean(child))
    return [clean]


def _bounded_dependency(stream):
    depth = nodes = 0
    root = None
    for event, node in ET.iterparse(stream, events=("start", "end"), forbid_dtd=True):
        if event == "start":
            depth += 1
            nodes += 1
            if root is None:
                root = node
            if depth > 80 or nodes > 100_000:
                raise ImportError("A drawing dependency exceeds the XML complexity budget.")
        else:
            depth -= 1
    return root


def safe_section_docx(path: Path, sections: tuple[int, ...]) -> bytes:
    """Copy selected Word sections with only the relationships actually needed."""
    if not sections or len(set(sections)) != len(sections) or len(sections) > MAX_SECTIONS or min(sections) < 1:
        raise ImportError("Automatic preparation supports between one and eight Word sections. Add replacement chart pictures instead.")
    with _package(path) as archive:
        doc = XML.Element(W + "document")
        body = XML.SubElement(doc, W + "body")
        stack, number, used, xml_bytes, nodes = [], 1, set(), 0, 0
        # Word's section properties END a section. Keep its own dimensions;
        # do not replace landscape charts with the last section's margins.
        with archive.open("word/document.xml") as stream:
            for event, element in ET.iterparse(stream, events=("start", "end"), forbid_dtd=True):
                if event == "start":
                    stack.append(element)
                    nodes += 1
                    if len(stack) > 100 or nodes > 1_000_000:
                        raise ImportError("This drawing exceeds the XML preparation budget.")
                    continue
                parent = stack[-2] if len(stack) > 1 else None
                if parent is not None and parent.tag == W + "body":
                    boundary = element.tag == W + "sectPr" or element.find(".//" + W + "sectPr") is not None
                    if number in sections:
                        used.add(number)
                        xml_bytes += len(XML.tostring(element))
                        if xml_bytes > MAX_XML:
                            raise ImportError("These chart sections exceed the 8 MB XML budget. Add replacement chart pictures instead.")
                        _visible(element)
                        body.extend(_clean(element))
                    if boundary:
                        number += 1
                    element.clear()
                    parent.remove(element)
                stack.pop()
        if used != set(sections):
            raise ImportError("The uploaded report changed. Analyze it again before preserving pages.")
        # A final paragraph section break creates an unnecessary empty page.
        if len(body) and body[-1].tag != W + "sectPr":
            last = body[-1].find(".//" + W + "sectPr")
            if last is not None:
                body[-1].find(W + "pPr").remove(last)
                body.append(last)
        for props in body.iter(W + "sectPr"):
            page = props.find(W + "pgSz")
            if page is not None:
                try:
                    if any(not 1440 <= int(page.get(W + key, "0")) <= 24480 for key in ("w", "h")):
                        raise ValueError()
                except ValueError as exc:
                    raise ImportError("This chart uses an unsupported page size. Add a replacement picture.") from exc
        parts, content_types, visiting = {}, {}, set()
        document_relations = _relations(archive, "word/document.xml")
        document_extra = set()
        total = 0

        def put(name, data, content_type):
            nonlocal total
            total += len(data)
            if total > MAX_PACKAGE or len(parts) >= MAX_PARTS:
                raise ImportError("These chart pages exceed the 24 MB preparation budget. Add replacement chart pictures instead.")
            parts[name] = data
            content_types[name] = content_type

        def copy_part(name, root, content_type):
            if name in parts:
                return
            if name in visiting:
                raise ImportError("Cyclic drawing relationships cannot be preserved.")
            if len(visiting) >= 10 or len(parts) + len(visiting) >= MAX_PARTS:
                raise ImportError("The drawing dependency graph exceeds the preparation budget.")
            visiting.add(name)
            relations = _relations(archive, name)
            needed = {value for node in root.iter() for key, value in node.attrib.items()
                      if key.startswith(R) or key == "relId"}
            # Styles/themes are implicit dependencies, not node relationship IDs.
            if name == "word/document.xml":
                needed.update(rid for rid, (_, kind) in relations.items() if kind.rsplit("/", 1)[-1] in ("styles", "numbering", "theme"))
            output_rels = XML.Element("Relationships", xmlns=_REL)
            pending, processed = sorted(needed), set()
            while pending:
                rid = pending.pop(0)
                if rid in processed:
                    continue
                processed.add(rid)
                target, kind = relations.get(rid, ("", ""))
                # SmartArt's dataModelExt relId belongs to the containing
                # document, unlike ordinary r:* part-local relationships.
                if not target and any(node.get("relId") == rid for node in root.iter()):
                    target, kind = document_relations.get(rid, ("", ""))
                    if kind.endswith("/diagramDrawing"):
                        document_extra.add(rid)
                short = kind.rsplit("/", 1)[-1]
                if not target or target not in archive.namelist() or not target.startswith("word/") or short not in (*_KINDS, "image"):
                    raise ImportError("A chart needs an external, missing or unsupported asset. Add a replacement picture instead.")
                destination = target
                if short == "image":
                    # Decode and re-encode; don't feed SVG, WMF or EMF programs
                    # or untrusted image metadata into the office converter.
                    if Path(target).suffix.lower() not in (".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".webp") or archive.getinfo(target).file_size > 30 * 1024 * 1024:
                        raise ImportError("This drawing uses a picture format that needs a PNG/JPEG replacement.")
                    destination = "word/media/" + hashlib.sha256(target.encode()).hexdigest() + ".png"
                    if destination not in parts:
                        image = normalize_report_image(archive.read(target), Path(target).suffix, line_art=True, dpi=150)
                        put(destination, image.data, "image/png")
                elif target not in parts:
                    if archive.getinfo(target).file_size > MAX_XML:
                        raise ImportError("Drawing XML exceeds the preparation budget.")
                    with archive.open(target) as stream:
                        source = _bounded_dependency(stream)
                    _visible(source)
                    clean = _clean(source)
                    if len(clean) != 1:
                        raise ImportError("A drawing dependency could not be preserved.")
                    copy_part(target, clean[0], _KINDS[short])
                XML.SubElement(output_rels, "Relationship", Id=rid, Type=kind, Target=posixpath.relpath(destination, posixpath.dirname(name)))
                if name == "word/document.xml":
                    pending.extend(sorted(document_extra - processed))
            if len(output_rels):
                rel_name = posixpath.join(posixpath.dirname(name), "_rels", posixpath.basename(name) + ".rels")
                put(rel_name, XML.tostring(output_rels, encoding="utf-8", xml_declaration=True), "application/vnd.openxmlformats-package.relationships+xml")
            put(name, XML.tostring(root, encoding="utf-8", xml_declaration=True), content_type)
            visiting.remove(name)

        copy_part("word/document.xml", doc, "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml")
        types = XML.Element("Types", xmlns=_CT)
        for name, content_type in sorted(content_types.items()):
            XML.SubElement(types, "Override", PartName="/" + name, ContentType=content_type)
        XML.SubElement(types, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
        relations = XML.Element("Relationships", xmlns=_REL)
        XML.SubElement(relations, "Relationship", Id="rId1", Type=_OFFICE + "/officeDocument", Target="word/document.xml")
        parts["_rels/.rels"] = XML.tostring(relations, encoding="utf-8", xml_declaration=True)
        parts["[Content_Types].xml"] = XML.tostring(types, encoding="utf-8", xml_declaration=True)
        result = BytesIO()
        with ZipFile(result, "w", ZIP_DEFLATED) as output:
            for name, data in sorted(parts.items()):
                output.writestr(name, data)
        return result.getvalue()


def _render(path: Path, directory: Path) -> Path:
    from app.monthly_report_render_jobs import conversion_slot
    with conversion_slot(wait_seconds=130):
        return _render_locked(path, directory)


def _render_locked(path: Path, directory: Path) -> Path:
    binary = shutil.which("libreoffice") or shutil.which("soffice")
    if not binary:
        raise ImportError("Word page preservation is unavailable. Add a chart picture instead.")
    profile = directory / "office-profile"
    from app.office_limits import prepare_profile
    prepare_profile(profile)
    process = subprocess.Popen([sys.executable, "-c", _LIMIT_EXEC, binary, "--headless", "--norestore", "-env:UserInstallation=" + profile.as_uri(),
                                "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(directory), str(path)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        process.communicate(timeout=60)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise ImportError("Chart preparation took too long. Add a replacement chart picture instead.") from exc
    pdf = directory / (path.stem + ".pdf")
    if process.returncode or not pdf.exists() or pdf.stat().st_size > MAX_PACKAGE:
        raise ImportError("These Word pages could not be preserved. Add a replacement picture; your original is unchanged.")
    return pdf


def preserve_word_pages(path: Path, sections: tuple[int, ...]) -> tuple[WordPage, ...]:
    """On-demand, caller-thread preparation. Never the network-only job pool."""
    if not _RENDER_LOCK.acquire(blocking=False):
        raise ImportError("Another chart is being prepared. Try again in a moment.")
    try:
        package = safe_section_docx(path, sections)
        root = library._root() / "imports"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="chart-", dir=root) as directory:
            directory = Path(directory)
            source = directory / "passive-chart.docx"
            source.write_bytes(rendering_docx(package))
            result, size = [], 0
            with fitz.open(_render(source, directory)) as pdf:
                if not 1 <= len(pdf) <= MAX_PAGES:
                    raise ImportError("These sections contain more than twelve pages. Add replacement chart pictures instead.")
                for index, page in enumerate(pdf, 1):
                    if max(page.rect.width, page.rect.height) > 1224:
                        raise ImportError("This chart page is too large to prepare.")
                    pix = page.get_pixmap(matrix=fitz.Matrix(160 / 72, 160 / 72), alpha=False)
                    raw = pix.tobytes("png")
                    size += len(raw)
                    if size > MAX_PAGE_BYTES:
                        raise ImportError("Prepared chart pictures exceed 24 MB. Add replacement chart pictures instead.")
                    picture = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    blank = all(low >= 248 for low, _ in picture.getextrema())
                    result.append(WordPage(index, raw, pix.width, pix.height, page.get_text()[:50000], blank))
            return tuple(result)
    finally:
        _RENDER_LOCK.release()
