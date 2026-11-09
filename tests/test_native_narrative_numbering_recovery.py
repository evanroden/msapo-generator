"""Unrecognized Word list metadata cannot crash or prove a body-style match."""
from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn

from app.monthly_report_native_layout import build_native_docx, _build_native_docx
from app.monthly_report_native_text import narrative_prototype, write_narrative
from tests.test_monthly_report_narrative_body_roles import hierarchy


INVALID = ("²", "①", "١", "１", "-1", "+1", "1.0", "", None)
IDS = ("superscript", "circled", "arabic-indic", "fullwidth", "negative", "signed", "decimal", "empty", "missing-value")


def numbered(paragraph, value):
    marker = paragraph._p.get_or_add_pPr().get_or_add_numPr().get_or_add_numId()
    if value is None:
        marker.attrib.pop(qn('w:val'), None)
    else:
        marker.set(qn('w:val'), value)


def prototype(document, heading, title, body, second):
    styles = {style.style_id: style.element for style in document.styles}
    scopes = {p._p: ('activity', 'activity_summary') for p in (heading, title, body, second)}
    return narrative_prototype(title._p, styles, set(), scopes=scopes)


def bold(prototype):
    marker = prototype.find('./' + qn('w:r') + '/' + qn('w:rPr') + '/' + qn('w:b'))
    return marker is not None and marker.get(qn('w:val')) not in ('0', 'false', 'off')


@pytest.mark.parametrize('value', INVALID, ids=IDS)
@pytest.mark.parametrize('location', ['title', 'first-body', 'second-body'])
def test_unrecognized_numbering_preserves_original_typography_and_source(tmp_path, value, location):
    source, _, document, heading, title, body, second = hierarchy(tmp_path)
    target = {'title': title, 'first-body': body, 'second-body': second}[location]
    numbered(target, value)
    document.save(source)
    before = source.read_bytes()
    original_xml = document.element.xml
    result = prototype(document, heading, title, body, second)
    assert bold(result)
    assert document.element.xml == original_xml
    assert source.read_bytes() == before

    # Actual Word XML writing and reopening; this is not the public storage gate.
    output = Document()
    anchor = output.add_paragraph('Replace this synthetic placeholder.')
    write_narrative(anchor._p, result, 'Current authored synthetic narrative.')
    encoded = BytesIO()
    output.save(encoded)
    reopened = Document(BytesIO(encoded.getvalue()))
    assert reopened.paragraphs[0].text == 'Current authored synthetic narrative.'
    assert reopened.paragraphs[0].runs[0].bold is True
    assert source.read_bytes() == before


@pytest.mark.parametrize('value', ['1', '000001', '9' * 5000], ids=['ordinary', 'padded', 'long-decimal'])
def test_matching_positive_decimal_list_identity_still_supplies_body_style(tmp_path, value):
    source, _, document, heading, title, body, second = hierarchy(tmp_path)
    for paragraph in (body, second):
        numbered(paragraph, value)
    document.save(source)
    before = source.read_bytes()
    result = prototype(document, heading, title, body, second)
    assert not bold(result)
    assert source.read_bytes() == before


@pytest.mark.parametrize('value', ['0', '000000'])
def test_inactive_zero_numbering_retains_established_role_behavior(tmp_path, value):
    _, _, document, heading, title, body, second = hierarchy(tmp_path)
    numbered(title, value)
    assert not bold(prototype(document, heading, title, body, second))
    for paragraph in (body, second):
        numbered(paragraph, value)
    assert bold(prototype(document, heading, title, body, second))


@pytest.mark.parametrize('section', [None, 'activity'])
@pytest.mark.parametrize('public', [False, True], ids=['assembly', 'public-storage-gate'])
def test_native_word_keeps_current_wording_and_source_when_list_marker_is_unrecognized(tmp_path, monkeypatch, section, public):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path / 'saved'))
    source, draft, document, heading, title, body, second = hierarchy(tmp_path)
    numbered(body, '²')
    document.save(source)
    before = source.read_bytes()
    fingerprint = draft.fingerprint
    build = build_native_docx if public else _build_native_docx
    output = Document(BytesIO(build(draft, source, section_key=section)))
    current = [p for p in output.paragraphs if p.text.startswith('Current synthetic')]
    assert [p.text for p in current] == [
        'Current synthetic inspection was completed.',
        'Current synthetic follow-up remains pending.',
    ]
    assert all(p.runs[0].bold is True for p in current)
    assert source.read_bytes() == before
    assert draft.fingerprint == fingerprint


def test_unchanged_source_prototype_does_not_mutate_unrecognized_numbering(tmp_path):
    source, _, document, heading, title, body, second = hierarchy(tmp_path)
    numbered(title, '²')
    before = title._p.xml
    prototype(document, heading, title, body, second)
    assert title._p.xml == before
