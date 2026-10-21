"""Closed native furniture patterns, never a generic ignore-drawings switch.

The import retains these units and their source positions as native_layout
records. Text and images are still inspected separately. The native writer
owns their geometry; this classifier neither removes nor renders source data.
"""
import re
from copy import deepcopy

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
WPG = "{http://schemas.microsoft.com/office/word/2010/wordprocessingGroup}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
PALETTE = {"082b23", "547e7e", "557f7f", "d2e7df", "d3e7e0", "d5ee4a", "d6ef4b"}
CONTENTS_NOTICE = (
    "This report contains confidential and proprietary information intended solely for the recipient(s) named herein. "
    "Any unauthorized use or disclosure of the information within this proposal may result in legal ramifications. "
    "We respect the confidentiality of all parties involved and are committed to safeguarding the sensitive data presented in this document."
)
# Owner decision (#304): a generated monthly report names itself a report.
REPORT_NOTICE = CONTENTS_NOTICE.replace("within this proposal", "within this report")


def name_report_in_contents_notice(root):
    """Say "this report" in every retained copy of the master's confidentiality notice.

    Only a paragraph whose whole text is that notice changes, one word across
    its runs, so run formatting and every other text stay exactly as authored.
    A word split across runs keeps that split: each run takes the replacement
    letters at its own positions, and the last one any remainder.
    """
    start = CONTENTS_NOTICE.index("this proposal") + len("this ")
    end, replacement = start + len("proposal"), "report"
    for paragraph in root.iter(W + "p"):
        nodes = list(paragraph.iter(W + "t"))
        text = "".join(node.text or "" for node in nodes)
        if text.strip() != CONTENTS_NOTICE:
            continue
        word = start + len(text) - len(text.lstrip())
        spans, offset = [], 0
        for node in nodes:
            value = node.text or ""
            left, right = max(word, offset), min(word + end - start, offset + len(value))
            if left < right:
                spans.append((node, value, left - offset, right - offset, left - word, right - word))
            offset += len(value)
        for index, (node, value, left, right, first, last) in enumerate(spans):
            piece = replacement[first:] if index == len(spans) - 1 else replacement[first:last]
            node.text = value[:left] + piece + value[right:]


def _legacy_band_path(value):
    """VML spelling of the same closed four-edge band accepted by _polygon."""
    value = re.sub(r"\s+", "", value)
    if not re.fullmatch(r"[mlrxe0-9,-]+", value):
        return False
    commands = re.findall(r"([mlrxe])([^mlrxe]*)", value)
    if not commands or commands[0][0] != "m" or commands[-2:] != [("x", ""), ("e", "")]:
        return False
    points = []
    try:
        for index, (command, arguments) in enumerate(commands[:-2]):
            if command not in ({"m"} if index == 0 else {"l", "r"}):
                return False
            numbers = [int(n or "0") for n in arguments.split(",")]
            if len(numbers) % 2 or (index == 0 and len(numbers) != 2):
                return False
            for offset in range(0, len(numbers), 2):
                x, y = numbers[offset:offset + 2]
                if command == "r":
                    x, y = x + points[-1][0], y + points[-1][1]
                points.append((x, y))
                if len(points) > 5:
                    return False
    except (ValueError, IndexError):
        return False
    return (len(points) == 5 and points[0] == points[-1]
            and points[0][1] == points[1][1] == 0 and points[2][1] == points[3][1] > 0
            and (points[0][0] == points[3][0] or points[1][0] == points[2][0]))


