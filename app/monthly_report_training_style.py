"""Compact training data inside native ENFRA table geometry and typography."""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.monthly_report_training import EVENT_REF, MATRIX_REF

STATUS_COLORS = {"Completed": "D8F3DC", "Pending": "FFF0B3", "Not required": "E5E7EB", "Not recorded": "F3F4F6"}


def _property(parent, name):
    node = parent.find(qn(name))
    if node is None:
        node = OxmlElement(name)
        parent.append(node)
    return node


def style_training_table(element, reference):
    """Touch generated training tables only; retain native grid, fonts and header."""
    if reference not in (MATRIX_REF, EVENT_REF):
        return
    for index, row in enumerate(element.findall(qn("w:tr"))):
        properties = _property(row, "w:trPr")
        # Native source tables can be full-page organizational-chart frames.
        # Their fixed/minimum heights must not become empty training boxes.
        for height in list(properties.findall(qn("w:trHeight"))):
            properties.remove(height)
        _property(properties, "w:cantSplit")
        if index == 0:
            _property(properties, "w:tblHeader")
        for column, cell in enumerate(row.findall(qn("w:tc"))):
            for paragraph in cell.findall(qn("w:p")):
                spacing = _property(_property(paragraph, "w:pPr"), "w:spacing")
                spacing.set(qn("w:before"), "0")
                spacing.set(qn("w:after"), "0")
            if index and column >= 2 and reference == MATRIX_REF:
                text = "".join(t.text or "" for t in cell.iter(qn("w:t")))
                if text in STATUS_COLORS:
                    shading = _property(_property(cell, "w:tcPr"), "w:shd")
                    shading.set(qn("w:val"), "clear")
                    shading.set(qn("w:color"), "auto")
                    shading.set(qn("w:fill"), STATUS_COLORS[text])
                    for name in ("w:themeFill", "w:themeFillShade", "w:themeFillTint"):
                        shading.attrib.pop(qn(name), None)
                    for run in cell.iter(qn("w:r")):
                        color = _property(_property(run, "w:rPr"), "w:color")
                        color.set(qn("w:val"), "17212B")
                        for name in ("w:themeColor", "w:themeShade", "w:themeTint"):
                            color.attrib.pop(qn(name), None)
