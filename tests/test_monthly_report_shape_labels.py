"""A39 synthetic Word shape inventory: source labels are not editable layout.

Fixtures are generated in memory. No client, restricted drawing or private
report content is present in this test module.
"""
from hashlib import sha256
from types import SimpleNamespace

from docx import Document
from docx.oxml import parse_xml
import pytest

from app.monthly_report_import import ImportError, ImportMapping, inspect_docx, map_items
from app.monthly_report_sections import section_reviews
from app.monthly_report_shape_labels import collect_drawing_labels, source_review_lines
from app.monthly_report_start_import import source_sites

NAMESPACES = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup" '
)


def _pict(*, grouped=True, empty=False):
    words = '' if empty else (
        '<v:shape id="title" style="left:18pt;top:32pt;width:200pt">'
        '<v:textbox><w:txbxContent><w:p><w:r>'
        '<w:t>November 2026</w:t>'
        '</w:r></w:p></w:txbxContent></v:textbox></v:shape>'
        '<v:shape id="client" style="left:18pt;top:54pt">'
        '<v:textbox><w:txbxContent><w:p><w:r>'
        '<w:t>Synthetic client heading</w:t>'
        '</w:r></w:p></w:txbxContent></v:textbox></v:shape>'
    )
    prefix = '<v:group id="cover-group" style="width:300pt;height:80pt">' if grouped else ''
    suffix = '</v:group>' if grouped else ''
    return parse_xml(
        '<w:r ' + NAMESPACES + '><w:pict>' + prefix
        + '<v:rect id="decorative-band" fillcolor="#082b23" '
          'style="width:300pt;height:18pt" stroked="f"/>'
        + words + suffix + '</w:pict></w:r>'
    )


def _modern_group():
    return parse_xml(
        '<w:r ' + NAMESPACES + '><w:drawing>'
        '<wp:anchor><wp:positionH relativeFrom="page"><wp:posOffset>914400</wp:posOffset>'
        '</wp:positionH><wp:positionV relativeFrom="margin"><wp:posOffset>1828800</wp:posOffset>'
        '</wp:positionV><a:graphic><a:graphicData '
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup">'
        '<wpg:wgp><wps:wsp><wps:txbx><w:txbxContent>'
        '<w:p><w:r><w:t>Owner: Synthetic team</w:t></w:r></w:p>'
        '</w:txbxContent></wps:txbx></wps:wsp>'
        '<wps:wsp><wps:spPr/><a:p><a:r><a:t>Group node B</a:t></a:r></a:p>'
        '</wps:wsp></wpg:wgp></a:graphicData></a:graphic>'
        '</wp:anchor></w:drawing></w:r>'
    )


def _frame(label):
    return parse_xml(
        '<w:r ' + NAMESPACES + '><w:pict>'
        '<v:shape id="body-frame" style="left:36pt;top:12pt">'
        '<v:textbox><w:txbxContent><w:p><w:r>'
        '<w:t>' + label + '</w:t>'
        '</w:r></w:p></w:txbxContent></v:textbox>'
        '</v:shape></w:pict></w:r>'
    )


def _object():
    return parse_xml(
        '<w:r ' + NAMESPACES + '><w:object w:dxaOrig="1200" w:dyaOrig="600">'
        '<v:shape id="unknown-embedded" style="width:35pt;height:35pt"/>'
        '</w:object></w:r>'
    )


def _smartart_unknown():
    return parse_xml(
        '<w:r ' + NAMESPACES + '><w:drawing><wp:anchor>'
        '<wp:docPr id="11" name="Synthetic diagram" '
        'descr="Synthetic process flow (image description)"/>'
        '<a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/diagram">'
        '</a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>'
    )


def _fixture(tmp_path):
    doc = Document()
    doc.add_paragraph("Operations and Maintenance Monthly Review — November 2026")
    doc.add_paragraph("Synthetic Alpha Facility")
    doc.add_paragraph("Prepared by: Synthetic Operator")
    cover = doc.add_paragraph("Ordinary cover caption")
    cover._p.append(_pict())
    doc.add_paragraph()._p.append(_modern_group())
    doc.add_paragraph("TABLE OF CONTENTS")
    doc.add_paragraph()._p.append(_frame("Synthetic contents notice"))
    doc.sections[0].footer.paragraphs[0]._p.append(_frame("Synthetic footer frame"))

    doc.add_heading("Monthly Activity Summary", level=1)
    body = doc.add_paragraph("Visible body report prose.")
    body._p.append(_frame("Unrelated Colony Facility"))
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Unit"
    table.cell(0, 1).text = "Condition"
    table.cell(1, 0).text = "Synthetic AHU"
    table.cell(1, 1).text = "Inspected"
    doc.add_paragraph()._p.append(_object())
    doc.add_paragraph()._p.append(_smartart_unknown())
    source = tmp_path / "a39-synthetic.docx"
    doc.save(source)
    return source


