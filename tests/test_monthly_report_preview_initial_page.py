from dataclasses import replace

import fitz
import pytest

from app import monthly_report_preview as preview
from app.monthly_report_model import ResolvedBlock, default_sections
from app.monthly_report_preview_store import PreviewStore
from test_monthly_report_section_preview import draft
from tests.conftest import requires_libreoffice


@pytest.mark.parametrize('key', ['organization', 'training', 'activity', 'maintenance'])
def test_title_only_divider_opens_at_content_without_removing_any_page(key):
    section = next(s for s in default_sections() if s.key == key)
    with fitz.open() as pdf:
        pdf.new_page().insert_text((50, 60), 'Section ' + section.number + '\n' + section.title)
        pdf.new_page().insert_text((50, 60), 'Meaningful matching content')
        original = pdf.tobytes(no_new_id=True)
        assert preview.section_initial_page(pdf, section) == 1
        assert pdf.tobytes(no_new_id=True) == original
        store = PreviewStore()
        ticket = store.put('synthetic-owner', preview.ReportPreview(original, 2, 'test', 'Sep', 1))
        assert ticket.pages == 2 and ticket.initial_page == 1
        assert store.pages('synthetic-owner', ticket, (0, 1), dpi=96)
        store.discard('synthetic-owner', ticket)


@pytest.mark.parametrize('first,pages', [
    ('Section 11\nTraining Summary\nCompleted inspection training', 2),
    ('Training Summary\nCompleted inspection training', 2),
    ('', 2),  # Unreadable/image-only native artwork is not assumed to be a divider.
    ('Section 11\nTraining Summary', 1),
])
def test_unknown_or_content_first_layout_keeps_the_first_page(first, pages):
    section = next(s for s in default_sections() if s.key == 'training')
    with fitz.open() as pdf:
        pdf.new_page().insert_text((50, 60), first)
        for _ in range(pages - 1):
            pdf.new_page()
        assert preview.section_initial_page(pdf, section) == 0
        assert preview.section_initial_page(pdf, None) == 0


@pytest.mark.parametrize('arrangement', ['excluded', 'reordered'])
def test_preview_initial_page_uses_the_actually_rendered_section_number(monkeypatch, tmp_path, arrangement):
    from docx import Document
    report = draft()
    if arrangement == 'excluded':
        report = replace(report, sections=tuple(replace(s, included=False) if s.key == 'activity' else s
                                                for s in report.sections))
    else:
        selected = next(s for s in report.sections if s.key == 'training')
        report = replace(report, sections=(selected, *(s for s in report.sections if s != selected)))
    converted = []

    def convert(path):
        paragraphs = [p.text for p in Document(path).paragraphs]
        section_number = next(text for text in paragraphs if text.startswith('Section '))
        converted.append(section_number)
        result = tmp_path / (path.stem + '.pdf')
        with fitz.open() as pdf:
            pdf.new_page().insert_text((50, 60), section_number + '\nTraining Summary')
            pdf.new_page().insert_text((50, 60), 'Completed synthetic safety training')
            pdf.save(result)
        return result

    monkeypatch.setattr(preview.pdf_converter, 'convert_to_pdf', convert)
    result = preview.preview_section(report, 'training')
    assert converted == ['Section 10' if arrangement == 'excluded' else 'Section 1']
    assert result.initial_page == 1 and result.pages == 2
    with fitz.open(stream=result.pdf, filetype='pdf') as pdf:
        assert converted[0] in pdf[0].get_text()
        assert 'Completed synthetic safety training' in pdf[1].get_text()


@requires_libreoffice
@pytest.mark.parametrize('key,expected', [('organization', 'Synthetic contact'), ('training', 'Completed synthetic safety training')])
def test_real_section_conversion_opens_meaningful_content_and_keeps_divider(tmp_path, key, expected):
    report = draft()
    report = replace(report, blocks=(*report.blocks, ResolvedBlock('contact_matrix', 'This month',
        rows=(('Demo North', 'Manager', 'Synthetic contact', '', ''),))))
    result = preview.preview_section(report, key)
    assert result.initial_page == 1 and result.pages >= 2
    with fitz.open(stream=result.pdf, filetype='pdf') as pdf:
        assert pdf[0].get_text().startswith('Section ')
        assert expected in '\n'.join(p.get_text() for p in pdf[result.initial_page:])
    (tmp_path / (key + '.pdf')).write_bytes(result.pdf)
