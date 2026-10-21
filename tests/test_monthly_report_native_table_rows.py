"""Native-design data rows copy a source data row, never the header (Refs #304).

In master mode each master table was blanked to its header before current rows
were written, so every Sub-Contractor row took the header's dark fill and bold
text. A source table with only a header row now yields plain data rows.
Synthetic values only.
"""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import RGBColor
from lxml import etree

from app import monthly_report_designs as designs
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import (ReportPeriod, ResolvedBlock, default_sections, synthetic_draft,
                                      synthetic_profiles)
from app.monthly_report_native_layout import _table

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HEADER_FILL, DATA_FILL = "082B23", "D2E7DF"
VENDORS = (("Synthetic North", "Controls", "Synthetic Vendor A", "Synthetic Contact", "202-555-0101", "Yes"),
           ("Synthetic South", "", "Synthetic Vendor B", "", "", ""))


def _shade(cell, fill):
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _master(tmp_path, *, data_fill=None, header_only=False):
    """A synthetic company master whose Sub-Contractor table has a dark, bold, white header."""
    path = tmp_path / "master.docx"
    document = Document()
    document.add_paragraph("Operations and Maintenance Monthly Review")
    for section in default_sections():
        document.add_heading(section.title, 1)
        document.add_paragraph("Source-only content")
        if section.key == "subcontractors":
            columns = section.blocks[0].columns
            table = document.add_table(rows=1 if header_only else 2, cols=len(columns))
            for cell, column in zip(table.rows[0].cells, columns):
                cell.text = column.title
                _shade(cell, HEADER_FILL)
                run = cell.paragraphs[0].runs[0]
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            if not header_only:
                table.rows[1].cells[0].text = "Synthetic Old Vendor"
                if data_fill:
                    for cell in table.rows[1].cells:
                        _shade(cell, data_fill)
    document.save(path)
    return path


def _vendor_rows(monkeypatch, tmp_path, **master):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "data"))
    designs.install_master(_master(tmp_path, **master), actor="Synthetic Editor", expected_revision=0)
    draft = synthetic_draft(designs.pin(replace(synthetic_profiles()[0], contract="Synthetic Client")),
                            ReportPeriod(2026, 9))
    standard = next(section for section in default_sections() if section.key == "subcontractors")
    draft = replace(draft, sections=tuple(standard if section.key == standard.key else section
                                          for section in draft.sections),
                    blocks=tuple(block for block in draft.blocks if block.key != "demo_subcontractors")
                    + (ResolvedBlock(standard.blocks[0].key, "This month", rows=VENDORS),))
    body = etree.fromstring(ZipFile(BytesIO(_build_docx(draft))).read("word/document.xml"))
    table = next(table for table in body.iter(W + "tbl")
                 if "Synthetic Vendor A" in "".join(node.text or "" for node in table.iter(W + "t")))
    return table.findall(W + "tr")


def _look(row):
    """Effective direct look; an explicit "off" or automatic colour is no emphasis."""
    fills = {node.get(W + "fill") for node in row.iter(W + "shd")}
    return {"fills": fills, "bold": any(node.get(W + "val") not in ("0", "false") for node in row.iter(W + "b")),
            "colors": {node.get(W + "val") for node in row.iter(W + "color")} - {"auto"}}


def test_master_data_rows_do_not_copy_the_header_fill(monkeypatch, tmp_path):
    header, *data = _vendor_rows(monkeypatch, tmp_path)
    assert _look(header)["fills"] == {HEADER_FILL} and _look(header)["bold"]
    assert len(data) == 2
    assert all(_look(row) == {"fills": set(), "bold": False, "colors": set()} for row in data)


def test_master_data_rows_keep_the_master_data_row_look(monkeypatch, tmp_path):
    _, *data = _vendor_rows(monkeypatch, tmp_path, data_fill=DATA_FILL)
    assert all(_look(row)["fills"] == {DATA_FILL} and not _look(row)["bold"] for row in data)