def _unsupported(inspection):
    return [item for item in inspection.items if item.kind == "unsupported"]


def test_grouped_vml_and_drawingml_labels_have_distinct_source_regions(tmp_path):
    source = _fixture(tmp_path)
    original = source.read_bytes()
    result = inspect_docx(source)
    assert result.sha256 == sha256(original).hexdigest()
    assert source.read_bytes() == original

    labels = [label for item in result.items for label in item.drawing_labels]
    by_text = {label.text: label for label in labels}
    for expected in (
        "November 2026", "Synthetic client heading", "Owner: Synthetic team",
        "Group node B", "Synthetic footer frame", "Synthetic contents notice",
        "Unrelated Colony Facility",
    ):
        assert expected in by_text, expected
    assert by_text["November 2026"].object_type == "VML text box"
    assert by_text["November 2026"].artwork_relationship == "grouped drawing"
    assert by_text["November 2026"].confidence == "high"
    assert "Word section 1 (not physical page)" in by_text["November 2026"].region
    assert "VML frame" in by_text["November 2026"].region
    assert by_text["Owner: Synthetic team"].object_type == "DrawingML text box"
    assert "horizontal 1.00 in from page" in by_text["Owner: Synthetic team"].region
    assert "vertical 2.00 in from margin" in by_text["Owner: Synthetic team"].region
    assert by_text["Group node B"].source == "drawing_text"
    assert by_text["Group node B"].confidence == "medium"
    assert "footer" in by_text["Synthetic footer frame"].region
    assert len({label.native_reference for label in labels}) == len(labels)
    assert all(label.native_reference.startswith("word/") for label in labels)


def test_readable_labels_remain_review_only_and_table_remains_native(tmp_path):
    inspection = inspect_docx(_fixture(tmp_path))
    groups = {section.key: section for section in section_reviews(inspection)}
    assert "cover" in groups and "activity" in groups
    assert any("November 2026" in item.text for item in _unsupported(inspection))
    assert any("Group node B" in item.text for item in _unsupported(inspection))
    assert not any(item.kind == "text" and "Unrelated Colony Facility" in item.text
                   for item in inspection.items if item.section == "activity")
    assert any(item.kind == "text" and "Visible body report prose." in item.text
                   for item in inspection.items if item.section == "activity")
    assert any(item.kind == "table" and item.rows == (
        ("Unit", "Condition"), ("Synthetic AHU", "Inspected"))
        for item in inspection.items)
    labels = next(item for item in _unsupported(inspection)
                  if any(label.text == "November 2026" for label in item.drawing_labels))
    assert any("Exact source label: November 2026" in line for line in source_review_lines(labels))
    # This is evidence of source text, not a raster/OCR editability assertion.
    assert all(item.suggested_slot == "" for item in _unsupported(inspection))


def test_unknown_object_and_unproved_smartart_remain_unapproved(tmp_path):
    source = _fixture(tmp_path)
    before = source.read_bytes()
    result = inspect_docx(source)
    assert any("Embedded or unsupported Word object" in item.note
               for item in _unsupported(result))
    assert any("Unmapped native SmartArt" in item.note
               for item in _unsupported(result))
    metadata = [label for item in _unsupported(result) for label in item.drawing_labels
                if label.text == "Synthetic process flow (image description)"]
    assert len(metadata) == 1 and metadata[0].source == "alternative_text"
    assert metadata[0].confidence == "metadata"  # Descriptive, not OCR or visible text.
    assert source.read_bytes() == before


