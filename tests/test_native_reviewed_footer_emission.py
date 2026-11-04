"""Reviewed footer words reach their original parts without becoming page caches."""
from copy import deepcopy
from dataclasses import replace
from io import BytesIO

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
import pytest
from streamlit.testing.v1 import AppTest
from conftest import requires_libreoffice

from app import monthly_report_library as library
from app.monthly_report_import import (
    ImportMapping, _remove_page_field_results, _text, imported_draft, inspect_docx, map_items,
)
from app.monthly_report_model import ReportPeriod, synthetic_profiles
from app.monthly_report_native_layout import _build_native_docx, build_native_docx
from app.monthly_report_sections import build_section_import, section_reviews


OLD = 'Old synthetic address'
CURRENT = 'Current synthetic address'
CANARY = 'UNSELECTED-SYNTHETIC-ADDRESS'
REVIEW = '''
import streamlit as st
from app.monthly_report_section_ui import _section_card
from app.monthly_report_ui import _field
from app.monthly_report_model import ReportPeriod
plans=st.session_state.setdefault('plans',{})
for section in st.session_state['sections']:
    _section_card(section,st.session_state['path'],st.session_state['inspection'],
                  ReportPeriod(2026,9),'footer_review',_field,plans,True)
'''
COVER = '''
from dataclasses import replace
import streamlit as st
from app.monthly_report_cover_ui import render_cover
from app.monthly_report_ui import _field
draft=st.session_state['draft']
blocks=render_cover(draft,{b.key:b for b in draft.blocks},'footer_probe',{},_field,lambda ref:None)
footer=blocks.get('footer_text')
# The existing guided parent copies this exact accepted footer value to address_line.
st.session_state['draft']=replace(draft,blocks=tuple(blocks.values()),
    address_line=footer.text if footer.source!='Omit' else '')
'''


def field(paragraph, instruction, cached, *, simple=False):
    if simple:
        node = OxmlElement('w:fldSimple')
        node.set(qn('w:instr'), ' ' + instruction + ' ')
        run = OxmlElement('w:r')
        text = OxmlElement('w:t'); text.text = cached
        run.append(text); node.append(run); paragraph._p.append(node)
        return
    for kind in ('begin', 'separate', 'end'):
        if kind == 'separate':
            text = OxmlElement('w:instrText'); text.text = ' ' + instruction + ' '
            paragraph.add_run()._r.append(text)
        node = OxmlElement('w:fldChar'); node.set(qn('w:fldCharType'), kind)
        paragraph.add_run()._r.append(node)
        if kind == 'separate':
            paragraph.add_run(cached)


def source(tmp_path, *, corporate=False, paragraphs=1, fields='', parts=False):
    document = Document()
    document.add_heading('MONTHLY ACTIVITY SUMMARY', 1)
    document.add_paragraph('Synthetic current activity.')
    section = document.sections[0]
    section.header.paragraphs[0].text = CANARY
    paragraph = section.footer.paragraphs[0]
    paragraph.paragraph_format.left_indent = Inches(.27)
    if fields == 'before':
        field(paragraph, 'PAGE', '7')
        field(paragraph, 'NUMPAGES', '23', simple=True)
    paragraph.add_run(OLD + (' | enfrasolutions.com' if corporate else '')).bold = True
    if fields == 'after':
        field(paragraph, 'PAGE', '7')
        field(paragraph, 'NUMPAGES', '23', simple=True)
    for index in range(1, paragraphs):
        section.footer.add_paragraph('Old synthetic address line ' + str(index + 1))
    if parts:
        section.different_first_page_header_footer = True
        document.settings.odd_and_even_pages_header_footer = True
        section.first_page_footer.paragraphs[0].text = 'Old first-page address'
        section.even_page_footer.paragraphs[0].text = 'Old even-page address'
    document.add_section(WD_SECTION_START.NEW_PAGE)
    document.add_heading('TRAINING SUMMARY', 1)
    document.add_paragraph('Synthetic current training.')
    if parts:
        second = document.sections[1]
        second.footer.is_linked_to_previous = False
        second.footer.paragraphs[0].text = 'Old second-section address'
    path = tmp_path / 'synthetic-footer.docx'
    document.save(path)
    return path


