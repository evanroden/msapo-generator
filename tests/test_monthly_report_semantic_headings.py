"""Synthetic Word section navigation without changing branded presentation."""
from copy import deepcopy
from io import BytesIO

import pytest

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


@pytest.mark.parametrize('body_outline', [None, 'direct', 'inherited'])
def test_generated_native_word_has_navigable_section_paragraphs(tmp_path, body_outline):
    """Exercise the actual derivative native builder, not just its XML helper."""
    from app.monthly_report_model import (
        BlockSpec, Facility, ReportDraft, ReportPeriod, ReportProfile,
        ResolvedBlock, SectionSpec,
    )
    from app.monthly_report_native_layout import build_native_docx

    source = Document()
    source.add_paragraph("Old Site")
    source.add_paragraph("August 2026")
    source.add_paragraph("Prepared by: Prior Editor")
    activity = source.add_paragraph("MONTHLY ACTIVITY SUMMARY")
    activity.runs[0].bold = True
    source.add_paragraph("Prior monthly activity")
    training = source.add_paragraph("TRAINING SUMMARY")
    training.runs[0].bold = True
    if body_outline is not None:
        for heading in (activity, training):
            if body_outline == 'inherited':
                from docx.enum.style import WD_STYLE_TYPE
                style_name = 'Synthetic Body ' + str(len(source.styles))
                heading.style = source.styles.add_style(style_name, WD_STYLE_TYPE.PARAGRAPH)
                properties = heading.style.element.get_or_add_pPr()
            else:
                properties = heading._p.get_or_add_pPr()
            _set_outline(properties, '9')
    source.add_paragraph("Prior training activity")
    path = tmp_path / "synthetic-native-headings.docx"
    source.save(path)
    original = path.read_bytes()

    sections = (
        SectionSpec("activity", "2", "Monthly Activity Summary",
                    (BlockSpec("activity_summary", "rich_text"),)),
        SectionSpec("training", "11", "Training Summary",
                    (BlockSpec("training_summary", "rich_text"),)),
    )
    profile = ReportProfile("Synthetic contract", "site", "Synthetic Site",
                            (Facility("site", "Synthetic Site"),))
    current = ReportDraft(
        profile, ReportPeriod(2026, 10), "Current Editor", sections,
        (ResolvedBlock("activity_summary", "This month", text="Current synthetic activity"),
         ResolvedBlock("training_summary", "This month", text="Current synthetic training")),
    )
    generated = Document(BytesIO(build_native_docx(current, path)))
    titles = {
        p.text.strip().upper(): p
        for p in generated.paragraphs
        if p.text.strip().upper() in ("MONTHLY ACTIVITY SUMMARY", "TRAINING SUMMARY")
    }
    assert set(titles) == {"MONTHLY ACTIVITY SUMMARY", "TRAINING SUMMARY"}
    assert all(outline(p) == "0" for p in titles.values())
    assert all((p.style.style_id.startswith('SyntheticBody') if body_outline == 'inherited'
                else p.style.style_id == "Normal") and p.runs[0].bold
               for p in titles.values())
    assert all(len(p._p.get_or_add_pPr().findall(qn('w:outlineLvl'))) == 1
               for p in titles.values())
    assert path.read_bytes() == original
    assert "Prior monthly activity" not in "\\n".join(p.text for p in generated.paragraphs)
    assert "Current synthetic activity" in "\\n".join(p.text for p in generated.paragraphs)


def _set_outline(properties, value):
    level = OxmlElement('w:outlineLvl')
    if value is not None:
        level.set(qn('w:val'), value)
    properties.append(level)
    return level


@pytest.mark.parametrize('value', ['9', '10', '-1', 'not-a-level', '', None])
@pytest.mark.parametrize('inherited', [False, True])
def test_body_text_and_invalid_levels_do_not_suppress_section_navigation(value, inherited):
    from docx.enum.style import WD_STYLE_TYPE
    document = Document()
    custom = document.styles.add_style('Synthetic Body Outline', WD_STYLE_TYPE.PARAGRAPH)
    heading = document.add_paragraph('TRAINING SUMMARY', style=custom)
    target = custom.element.get_or_add_pPr() if inherited else heading._p.get_or_add_pPr()
    _set_outline(target, value)
    original, positions, owners = selection(document, (heading, 'training'))
    style_before = custom.element.xml
    assert mark_native_section_headings(document, original, positions, owners, {'training'}) == ('training',)
    assert outline(heading) == '0'
    assert len(heading._p.get_or_add_pPr().findall(qn('w:outlineLvl'))) == 1
    assert custom.element.xml == style_before
    assert mark_native_section_headings(document, original, positions, owners, {'training'}) == ()


@pytest.mark.parametrize('value', [str(level) for level in range(9)])
@pytest.mark.parametrize('inherited', [False, True])
def test_valid_outline_levels_are_preserved(value, inherited):
    from docx.enum.style import WD_STYLE_TYPE
    document = Document()
    custom = document.styles.add_style('Synthetic Valid Outline', WD_STYLE_TYPE.PARAGRAPH)
    heading = document.add_paragraph('TRAINING SUMMARY', style=custom)
    target = custom.element.get_or_add_pPr() if inherited else heading._p.get_or_add_pPr()
    _set_outline(target, value)
    original, positions, owners = selection(document, (heading, 'training'))
    before = document.element.body.xml
    assert mark_native_section_headings(document, original, positions, owners, {'training'}) == ()
    assert document.element.body.xml == before


def test_body_text_override_beats_named_heading_style_and_inherited_heading_level():
    from docx.enum.style import WD_STYLE_TYPE
    for direct in (False, True):
        document = Document()
        custom = document.styles.add_style('Synthetic Override', WD_STYLE_TYPE.PARAGRAPH)
        custom.base_style = document.styles['Heading 1']
        heading = document.add_paragraph('TRAINING SUMMARY', style='Heading 1' if direct else custom)
        _set_outline(heading._p.get_or_add_pPr() if direct else custom.element.get_or_add_pPr(), '9')
        original, positions, owners = selection(document, (heading, 'training'))
        assert mark_native_section_headings(document, original, positions, owners, {'training'}) == ('training',)
        assert outline(heading) == '0'
        assert len(heading._p.get_or_add_pPr().findall(qn('w:outlineLvl'))) == 1
