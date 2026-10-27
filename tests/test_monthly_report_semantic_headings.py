"""Synthetic Word section navigation without changing branded presentation."""
from copy import deepcopy
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from app.monthly_report_semantic_headings import mark_native_section_headings


def outline(paragraph):
    properties = paragraph._p.find(qn("w:pPr"))
    if properties is None:
        return None
    level = properties.find(qn("w:outlineLvl"))
    return level.get(qn("w:val")) if level is not None else None


def selection(document, *pairs):
    original = list(document.element.body)
    positions = set()
    by_position = {}
    for paragraph, key in pairs:
        position = original.index(paragraph._p) + 1
        positions.add(position)
        by_position[position] = key
    return original, positions, by_position


def test_native_section_headings_gain_outline_without_changing_visible_formatting():
    document = Document()
    cover = document.add_paragraph("Synthetic cover title")
    contents = document.add_paragraph("Table of contents")
    divider = document.add_paragraph("WATER TREATMENT REPORTS")
    water = document.add_paragraph("7 Water Treatment Reports")
    water.runs[0].bold = True
    water.runs[0].italic = True
    notes = document.add_paragraph("Synthetic water report table label")
    issue = document.add_paragraph("EQUIPMENT PERFORMANCE ISSUES")
    issue.runs[0].bold = True
    before = [(paragraph.text, paragraph.style.style_id,
               deepcopy(paragraph._p).find(qn("w:r")))
              for paragraph in (cover, contents, divider, water, notes, issue)]
    original, positions, owners = selection(
        document, (cover, "cover"), (contents, "cover"),
        (divider, "water"), (water, "water"), (notes, "water"),
        (issue, "issues"),
    )
    marked = mark_native_section_headings(
        document, original, positions, owners, {"water", "issues"}
    )
    assert marked == ("water", "issues")
    assert outline(water) == outline(issue) == "0"
    assert all(outline(p) is None for p in (cover, contents, divider, notes))
    for (text, style, run), paragraph in zip(
            before, (cover, contents, divider, water, notes, issue)):
        assert paragraph.text == text
        assert paragraph.style.style_id == style
        assert etree.tostring(paragraph._p.find(qn("w:r")), method="c14n", exclusive=True) == etree.tostring(run, method="c14n", exclusive=True)

    snapshot = BytesIO()
    document.save(snapshot)
    recovered = Document(BytesIO(snapshot.getvalue()))
    assert [(p.text, outline(p)) for p in recovered.paragraphs if outline(p) == "0"] == [
        ("7 Water Treatment Reports", "0"),
        ("EQUIPMENT PERFORMANCE ISSUES", "0"),
    ]
    assert mark_native_section_headings(
        document, original, positions, owners, {"water", "issues"}
    ) == ()


def test_existing_word_heading_style_is_not_given_duplicate_outline():
    document = Document()
    branded = document.add_heading("MBCx Reports", 1)
    repeated = document.add_paragraph("MBCX REPORTS")
    original, positions, owners = selection(
        document, (branded, "mbcx"), (repeated, "mbcx"))
    unchanged = document.element.body.xml
    assert not mark_native_section_headings(
        document, original, positions, owners, {"mbcx"})
    assert document.element.body.xml == unchanged
    assert outline(branded) is None  # Heading 1 is already semantic via its style.
    assert outline(repeated) is None


def test_textbox_art_table_cells_and_excluded_sections_are_not_promoted():
    document = Document()
    art = document.add_paragraph("MBCX REPORTS")
    drawing = OxmlElement("w:drawing")
    art.add_run()._r.append(drawing)
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0).paragraphs[0]
    cell.add_run("WATER TREATMENT REPORTS")
    water = document.add_paragraph("WATER TREATMENT REPORTS")
    issue = document.add_paragraph("EQUIPMENT PERFORMANCE ISSUES")
    original, positions, owners = selection(
        document, (art, "mbcx"), (water, "water"), (issue, "issues"))
    # Table cells aren't top-level children; even a forged position cannot
    # promote their label into the navigation outline.
    assert mark_native_section_headings(
        document, original, positions, owners, {"issues", "mbcx"}) == ("issues",)
    assert outline(art) is None
    assert outline(water) is None
    assert outline(cell) is None
    assert outline(issue) == "0"


def test_custom_style_outline_is_respected_as_existing_navigation():
    document = Document()
    from docx.enum.style import WD_STYLE_TYPE
    custom = document.styles.add_style("Synthetic Branded Heading", WD_STYLE_TYPE.PARAGRAPH)
    paragraph_style = custom.element.get_or_add_pPr()
    level = OxmlElement("w:outlineLvl")
    level.set(qn("w:val"), "0")
    paragraph_style.append(level)
    heading = document.add_paragraph("TRAINING SUMMARY", style=custom)
    plain = document.add_paragraph("Training Summary")
    original, positions, owners = selection(
        document, (heading, "training"), (plain, "training"))
    assert mark_native_section_headings(
        document, original, positions, owners, {"training"}) == ()
    assert outline(heading) is None
    assert outline(plain) is None
