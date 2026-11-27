"""Built-in output labels actual procedures without changing saved report data."""
from dataclasses import replace
from io import BytesIO
from docx import Document
import pytest
from app.monthly_report_docx import _build_docx
from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, profile_sections, synthetic_profiles


def report(*blocks):
    profile = synthetic_profiles()[0]
    sections = tuple(replace(s, included=s.key == 'organization') for s in profile_sections(profile))
    return ReportDraft(profile, ReportPeriod(2026, 11), 'Synthetic Editor', sections, blocks)


@pytest.mark.parametrize('key', ['business_hours_workflow', 'after_hours_workflow'])
def test_procedures_only_have_matching_contents_divider_and_page_title(key):
    draft = report(ResolvedBlock(key, 'This month', text='Synthetic outage instructions'))
    original = draft.sections
    doc = Document(BytesIO(_build_docx(draft)))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert 'Outage procedures' in text
    assert '1. Outage procedures' in text
    assert 'Organizational Chart' not in text
    assert draft.sections == original


def test_genuine_chart_survives_independently_with_combined_semantic_title():
    draft = report(ResolvedBlock('org_chart', 'This month', text='Synthetic chart content'),
                   ResolvedBlock('business_hours_workflow', 'This month', text='Synthetic business procedure'),
                   ResolvedBlock('after_hours_workflow', 'This month', text='Synthetic after-hours procedure'))
    doc = Document(BytesIO(_build_docx(draft)))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '1. Organization and outage procedures' in text
    assert all(text.count(t) == 1 for t in ('Synthetic chart content', 'Synthetic business procedure', 'Synthetic after-hours procedure'))


def test_omitted_procedures_do_not_retitle_a_chart():
    doc = Document(BytesIO(_build_docx(report(ResolvedBlock('org_chart', 'This month', text='Synthetic chart'),
                                              ResolvedBlock('business_hours_workflow', 'Omit', text='Omitted instructions')))))
    text = '\n'.join(p.text for p in doc.paragraphs)
    assert '1. Organizational Chart' in text and 'Omitted instructions' not in text


def test_explicit_custom_section_title_is_preserved():
    draft = report(ResolvedBlock('business_hours_workflow', 'This month', text='Synthetic instructions'))
    draft = replace(draft, sections=tuple(replace(s, title='Explicit reviewed title')
                    if s.key == 'organization' else s for s in draft.sections))
    doc = Document(BytesIO(_build_docx(draft)))
    assert any(p.text == '1. Explicit reviewed title' for p in doc.paragraphs)


def test_generation_and_pdf_retry_share_derived_contents_titles(tmp_path, monkeypatch):
    from app import monthly_report_docx as renderer
    from app import monthly_report_contents_pagination as contents
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = report(ResolvedBlock('org_chart', 'This month', text='Synthetic chart'),
                   ResolvedBlock('business_hours_workflow', 'This month', text='Synthetic instructions'))
    draft = replace(draft, sections=tuple(replace(section, blocks=tuple(replace(spec, required=False) for spec in section.blocks)) for section in draft.sections))
    observed = []
    monkeypatch.setattr(renderer, '_convert_report_pdf', lambda *args: (b'synthetic-pdf', ''))
    monkeypatch.setattr(contents, 'ensure_pdf_page_links', lambda pdf, sections: pdf)
    def synchronize(docx, pdf, sections):
        observed.append(tuple(s.title for s in sections))
        return docx, ''
    monkeypatch.setattr(contents, 'synchronize', synchronize)
    package = renderer.generate_report(draft, acknowledged_fingerprint=draft.fingerprint)
    assert observed == [('Organization and outage procedures',)]
    renderer.retry_report_pdf(draft, replace(package, pdf=None))
    assert observed == [('Organization and outage procedures',), ('Organization and outage procedures',)]


def test_contacts_and_workflow_use_combined_title_without_mutating_sections():
    from app.monthly_report_docx import _builtin_semantic_sections
    draft = report(ResolvedBlock('contact_matrix', 'This month', rows=(('Synthetic contact', 'Synthetic role'),)),
                   ResolvedBlock('after_hours_workflow', 'This month', text='Synthetic procedure'))
    original = draft.sections
    assert tuple(s.title for s in _builtin_semantic_sections(draft)) == ('Organization and outage procedures',)
    assert draft.sections == original