def equivalent_native_alternatives(element, image_identity):
    """A new furniture exemption must cover every retained representation.

    The importer displays Choice while native Word keeps Fallback. Compare
    current-view text and resolved image bytes before selecting a branch. IDs
    and DrawingML/VML geometry may differ; hidden text, images and commands may
    not acquire approval merely because the modern branch looks harmless.
    """
    if element.find(".//" + MC + "AlternateContent") is None:
        return True
    from app.monthly_report_revision_view import current_view
    element = deepcopy(element)
    try:
        current_view(element)
    except ValueError:
        return False  # _visible reports the existing, correctly typed error.

    def signature(branch):
        text, pictures, shapes = [], set(), []
        for node in branch.iter():
            namespace = node.tag.rsplit("}", 1)[0] + "}"
            if namespace not in {W, A, R, WPS, WPG, WP, PIC, MC,
                    "{http://schemas.microsoft.com/office/word/2010/wordml}",
                    "{http://schemas.microsoft.com/office/word/2012/wordml}",
                    "{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}",
                    "{http://schemas.microsoft.com/office/drawing/2010/main}",
                    "{urn:schemas-microsoft-com:office:word}", "{urn:schemas-microsoft-com:vml}"}:
                return None
            local = node.tag.rsplit("}", 1)[-1]
            if local in {"object", "OLEObject", "altChunk", "relIds", "linkedTxbx", "chart", "control", "contentPart", "sym"}:
                return None
            if node.tag == A + "graphicData" and node.get("uri") not in (WPS[1:-1], WPG[1:-1], PIC[1:-1]):
                return None
            if node.tag == WPS + "wsp":
                if _frame(node, plain=False):
                    shapes.append("text-frame")
                elif _polygon(node):
                    shapes.append("band")
                else:
                    return None
            if namespace == "{urn:schemas-microsoft-com:vml}" and local in {"shape", "rect", "roundrect", "oval", "line", "polyline", "curve", "arc"}:
                if node.find(".//{urn:schemas-microsoft-com:vml}imagedata") is not None:
                    continue  # The resolved image bytes are compared below.
                color = re.fullmatch(r"#([0-9a-fA-F]{6})(?: \[\d+\])?", node.get("fillcolor", ""))
                if (local in {"shape", "rect"} and color and color[1].casefold() in PALETTE
                        and node.find(".//" + W + "txbxContent") is None
                        and node.get("stroked", "").casefold() in {"f", "false"}
                        and (local == "rect" or _legacy_band_path(node.get("path", "")))):
                    shapes.append("band")
                elif (local in {"shape", "rect"} and not node.get("path")
                        and (local == "rect" or node.get("type", "").endswith("#_x0000_t202"))):
                    shapes.append("text-frame")
                else:
                    return None
            if node.tag in {W + "t", A + "t", W + "instrText"}:
                text.append(node.text or "")
            if local == "textpath":
                text.append(node.get("string", ""))
            if local == "fldSimple":
                text.append(node.get(W + "instr", ""))
            for key, value in node.attrib.items():
                if key.startswith(R):
                    identity = image_identity(value)
                    if identity is None:
                        return None
                    pictures.add(identity)
            if local in {"imagedata", "fill"} and (node.get("src") or node.get("href")):
                return None
        return re.sub(r"\s+", " ", "".join(text)).strip(), frozenset(pictures), tuple(sorted(shapes))

    for wrapper in element.iter(MC + "AlternateContent"):
        signatures = [signature(branch) for branch in wrapper]
        if not signatures or signatures[0] is None or any(s != signatures[0] for s in signatures):
            return False
    return True


def _closed_shapes(element):
    if any(node.tag.startswith("{urn:schemas-microsoft-com:vml}")
           or node.tag in (W + "object", W + "altChunk") for node in element.iter()):
        return ()
    graphics = list(element.iter(A + "graphicData"))
    if not graphics or any(g.get("uri") not in (WPS[1:-1], WPG[1:-1], PIC[1:-1]) for g in graphics):
        return ()
    for graphic in graphics:
        for node in graphic.iter():
            # Unknown drawing vocabularies, linked frames, WordArt, connectors,
            # embedded objects and relationships other than pictures stay open.
            namespace, _, local = node.tag.rpartition("}")
            if namespace + "}" not in (A, W, WPS, WPG, PIC, WP,
                    "{http://schemas.microsoft.com/office/word/2010/wordml}",
                    "{http://schemas.microsoft.com/office/word/2012/wordml}",
                    "{http://schemas.microsoft.com/office/drawing/2010/main}"):
                return ()
            if local in {"linkedTxbx", "cxnSp", "stCxn", "endCxn", "object", "altChunk", "textpath", "hlinkClick", "hlinkHover", "sym"} or node.tag == A + "t":
                return ()
            if any(key.startswith(R) for key in node.attrib) and node.tag != A + "blip":
                return ()
            if node.tag == A + "blip" and node.get(R + "link"):
                return ()
            if node.tag == W + "instrText" and (node.text or "").strip().upper() not in {"PAGE", "NUMPAGES", "SECTION", "SECTIONPAGES"}:
                return ()
            if node.tag == W + "fldSimple" and node.get(W + "instr", "").strip().upper() not in {"PAGE", "NUMPAGES", "SECTION", "SECTIONPAGES"}:
                return ()
    shapes = tuple(element.iter(WPS + "wsp"))
    if any(child.tag not in {WPS + name for name in ("cNvPr", "cNvSpPr", "spPr", "txbx", "bodyPr")}
           for shape in shapes for child in shape):
        return ()
    return shapes if shapes else ()


