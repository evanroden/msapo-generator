"""Proved source-specific correction for a Word divider's clipped two-digit numeral.

This is intentionally NOT a document-wide font or textbox adjustment.  The
matching geometry and negative terminal tracking were measured against the
original authored Unity/USH PDF and a LibreOffice 24.2 render.  A different
font/layout, a missing compatibility branch, or a changed master must retain its
native design until it has its own paired-reference evidence.
"""
from __future__ import annotations

import re

from docx.oxml.ns import qn

MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
WPS = "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}"
VML = "{urn:schemas-microsoft-com:vml}"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# Twips and EMUs from the paired Word-source/Adobe-authored numeral shape.
_X = 12700
_FRAME_CX = 2574290
_FRAME_CY = 3657600
_POS_V = 5596885
_FALLBACK_WIDTH = 202.7
_FALLBACK_TOP = 440.7
_LAST_SPACING = -400  # 1/20 pt; LibreOffice counts the terminal -20 pt differently
# A 5pt downward translation matches the measured visible glyph ink after the
# two digits fit.  Without this paired correction, width-only leaves the bottom
# of the numerals several points above the authored reference.
_DELTA_CX = 20 * _X
_DELTA_Y = 5 * _X


def _numeric_text(branch):
    paragraphs = list(branch.iter(qn("w:p")))
    if len(paragraphs) != 1:
        return False
    paragraph = paragraphs[0]
    runs = [run for run in paragraph.iter(qn("w:r")) if next(
        (p for p in run.iterancestors(qn("w:p"))), None) is paragraph]
    if len(runs) != 2 or ["".join(t.text or "" for t in r.iter(qn("w:t"))).strip() for r in runs] != ["1", "0"]:
        return False
    return all(run.find("./" + qn("w:rPr") + "/" + qn("w:spacing")) is not None
               and run.find("./" + qn("w:rPr") + "/" + qn("w:spacing")).get(qn("w:val")) == str(_LAST_SPACING)
               and run.find("./" + qn("w:rPr") + "/" + qn("w:sz")) is not None
               and run.find("./" + qn("w:rPr") + "/" + qn("w:sz")).get(qn("w:val")) == "420"
               for run in runs)


def _pair(alternate):
    choices = alternate.findall(MC + "Choice")
    fallbacks = alternate.findall(MC + "Fallback")
    if len(choices) != 1 or len(fallbacks) != 1:
        return None
    choice, fallback = choices[0], fallbacks[0]
    if not _numeric_text(choice) or not _numeric_text(fallback):
        return None
    anchor = next(choice.iter(qn("wp:anchor")), None)
    shape = next(fallback.iter(VML + "shape"), None)
    if anchor is None or shape is None or len(list(choice.iter(qn("wp:anchor")))) != 1:
        return None
    extent = anchor.find(qn("wp:extent"))
    vertical = anchor.find(qn("wp:positionV"))
    offset = vertical.find(qn("wp:posOffset")) if vertical is not None else None
    if (extent is None or vertical is None or offset is None
            or extent.get("cx") != str(_FRAME_CX) or extent.get("cy") != str(_FRAME_CY)
            or vertical.get("relativeFrom") != "page" or offset.text != str(_POS_V)):
        return None
    inner = next(choice.iter(qn("a:ext")), None)
    if inner is None or inner.get("cx") != extent.get("cx") or inner.get("cy") != extent.get("cy"):
        return None
    body = next(choice.iter(WPS + "bodyPr"), None)
    if body is None or body.get("wrap") not in ("square", None):
        return None
    style = shape.get("style", "")
    if not (re.search(r"(?<!\w)width:202\.7pt(?:;|$)", style)
            and re.search(r"(?<!\w)margin-top:440\.7pt(?:;|$)", style)):
        return None
    if len(list(fallback.iter(VML + "shape"))) != 1:
        return None
    return extent, inner, offset, shape


def fit_proposals_numeral(document, *, section_key=None) -> bool:
    """Change both Word Choice/Fallback geometries only for one proved '10'.

    If the recognized layout is absent or ambiguous, native output is untouched.
    Source files, installed masters and immutable design profiles are unchanged.
    """
    if section_key not in (None, "proposals"):
        return False
    alternatives = list(document.element.body.iter(MC + "AlternateContent"))
    matches = [_pair(alt) for alt in alternatives]
    matches = [candidate for candidate in matches if candidate is not None]
    if len(matches) != 1:
        return False
    extent, inner, offset, shape = matches[0]
    for node in (extent, inner):
        node.set("cx", str(_FRAME_CX + _DELTA_CX))
    offset.text = str(_POS_V + _DELTA_Y)
    style = shape.get("style")
    style = style.replace("width:202.7pt", "width:222.7pt", 1)
    style = style.replace("margin-top:440.7pt", "margin-top:445.7pt", 1)
    shape.set("style", style)
    return True
