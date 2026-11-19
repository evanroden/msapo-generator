"""Capped, read-only evidence for embedded DOCX chart relationships.

Chart text is review evidence only. Chart series, numeric values, workbook
references and geometry are NOT treated as editable report tables or approved
images; the original chart remains in native drawing review.
"""
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from lxml import etree

from app.monthly_report_xml_parser import parse_xml_stream

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_CHART_XML = 512 * 1024
MAX_LABELS = 64
MAX_LABEL_CHARS = 4096


def chart_relationship_evidence(archive, graphics, relations, names):
    """(relationship IDs, review-only labels, honest notices) for chart nodes."""
    ids, labels, notices = [], [], []
    chart_nodes = [node for graphic in graphics for node in graphic.iter(C + "chart")]
    for node in chart_nodes:
        identity = node.get(R + "id", "")
        if identity and identity not in ids:
            ids.append(identity)
        target, kind = relations.get(identity, ("", ""))
        if not (identity and target in names and target.startswith("word/charts/")
                and target.endswith(".xml") and kind.endswith("/chart")):
            notices.append(f"Chart relationship {identity or '(missing ID)'} has no safe local chart part; review the original drawing.")
            continue
        if archive.getinfo(target).file_size > MAX_CHART_XML:
            notices.append(f"Chart {identity} exceeds the 512 KiB chart-label inspection budget; review the original.")
            continue
        try:
            with archive.open(target) as source:
                root = parse_xml_stream(source).getroot()
        except (ET.ParseError, etree.XMLSyntaxError, DefusedXmlException, ValueError, OSError, RuntimeError) as exc:
            notices.append(f"Chart {identity} could not be read safely ({type(exc).__name__}); review the original.")
            continue
        # Only chart titles, series names and category labels are text evidence.
        # Exclude c:val numeric measures, c:f formulas and external workbooks.
        candidates = []
        for title in root.iter(C + "title"):
            candidates.extend(n.text or "" for n in title.iter() if n.tag in (A + "t", C + "v"))
        for series in root.iter(C + "ser"):
            for child in series:
                if child.tag in (C + "tx", C + "cat"):
                    candidates.extend(n.text or "" for n in child.iter() if n.tag in (A + "t", C + "v"))
        candidates = [v.strip() for v in candidates if v.strip()]
        if len(candidates) > MAX_LABELS or sum(map(len, candidates)) > MAX_LABEL_CHARS:
            notices.append(f"Chart {identity} has more labels than the 64-item/4096-character review budget; the original is required.")
            continue
        labels.extend(candidates)
        notices.append(f"Chart {identity} has {len(candidates)} review-only title/series/category label(s); numeric data and layout are not imported.")
    return tuple(ids), tuple(labels), tuple(notices)