def _frame(shape, *, plain=True):
    props = shape.find(WPS + "spPr")
    geometry = props.find(A + "prstGeom") if props is not None else None
    if (shape.find(".//" + W + "txbxContent") is None or geometry is None
            or geometry.get("prst") != "rect" or shape.find(WPS + "style") is not None
            or (plain and any(n.tag == A + "blip" for n in shape.iter()))):
        return False
    allowed = {A + "xfrm", A + "prstGeom", A + "noFill"}
    if not plain:
        allowed |= {A + "solidFill", A + "ln"}
    return all(child.tag in allowed
               or (child.tag == A + "ln" and child.find(A + "noFill") is not None
                   and all(n.tag in {A + "noFill", A + "prstDash", A + "round", A + "headEnd", A + "tailEnd"}
                           and (n.tag not in {A + "headEnd", A + "tailEnd"} or n.get("type", "none") == "none") for n in child))
               or (child.tag == A + "effectLst" and not len(child)) for child in props)


def _polygon(shape, *, colors=PALETTE, thin=False):
    """A filled four-sided native band, not any arbitrary custom drawing."""
    if shape.find(".//" + W + "txbxContent") is not None:
        return False
    props = shape.find(WPS + "spPr")
    if props is None or any(child.tag not in {A + "xfrm", A + "custGeom", A + "prstGeom", A + "solidFill"} for child in props):
        return False
    fill = props.find(A + "solidFill")
    if fill is None or len(fill) != 1:
        return False
    color = fill[0]
    if not (color.tag == A + "srgbClr" and color.get("val", "").casefold() in colors
            or color.tag == A + "schemeClr" and color.get("val") == "accent2"):
        return False
    extent = props.find(A + "xfrm/" + A + "ext")
    if extent is None:
        return False
    try:
        width, height = int(extent.get("cx", "0")), int(extent.get("cy", "0"))
    except ValueError:
        return False
    if width <= 0 or height <= 0 or (thin and not (width >= 5_000_000 and 0 < height <= 180_000)):
        return False
    geometry = props.find(A + "custGeom")
    if geometry is None:
        preset = props.find(A + "prstGeom")
        return not thin and preset is not None and preset.get("prst") == "rect"
    paths = geometry.findall(A + "pathLst/" + A + "path")
    if len(paths) != 1:
        return False
    path = paths[0]
    if [n.tag for n in path] != [A + "moveTo", *([A + "lnTo"] * 4), A + "close"]:
        return False
    points = list(path.iter(A + "pt"))
    if len(points) != 5 or points[0].attrib != points[-1].attrib:
        return False
    try:
        coords = [(int(p.get("x", "")), int(p.get("y", ""))) for p in points]
    except ValueError:
        return False
    # Horizontal top/bottom edges, one vertical side, a slanted opposite side.
    return (coords[0][1] == coords[1][1] == 0 and coords[2][1] == coords[3][1] > 0
            and (coords[0][0] == coords[3][0] or coords[1][0] == coords[2][0]))


def mint_divider_background(element, text):
    """The three-band mint/teal page-photo variant, with no other payload."""
    # The writer preserves modern/legacy representations. Inspect its current
    # Choice on a copy, just as the importer does; do not count both as artwork.
    if element.find(".//" + MC + "AlternateContent") is not None:
        if re.sub(r"[\d.\s]", "", text):
            return False
        element = deepcopy(element)
        for wrapper in element.iter(MC + "AlternateContent"):
            choice = wrapper.find(MC + "Choice")
            if choice is None:
                choice = wrapper.find(MC + "Fallback")
            for child in list(wrapper):
                if child is not choice:
                    wrapper.remove(child)
        text = "".join(node.text or "" for node in element.iter(W + "t"))
    shapes = _closed_shapes(element)
    if not shapes or (text.strip() and re.sub(r"\s+", "", text) not in ("1.2.3.4.5.", "1.2.3.4.5.1.2.3.4.5.")):
        return False
    bands = [shape for shape in shapes if _polygon(shape)]
    frames = [shape for shape in shapes if _frame(shape)]
    if len(bands) != 3 or len(frames) > 1 or len(bands) + len(frames) != len(shapes):
        return False
    fills = {n.get("val", "").casefold() for shape in bands for n in shape.iter(A + "srgbClr")}
    if not {"547e7e", "d2e7df"}.issubset(fills):
        return False
    photos = [anchor for anchor in element.iter(WP + "anchor") if any(True for _ in anchor.iter(A + "blip"))]
    if len(photos) != 1:
        return False
    extent = photos[0].find(WP + "extent")
    vertical = photos[0].find(WP + "positionV")
    try:
        return (extent is not None and vertical is not None and vertical.get("relativeFrom") == "page"
                and 6_000_000 < int(extent.get("cx", "0")) < 12_000_000
                and 6_000_000 < int(extent.get("cy", "0")) < 16_000_000)
    except ValueError:
        return False


