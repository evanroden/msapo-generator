"""Occurrence-only slot evidence from a narrowly closed native text frame.

This classifies a slot, NOT image identity, approval, client correctness or
Choice/Fallback equivalence. The ordinary divergent-alternatives guard remains
in force. No role is inferred from a filename, image dimensions or equal bytes.
"""
import re

from app.monthly_report_native_design import A, MC, PIC, W, WP, WPS, _frame

R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
V = "{urn:schemas-microsoft-com:vml}"
A14 = "{http://schemas.microsoft.com/office/drawing/2010/main}"
# This is an intentionally small slot-label grammar, not a general WPS/VML
# interpreter. Unknown markup, revisions, fields and extra artwork give no hint.
_ALLOWED = {
    W: "p pPr r rPr t txbxContent drawing pict b bCs jc noProof highlight sz szCs rFonts color lang spacing ind keepNext keepLines",
    WP: "anchor inline cNvGraphicFramePr docPr effectExtent extent posOffset positionH positionV simplePos wrapNone",
    A: "avLst blip ext extLst fillRect graphic graphicData graphicFrameLocks ln noAutofit noFill off picLocks prstClr prstGeom prstTxWarp schemeClr solidFill srcRect stretch xfrm",
    WPS: "bodyPr cNvSpPr spPr txbx wsp",
    PIC: "blipFill cNvPicPr cNvPr nvPicPr pic spPr",
    V: "shape textbox",
    A14: "useLocalDpi",
    MC: "Choice Fallback",
}
_ALLOWED_TAGS = {namespace + name for namespace, names in _ALLOWED.items() for name in names.split()}


def _drawing_container(node, parents, uri):
    """Recognize the closed DrawingML scaffold, not an arbitrary ancestor."""
    for tags in ((A + "graphicData",), (A + "graphic",),
                 (WP + "inline", WP + "anchor"), (W + "drawing",)):
        node = parents.get(node)
        if node is None or node.tag not in tags:
            return None
        if node.tag == A + "graphicData" and node.get("uri") != uri:
            return None
    return node


def _labelled_picture(container, image_identity, label_role):
    nodes = list(container.iter())
    parents = {child: parent for parent in nodes for child in parent}
    if any(node.tag not in _ALLOWED_TAGS or (node.tail or "").strip()
           or ((node.text or "").strip() and node.tag not in (W + "t", WP + "posOffset"))
           or (node.tag == WP + "posOffset" and not re.fullmatch(r"-?\d{1,24}", node.text or ""))
           for node in nodes):
        return None
    frames = [node for node in nodes if node.tag in (WPS + "wsp", V + "shape")]
    pictures = [node for node in nodes if node.tag == A + "blip"]
    if len(frames) != 1 or len(pictures) != 1:
        return None
    frame, picture = frames[0], pictures[0]
    boxes = list(frame.iter(W + "txbxContent"))
    expected_box = frame.find((WPS + "txbx/" if frame.tag == WPS + "wsp" else V + "textbox/") + W + "txbxContent")
    pic_nodes = list(frame.iter(PIC + "pic"))
    if (len(boxes) != 1 or boxes[0] is not expected_box or len(pic_nodes) != 1
            or pic_nodes[0] not in set(boxes[0].iter())
            or pic_nodes[0].find(PIC + "blipFill/" + A + "blip") is not picture):
        return None
    drawing = _drawing_container(pic_nodes[0], parents, PIC[1:-1])
    run = parents.get(drawing)
    paragraph = parents.get(run)
    if (drawing is None or run is None or run.tag != W + "r"
            or paragraph is None or paragraph.tag != W + "p"
            or parents.get(paragraph) is not boxes[0]):
        return None
    if picture not in set(frame.iter()):
        return None  # An adjacent/sibling picture does not occupy this slot.
    if frame.tag == WPS + "wsp":
        if _drawing_container(frame, parents, WPS[1:-1]) is None or not _frame(frame, plain=False) or any(child.tag not in {
                WPS + name for name in ("cNvSpPr", "spPr", "txbx", "bodyPr")} for child in frame):
            return None
    elif frame.get("path") or not frame.get("type", "").endswith("#_x0000_t202"):
        return None
    text = re.sub(r"\s+", " ", "".join(node.text or "" for node in nodes if node.tag == W + "t")).strip()
    if text.casefold() != "insert client logo":
        return None
    references = [(node, key, value) for node in nodes for key, value in node.attrib.items() if key.startswith(R)]
    if (len(references) != 1 or references[0][:2] != (picture, R + "embed")
            or image_identity(references[0][2]) is None):
        return None
    for node in nodes:
        if any(key.rsplit("}", 1)[-1].casefold() in {"href", "src", "action", "onload", "onclick"}
               for key in node.attrib):
            return None
        if node.tag == A + "graphicData" and node.get("uri") not in (WPS[1:-1], PIC[1:-1]):
            return None
        if node.tag == A + "extLst":
            # The sole supported extension only controls local DPI, not a new
            # image layer or hidden SVG/diagram payload.
            if (len(node) != 1 or node[0].tag != A + "ext" or len(node[0]) != 1
                    or node[0][0].tag != A14 + "useLocalDpi"
                    or node[0].get("uri") != "{28A0092B-C50C-407E-A947-70E740481C1C}"
                    or node[0][0].get("val") not in ("0", "1")):
                return None
        if any(label_role(node.get(key, "")) == "brand_logo" for key in ("descr", "title", "alt")):
            return None
    return picture


def client_logo_frame_pictures(element, image_identity, label_role):
    """Return source nodes whose exact enclosing frame proves client-logo slot.

    Every retained branch must independently have this same sole label and one
    local picture. Differing image bytes remain divergent to the separate native
    import guard. No returned hint authorizes another occurrence or later source.
    """
    parents = {child: parent for parent in element.iter() for child in parent}
    result = set()
    for wrapper in element.iter(MC + "AlternateContent"):
        ancestor = parents.get(wrapper)
        nested_frame = False
        while ancestor is not None:
            if ancestor.tag in (WPS + "wsp", V + "shape", MC + "AlternateContent"):
                nested_frame = True
                break
            ancestor = parents.get(ancestor)
        if nested_frame:
            continue
        # Narrow support: exactly one Choice and one Fallback, no nested wrapper.
        if ([node.tag for node in wrapper] != [MC + "Choice", MC + "Fallback"]
                or wrapper.find(".//" + MC + "AlternateContent") is not None):
            continue
        pictures = [_labelled_picture(branch, image_identity, label_role) for branch in wrapper]
        if all(picture is not None for picture in pictures):
            result.update(pictures)
    for frame in element.iter(WPS + "wsp"):
        ancestor = parents.get(frame)
        in_alternate = False
        while ancestor is not None:
            if ancestor.tag in (MC + "AlternateContent", WPS + "wsp", V + "shape"):
                in_alternate = True
                break
            ancestor = parents.get(ancestor)
        if not in_alternate:
            container = _drawing_container(frame, parents, WPS[1:-1])
            picture = (_labelled_picture(container, image_identity, label_role)
                       if container is not None else None)
            if picture is not None:
                result.add(picture)
    return result