def imported(path, *, normal_review=False, only_part=None):
    inspection = inspect_docx(path)
    if normal_review:
        app = AppTest.from_string(REVIEW)
        for key, value in (('path', path), ('inspection', inspection),
                           ('sections', section_reviews(inspection))):
            app.session_state[key] = value
        app.run()
        assert not app.exception
        plans = tuple(app.session_state['plans'].values())
        mapped, _ = build_section_import(path, inspection, plans)
    else:
        selected = [item for item in inspection.items
                    if item.kind == 'text' and item.suggested_slot in
                    ('footer_text', 'activity_summary', 'training_summary')
                    and (item.suggested_slot != 'footer_text' or only_part is None or item.part == only_part)]
        mapped = map_items(path, inspection, tuple(ImportMapping(i.id, i.suggested_slot) for i in selected))
    return imported_draft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor', mapped)


def accept_footer(draft, value=CURRENT):
    app = AppTest.from_string(COVER)
    app.session_state['draft'] = draft
    app.run()
    next(b for b in app.button if b.label == 'Edit footer').click().run()
    app.text_area[0].set_value(value).run()
    next(b for b in app.button if b.label == 'Use footer text').click().run()
    assert not app.exception
    result = app.session_state['draft']
    assert result.address_line == value
    assert next(b for b in result.blocks if b.key == 'footer_text').text == value
    return result


def parts(raw, prefix='footer'):
    document = Document(BytesIO(raw))
    return {str(part.partname): part.element for part in document.part.package.parts
            if str(part.partname).startswith('/word/' + prefix) and hasattr(part, 'element')}


def visible_text(element):
    clone = deepcopy(element)
    _remove_page_field_results(clone, [])
    return _text(clone)


@pytest.mark.parametrize('corporate', [False, True])
@pytest.mark.parametrize('paragraphs', [1, 2])
def test_actual_starting_review_and_footer_acceptance_reach_word(tmp_path, corporate, paragraphs):
    path = source(tmp_path, corporate=corporate, paragraphs=paragraphs)
    original = path.read_bytes()
    draft = imported(path, normal_review=True)
    assert next(b for b in draft.blocks if b.key == 'footer_text').references
    edited = accept_footer(draft, CURRENT + '\nSecond current address line')
    output = _build_native_docx(edited, path)
    footer = next(iter(parts(output).values()))
    assert visible_text(footer) == CURRENT + '\nSecond current address line'
    assert sum(CURRENT in (n.text or '') for n in footer.iter(qn('w:t'))) == 1
    assert len(footer.findall(qn('w:p'))) == paragraphs
    assert footer.find('.//' + qn('w:ind')).get(qn('w:left')) == '389'
    assert OLD not in visible_text(footer)
    assert all(CANARY not in visible_text(p) for p in parts(output, 'header').values())
    assert path.read_bytes() == original
    assert tuple(b for b in edited.blocks if b.key != 'footer_text') == tuple(b for b in draft.blocks if b.key != 'footer_text')


def test_accepted_unchanged_plain_footer_is_not_silently_erased(tmp_path):
    path = source(tmp_path)
    draft = imported(path, normal_review=True)
    output = _build_native_docx(draft, path)
    assert [visible_text(p) for p in parts(output).values()] == [OLD]