def test_a_header_only_source_table_yields_plain_data_rows(monkeypatch, tmp_path):
    header, *data = _vendor_rows(monkeypatch, tmp_path, header_only=True)
    assert _look(header) == {"fills": {HEADER_FILL}, "bold": True, "colors": {"FFFFFF"}}
    assert all(_look(row) == {"fills": set(), "bold": False, "colors": set()} for row in data)
    assert ["".join(node.text or "" for node in row.iter(W + "t")) for row in data] == [
        "".join(values) for values in VENDORS]


def _xml_table(*rows):
    body = "".join("<w:tr>" + "".join(f'<w:tc><w:tcPr><w:shd w:fill="{fill}"/></w:tcPr><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'
                                      for text, fill in row) + "</w:tr>" for row in rows)
    grid = '<w:gridCol w:w="4000"/>' * max(len(row) for row in rows)
    return parse_xml(f'<w:tbl xmlns:w="{W[1:-1]}"><w:tblGrid>{grid}</w:tblGrid>{body}</w:tbl>')


def test_a_two_level_header_is_not_reused_as_a_data_row():
    table = _xml_table((("Synthetic Group", HEADER_FILL),), (("Name", HEADER_FILL), ("Detail", HEADER_FILL)))
    _table(table, ("Name", "Detail"), (("Synthetic A", "One"),))
    data = table.findall(W + "tr")[-1]
    assert "".join(node.text for node in data.iter(W + "t")) == "Synthetic AOne"
    assert not list(data.iter(W + "shd"))


def test_a_continuation_frame_still_copies_its_own_data_row():
    table = _xml_table((("Synthetic A", DATA_FILL), ("One", DATA_FILL)))
    _table(table, ("Name", "Detail"), (("Synthetic B", "Two"),), continuation=True)
    rows = table.findall(W + "tr")
    assert len(rows) == 1 and {node.get(W + "fill") for node in rows[0].iter(W + "shd")} == {DATA_FILL}