def test_decorative_only_vml_is_not_silently_discarded(tmp_path):
    doc = Document()
    doc.add_paragraph("Synthetic cover title and date, November 2026")
    doc.add_paragraph()._p.append(_pict(grouped=False, empty=True))
    doc.add_heading("Monthly Activity Summary", 1)
    doc.add_paragraph("Synthetic completed work, clearly separate from decoration")
    path = tmp_path / "decorative.docx"
    doc.save(path)
    result = inspect_docx(path)
    assert any(i.kind == "unsupported" and "Unlabelled VML artwork" in i.note
               and not i.drawing_labels for i in result.items)
    assert any(i.kind == "text" and i.text == "Synthetic cover title and date, November 2026"
               for i in result.items)
    assert any(i.kind == "text" and "Synthetic completed work" in i.text
               for i in result.items)


def test_site_and_period_cannot_be_inferred_from_body_shape(tmp_path):
    result = inspect_docx(_fixture(tmp_path))
    sites = (
        SimpleNamespace(key="alpha", title="Synthetic Alpha Facility", aliases=()),
        SimpleNamespace(key="colony", title="Unrelated Colony Facility", aliases=()),
    )
    assert [site.key for site in source_sites(result, sites)] == ["alpha"]
    assert all("Unrelated Colony Facility" not in candidate for candidate in result.title_candidates)
    assert any("November 2026" in candidate for candidate in result.title_candidates)


def test_duplicate_labels_each_keep_an_occurrence_reference():
    unit = parse_xml(
        '<w:p ' + NAMESPACES + '>'
        '<w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
        '<w:p><w:r><w:t>Duplicate</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>'
        '<w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
        '<w:p><w:r><w:t>Duplicate</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>'
    )
    evidence = collect_drawing_labels(unit, part="word/document.xml", position=7, word_section=2)
    assert [item.text for item in evidence] == ["Duplicate", "Duplicate"]
    assert evidence[0].native_reference != evidence[1].native_reference


def test_missing_or_malformed_source_and_label_budget_fail_closed(tmp_path):
    with pytest.raises(OSError):
        inspect_docx(tmp_path / "missing.docx")
    damaged = tmp_path / "broken.docx"
    damaged.write_bytes(b"not a Word package")
    with pytest.raises((ImportError, __import__("zipfile").BadZipFile)):
        inspect_docx(damaged)

    too_long = parse_xml(
        '<w:p ' + NAMESPACES + '><w:r><w:pict><v:shape><v:textbox>'
        '<w:txbxContent><w:p><w:r><w:t>' + "x" * 16001 +
        '</w:t></w:r></w:p></w:txbxContent></v:textbox>'
        '</v:shape></w:pict></w:r></w:p>'
    )
    with pytest.raises(ValueError, match="bounded label inventory"):
        collect_drawing_labels(too_long, part="word/document.xml", position=1, word_section=1)


def test_unsupported_group_cannot_be_mapped_to_public_output(tmp_path):
    path = _fixture(tmp_path)
    raw = path.read_bytes()
    inspection = inspect_docx(path)
    candidate = next(item for item in inspection.items
                     if item.kind == "unsupported" and "Group node B" in item.text)
    with pytest.raises(ImportError, match="Unsupported items must remain in review"):
        map_items(path, inspection, (ImportMapping(candidate.id, "activity_summary"),))
    assert path.read_bytes() == raw


def test_picture_alt_text_is_not_misattributed_to_neighbor_text_frame():
    unit = parse_xml(
        '<w:p ' + NAMESPACES + '><w:r><w:drawing>'
        '<wp:anchor><wp:docPr id="1" name="frame" title="Actual frame description"/>'
        '<a:graphic><a:graphicData '
        'uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">'
        '<wps:wsp><wps:txbx><w:txbxContent><w:p><w:r><w:t>Frame A</w:t>'
        '</w:r></w:p></w:txbxContent></wps:txbx></wps:wsp>'
        '</a:graphicData></a:graphic></wp:anchor>'
        '</w:drawing></w:r>'
        '<w:r><w:drawing><wp:anchor>'
        '<wp:docPr id="2" name="picture" title="Unrelated picture alt"/>'
        '<a:graphic><a:graphicData '
        'uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '</a:graphicData></a:graphic></wp:anchor></w:drawing></w:r></w:p>'
    )
    labels = collect_drawing_labels(unit, part="word/document.xml", position=9, word_section=1)
    assert {label.text for label in labels} == {"Frame A", "Actual frame description"}
    meta = next(label for label in labels if label.text == "Actual frame description")
    assert meta.source == "alternative_text" and meta.confidence == "metadata"