@pytest.mark.parametrize('corporate', [False, True])
@pytest.mark.parametrize('position', ['before', 'after'])
def test_page_fields_keep_instructions_and_cache_separate_from_current_address(tmp_path, corporate, position):
    path = source(tmp_path, corporate=corporate, fields=position)
    draft = accept_footer(imported(path))
    result = _build_native_docx(draft, path)
    footer = next(iter(parts(result).values()))
    paragraph = footer.find(qn('w:p'))
    assert visible_text(footer) == CURRENT
    assert [n.text.strip() for n in footer.iter(qn('w:instrText'))] == ['PAGE']
    assert [n.get(qn('w:instr')).strip() for n in footer.iter(qn('w:fldSimple'))] == ['NUMPAGES']
    assert [n.text for n in footer.find(qn('w:p')).iter(qn('w:t'))].count('7') == 0
    assert [n.text for n in footer.find(qn('w:p')).iter(qn('w:t'))].count('23') == 0
    # Refreshing fields must not erase the accepted address, even with fields first.
    refreshed = deepcopy(paragraph)
    _remove_page_field_results(refreshed, [])
    assert CURRENT in _text(refreshed)


@pytest.mark.parametrize('selected', [None, 'activity', 'training'])
def test_all_selected_physical_footer_parts_emit_once_and_keep_routing(tmp_path, selected):
    path = source(tmp_path, parts=True)
    draft = accept_footer(imported(path))
    output = _build_native_docx(draft, path, section_key=selected)
    result = parts(output)
    assert result
    assert all(visible_text(p) == CURRENT for p in result.values())
    assert all(sum(CURRENT in (n.text or '') for n in p.iter(qn('w:t'))) == 1 for p in result.values())
    if selected is None:
        assert len(result) == 4
        before = Document(path)
        after = Document(BytesIO(output))
        for a, b in zip(before.sections, after.sections):
            assert a.different_first_page_header_footer == b.different_first_page_header_footer
            for tag in ('headerReference', 'footerReference'):
                assert [n.attrib for n in a._sectPr.findall(qn('w:' + tag))] == [n.attrib for n in b._sectPr.findall(qn('w:' + tag))]


def test_only_explicitly_reviewed_source_part_receives_address(tmp_path):
    path = source(tmp_path, parts=True)
    inspection = inspect_docx(path)
    chosen = next(i.part for i in inspection.items if i.suggested_slot == 'footer_text')
    draft = accept_footer(imported(path, only_part=chosen))
    output = parts(_build_native_docx(draft, path))
    assert visible_text(output['/' + chosen]) == CURRENT
    assert all(not visible_text(value) for key, value in output.items() if key != '/' + chosen)


def test_unselected_paragraph_does_not_steal_the_reviewed_footer_position(tmp_path):
    path = source(tmp_path, paragraphs=2)
    inspection = inspect_docx(path)
    item = next(i for i in inspection.items if i.suggested_slot == 'footer_text' and i.position == 2)
    mapped = map_items(path, inspection, (ImportMapping(item.id, 'footer_text'),))
    draft = imported_draft(synthetic_profiles()[0], ReportPeriod(2026, 9), 'Synthetic Editor', mapped)
    draft = accept_footer(draft)
    footer = next(iter(parts(_build_native_docx(draft, path)).values()))
    assert [visible_text(p) for p in footer.findall(qn('w:p'))] == ['', CURRENT]


@pytest.mark.parametrize('position', ['before', 'after'])
def test_field_result_words_are_not_authorized_footer_content(tmp_path, position):
    path = source(tmp_path, fields=position)
    doc = Document(path)
    paragraph = doc.sections[0].footer.paragraphs[0]
    for text in paragraph._p.iter(qn('w:t')):
        if text.text in ('7', '23'):
            text.text = CANARY
    # Passive packaging flattens unsupported fields; their old cached words
    # must still be cleared by the accepted current footer replacement.
    field(paragraph, 'MERGEFIELD PreviousClient', CANARY)
    field(paragraph, 'DOCPROPERTY PreviousAddress', CANARY, simple=True)
    doc.save(path)
    draft = accept_footer(imported(path))
    result = _build_native_docx(draft, path)
    footer = next(iter(parts(result).values()))
    assert CANARY not in footer.xml and CURRENT in footer.xml
    assert visible_text(footer) == CURRENT