def test_copied_data_rows_drop_the_source_rows_position_markers():
    template = parse_xml(
        f'<w:tbl xmlns:w="{W[1:-1]}"><w:tblGrid><w:gridCol w:w="4000"/></w:tblGrid>'
        '<w:tr><w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:trPr><w:cnfStyle w:val="010000000000" w:lastRow="1"/></w:trPr><w:tc><w:tcPr>'
        f'<w:cnfStyle w:val="000010000000" w:oddHBand="1"/><w:shd w:fill="{DATA_FILL}"/></w:tcPr>'
        '<w:p><w:pPr><w:cnfStyle w:val="010000000000"/></w:pPr><w:r><w:t>Old</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    table = _xml_table((("Name", HEADER_FILL),))
    _table(table, ("Name",), (("Synthetic A",), ("Synthetic B",)), template=template)
    data = table.findall(W + "tr")[1:]
    assert len(data) == 2 and not [node for row in data for node in row.iter(W + "cnfStyle")]
    assert all({node.get(W + "fill") for node in row.iter(W + "shd")} == {DATA_FILL} for row in data)


def test_a_header_style_cannot_make_plain_data_rows_bold_or_white():
    table = parse_xml(
        f'<w:tbl xmlns:w="{W[1:-1]}"><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/></w:tblGrid><w:tr>'
        '<w:tc><w:p><w:pPr><w:pStyle w:val="SyntheticTableHeading"/></w:pPr><w:r><w:rPr><w:rStyle w:val="SyntheticHeadingChar"/>'
        '<w:color w:val="FFFFFF" w:themeColor="background1"/></w:rPr><w:t>Name</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:pPr><w:pStyle w:val="SyntheticTableHeading"/></w:pPr></w:p></w:tc></w:tr></w:tbl>')
    _table(table, ("Name", "Detail"), (("Synthetic A", "One"),))
    data = table.findall(W + "tr")[-1]
    assert not list(data.iter(W + "rStyle")) and [node.get(W + "val") for node in data.iter(W + "pStyle")] == [
        "SyntheticTableHeading", "SyntheticTableHeading"]
    for cell, text in zip(data.findall(W + "tc"), ("Synthetic A", "One")):
        run = next(run for run in cell.iter(W + "r") if run.find(W + "t") is not None and run.find(W + "t").text)
        properties = run.find(W + "rPr")
        assert run.find(W + "t").text == text
        assert [properties.find(W + name).get(W + "val") for name in ("b", "bCs", "caps")] == ["0", "0", "0"]
        assert dict(properties.find(W + "color").attrib) == {W + "val": "auto"}


def test_copied_rows_carry_no_source_payload():
    old = "Synthetic Old Client"
    template = parse_xml(
        f'<w:tbl xmlns:w="{W[1:-1]}"><w:tblGrid><w:gridCol w:w="4000"/></w:tblGrid>'
        f'<w:tr><w:tc><w:p><w:bookmarkStart w:id="1" w:name="{old.replace(" ", "_")}_Header"/>'
        '<w:r><w:t>Name</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p></w:tc></w:tr>'
        f'<w:tr><w:trPr><w:ins w:id="2" w:author="{old} Editor" w:date="2026-01-01T00:00:00Z"/></w:trPr><w:tc>'
        f'<w:tcPr><w:cellIns w:id="5" w:author="{old} Editor"/></w:tcPr>'
        f'<w:p><w:permStart w:id="3" w:edGrp="everyone"/><w:bookmarkStart w:id="4" w:name="{old.replace(" ", "_")}"/>'
        f'<w:r><w:rPr><w:i/></w:rPr><w:t>{old}</w:t></w:r><w:fldSimple w:instr="AUTHOR"><w:r><w:t>{old}</w:t></w:r></w:fldSimple>'
        '<w:bookmarkEnd w:id="4"/><w:permEnd w:id="3"/></w:p>'
        f'<w:p><w:r><w:t>{old} second line</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    table = _xml_table((("Name", HEADER_FILL),))
    _table(table, ("Name",), (("Synthetic A",), ("Synthetic B",)), template=template)
    _table(template, ("Name",), (("Synthetic C",),))  # the non-master path rewrites the source table itself
    for result in (table, template):
        markup = etree.tostring(result, encoding="unicode")
        assert "Old" not in markup and "author" not in markup
        assert not [node for tag in ("bookmarkStart", "permStart", "fldSimple", "ins")
                    for node in result.iter(W + tag)]
        assert all(len(cell.findall(W + "p")) == 1 for cell in result.iter(W + "tc"))
    assert [row.find(f".//{W}i") is not None for row in table.findall(W + "tr")] == [False, True, True]


def test_a_two_row_marked_header_of_equal_width_is_not_data():
    header = "".join(f'<w:tc><w:tcPr><w:shd w:fill="{HEADER_FILL}"/></w:tcPr><w:p><w:r><w:rPr><w:b/></w:rPr>'
                     f'<w:t>{text}</w:t></w:r></w:p></w:tc>' for text in ("Synthetic", "Group"))
    marked = '<w:trPr><w:tblHeader/></w:trPr>'
    table = parse_xml(f'<w:tbl xmlns:w="{W[1:-1]}"><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/></w:tblGrid>'
                      f'<w:tr>{marked}{header}</w:tr><w:tr>{marked}{header}</w:tr></w:tbl>')
    _table(table, ("Name", "Detail"), (("Synthetic A", "One"),))
    assert _look(table.findall(W + "tr")[-1]) == {"fills": set(), "bold": False, "colors": set()}


def test_a_dropped_middle_column_never_lends_its_cell_to_a_retained_column():
    fills = ("C0C0C1", "C0C0C2", "FF0000", "C0C0C4")  # column 2 is an excluded price column
    template = _xml_table(tuple((f"Head {n}", HEADER_FILL) for n in range(4)),
                          tuple((f"Old {n}", fill) for n, fill in enumerate(fills)))
    table = deepcopy(template)
    _table(table, ("A", "B", "D"), (), physical_indices=(0, 1, 3))  # master blanking pass
    _table(table, ("A", "B", "D"), (("1", "2", "4"),), physical_indices=(0, 1, 3), template=template)
    header, data = table.findall(W + "tr")
    assert [_text(cell) for cell in header.findall(W + "tc")] == ["A", "B", "D"]
    assert [next(cell.iter(W + "shd")).get(W + "fill") for cell in data.findall(W + "tc")] == [
        "C0C0C1", "C0C0C2", "C0C0C4"]


def _text(element):
    return "".join(node.text or "" for node in element.iter(W + "t"))