def clear_native_design_placeholders(element, *, cover=False):
    """Clean only proved source furniture in the writer's private output copy."""
    def text(box):
        return "".join(node.text or "" for node in box.iter(W + "t"))
    divider = mint_divider_background(element, text(element))
    for box in element.iter(W + "txbxContent"):
        value = re.sub(r"\s+", "", text(box))
        if ((divider and value == "1.2.3.4.5.")
                or (cover and value.upper() in {"INSERTCLIENTLOGO", "INSERTIMAGEHERE"})):
            for node in box.iter(W + "t"):
                node.text = ""


def native_layout_role(element, text, *, part, section, word_section):
    shapes = _closed_shapes(element)
    if not shapes:
        return ""
    plain = all(_frame(shape) for shape in shapes)
    lines = tuple(line.strip() for line in text.splitlines() if line.strip())
    if plain and not text.strip():
        return "Empty unstyled native text frames"
    if part.startswith("word/header"):
        if plain and set(lines) <= {"Client Utility Rate Analysis", "Author:"}:
            return "Native running-header text frames"
        return ""
    if part.startswith("word/footer"):
        if plain and len(lines) == 1 and re.fullmatch(r"\d+ Galleria Blvd\..*\|.*enfrasolutions\.com", lines[0], re.I):
            return "Native footer text frames"
        return ""
    if part != "word/document.xml":
        return ""
    if section and section not in ("cover", "unmatched"):
        if (plain and len(shapes) == 1) or (text.strip() and len(shapes) == 1 and _frame(shapes[0], plain=False)
                     and not any(True for _ in shapes[0].iter(A + "blip"))
                     and shapes[0].find(WPS + "spPr/" + A + "solidFill") is None):
            return "Editable native text frames"
        if not text.strip() and len(shapes) == 1 and _polygon(shapes[0], colors={"d6ef4b", "d5ee4a"}, thin=True):
            return "Native divider rule"
        return ""
    if word_section > 2 or not all(_frame(shape, plain=False) or _polygon(shape) for shape in shapes):
        return ""
    if word_section == 1:
        if text.strip() in ("", "=") and len(shapes) == 1 and _polygon(shapes[0], colors={"082b23"}):
            return "Native cover branding band"
        recognized = [line for line in lines if re.fullmatch(r"Prepared by: [^\n]{1,120}|(?:January|February|March|April|May|June|July|August|September|October|November|December) 20\d\d|Operations and Maintenance Monthly Review|INSERT CLIENT LOGO", line, re.I)]
        other = [line for line in lines if line not in recognized]
        title = "Operations and Maintenance Monthly Review"
        title_frame = any(other and (other[0] + title) == "".join(n.text or "" for n in shape.iter(W + "t")) for shape in shapes)
        if (len(recognized) >= 3 and title in lines and title_frame
                and any(line.startswith("Prepared by:") for line in recognized)
                and len(other) == 1 and len(other[0]) <= 100
                and not re.search(r"[$€£]|\d{3,}", other[0])):
            return "Native cover title and artwork"
    else:
        if lines and all(line == "ENFRA" or re.fullmatch(r"Section \d{1,2}: [A-Za-z /&-]{3,90}", line) for line in lines):
            return "Native contents text frames"
        if (lines and lines[0] == "TABLE OF CONTENTS" and len(lines) == 3
                and lines[1] in (CONTENTS_NOTICE, REPORT_NOTICE)
                and re.fullmatch(r"\d+ Galleria Blvd\..*\|.*enfrasolutions\.com", lines[2], re.I)):
            return "Native contents notice and artwork"
    return ""