def test_current_manual_address_is_authoritative_and_corporate_fallback_stays_unchanged(tmp_path):
    path = source(tmp_path)
    draft = replace(imported(path), address_line=CURRENT)
    assert [visible_text(p) for p in parts(_build_native_docx(draft, path)).values()] == [CURRENT]
    path = source(tmp_path, corporate=True)
    draft = replace(imported(path), address_line=CURRENT,
                    blocks=tuple(b for b in draft.blocks if b.key != 'footer_text'))
    assert [visible_text(p) for p in parts(_build_native_docx(draft, path)).values()] == [CURRENT]


@pytest.mark.parametrize('fault', ['missing', 'other_source', 'body', 'header', 'omitted'])
def test_unproved_or_omitted_footer_cannot_authorize_source_text_or_arbitrary_placement(tmp_path, fault):
    path = source(tmp_path)
    draft = accept_footer(imported(path))
    footer = next(b for b in draft.blocks if b.key == 'footer_text')
    inspection = inspect_docx(path)
    references = ()
    if fault == 'other_source':
        references = tuple(ref.replace(inspection.sha256, '0' * 64) for ref in footer.references)
    elif fault in ('body', 'header'):
        item = next(i for i in inspection.items if i.kind == 'text' and
                    i.part.startswith('word/document' if fault == 'body' else 'word/header'))
        references = ('docx:' + inspection.sha256 + ':' + item.id,)
    elif fault == 'omitted':
        references = footer.references
    changed = replace(footer, references=references, source='Omit' if fault == 'omitted' else footer.source)
    draft = replace(draft, blocks=tuple(changed if b.key == 'footer_text' else b for b in draft.blocks))
    output = _build_native_docx(draft, path)
    assert all(not visible_text(p) for p in parts(output).values())
    assert all(CURRENT not in visible_text(p) and CANARY not in visible_text(p) for p in parts(output, 'header').values())


@pytest.mark.parametrize('corporate', [False, True])
def test_deliberate_blank_retains_existing_corporate_fallback_policy(tmp_path, corporate):
    path = source(tmp_path, corporate=corporate)
    draft = accept_footer(imported(path), '')
    output = _build_native_docx(draft, path)
    assert [visible_text(p) for p in parts(output).values()] == ['ENFRA | enfrasolutions.com' if corporate else '']


def test_public_storage_history_and_native_word_retain_accepted_footer(monkeypatch, tmp_path):
    """Enabled real Linux storage/public output; no fake locks or skips."""
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    path = source(tmp_path)
    original = path.read_bytes()
    draft = imported(path, normal_review=True)
    first = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Editor')
    edited = accept_footer(library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft)
    library.save_snapshot(edited, expected_revision=first.revision, entered_editor='Synthetic Editor')
    reopened = library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period).draft
    assert [visible_text(p) for p in parts(build_native_docx(reopened, path)).values()] == [CURRENT]
    assert library.load_snapshot_version(draft.profile.contract, draft.profile.key, draft.period, first.revision) == first
    assert path.read_bytes() == original


@requires_libreoffice
def test_real_pdf_keeps_current_footer_after_field_refresh(monkeypatch, tmp_path):
    """Real public Word and LibreOffice conversion; standard renderer gate only."""
    import pymupdf
    from app import pdf_converter
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    monkeypatch.setattr(pdf_converter, 'PDF_BACKEND', 'libreoffice')
    path = source(tmp_path, fields='before', paragraphs=2)
    document = Document(path)
    for node in document.sections[0].footer.paragraphs[0]._p.iter(qn('w:t')):
        if node.text in ('7', '23'):
            node.text = CANARY
    document.save(path)
    original = path.read_bytes()
    draft = accept_footer(imported(path, normal_review=True))
    output = tmp_path / 'synthetic-current-footer.docx'
    output.write_bytes(build_native_docx(draft, path))
    pdf_path = pdf_converter.convert_to_pdf(output)
    with pymupdf.open(pdf_path) as pdf:
        pages = [page.get_text() for page in pdf]
        assert pages and all(CURRENT in text for text in pages)
        assert all(OLD not in text and CANARY not in text for text in pages)
    assert path.read_bytes() == original
