"""Synthetic Scorecards reuse the whole-PDF policy without changing MBCx."""
from dataclasses import asdict, replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources
from app.monthly_report_mbcx_pdf import prepare_whole_pdf
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from test_monthly_report_mbcx_pdf import APP, pdf_bytes


@pytest.fixture
def prepared(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    raw = pdf_bytes()
    content, _ = sources.ingest(profile, 'synthetic-scorecard.pdf', raw)
    return profile, content, raw


def test_scorecard_complete_order_original_and_duplicate_protection(prepared):
    profile, content, raw = prepared
    sibling = ResolvedBlock('activity_summary', 'This month', text='Keep manual notes.')
    blocks = {sibling.key: sibling}
    revised, additions = prepare_whole_pdf(profile, content, blocks, destination='utility_analysis')
    assert list(additions) == ['utility_analysis']
    block = additions['utility_analysis']
    assert len(block.asset_hashes) == 3
    assert block.references == tuple(sources.source_reference(revised.source, n) for n in (1, 2, 3))
    assert sources.source_bytes(profile, revised.source) == raw
    assert blocks == {sibling.key: sibling}
    assert prepare_whole_pdf(profile, revised, {**blocks, **additions}, destination='utility_analysis') == (revised, {})
    with pytest.raises(ValueError, match='another section'):
        prepare_whole_pdf(profile, revised, additions)  # MBCx cannot duplicate it.


@pytest.mark.parametrize('change', ['omit', 'budget', 'excluded', 'late_failure'])
def test_scorecard_refusals_are_atomic(prepared, monkeypatch, change):
    profile, content, _ = prepared
    blocks = {}
    if change == 'omit':
        blocks['utility_analysis'] = ResolvedBlock('utility_analysis', 'Omit')
    elif change == 'budget':
        blocks['water_reports'] = ResolvedBlock('water_reports', 'This month', asset_hashes=('x.png',) * 149)
    elif change == 'excluded':
        content = replace(content, source=replace(content.source, client_page_exclusions=((2, 'review'),)))
    else:
        original = sources.page_image
        def fail(profile, content, number, **kwargs):
            if number == 3:
                raise ValueError('Synthetic last-page failure')
            return original(profile, content, number, **kwargs)
        monkeypatch.setattr(sources, 'page_image', fail)
    before, before_blocks = asdict(content), dict(blocks)
    with pytest.raises(ValueError):
        prepare_whole_pdf(profile, content, blocks, destination='utility_analysis')
    assert asdict(content) == before and blocks == before_blocks


def scorecard_app(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    from app import monthly_report_upload_ui as ui
    stream = BytesIO(pdf_bytes()); stream.name = 'synthetic-scorecard.pdf'
    monkeypatch.setattr(ui.st, 'file_uploader', lambda *args, **kwargs: [stream])
    return AppTest.from_string(APP.replace('"mbcx_report"', '"utility_analysis"'), default_timeout=20).run()


def test_scorecard_one_click_and_individual_review(monkeypatch, tmp_path):
    app = scorecard_app(monkeypatch, tmp_path)
    assert not app.exception
    assert not any(p.proto.popover.label == 'Add files' for p in app.get('popover'))
    button = next(b for b in app.button if b.label == 'Include all 3 PDF pages')
    button.click().run()
    assert not app.exception
    assert len(app.session_state['blocks']['utility_analysis'].asset_hashes) == 3
    app.run()
    assert len(app.session_state['blocks']['utility_analysis'].asset_hashes) == 3
    app.toggle[0].set_value(True).run()
    assert any(w.label == 'Page to review' for w in app.selectbox)


def test_default_caption_initialization_preserves_first_click(monkeypatch, tmp_path):
    app = scorecard_app(monkeypatch, tmp_path)
    button = next(b for b in app.button if b.label == 'Include all 3 PDF pages')
    key = 'synthetic_evidence'
    content, = app.session_state[key]
    source = content.source
    # Activity's earlier source manager materializes the same default caption
    # before this section handles the delivered first inclusion click.
    caption = f'{source.filename} · page/item 1'
    app.session_state[key] = (replace(content, source=replace(source, captions=((1, caption),))),)
    button.click().run()
    assert not app.exception
    assert len(app.session_state['blocks']['utility_analysis'].asset_hashes) == 3


@pytest.mark.parametrize('caption', ['', 'A deliberate changed caption'])
def test_deliberate_caption_changes_reject_old_click(monkeypatch, tmp_path, caption):
    app = scorecard_app(monkeypatch, tmp_path)
    button = next(b for b in app.button if b.label == 'Include all 3 PDF pages')
    content, = app.session_state['synthetic_evidence']
    app.session_state['synthetic_evidence'] = (replace(content, source=replace(content.source, captions=((1, caption),))),)
    button.click().run()
    assert not app.exception and not app.session_state['blocks']
    assert not app.session_state['sources'][0].client_page_reviews


def _saved_scorecard_word(prepared):
    import pymupdf
    from docx import Document
    from app import monthly_report_library as library
    from app.monthly_report_asset_review import approve_all_assets, refresh_asset_source_context
    from app.monthly_report_docx import assemble_docx
    from app.monthly_report_model import ReportDraft, ReportPeriod, known_sections
    profile, content, raw = prepared
    revised, additions = prepare_whole_pdf(profile, content, {}, destination='utility_analysis')
    source = replace(revised.source, service_date='2026-09-12', facility=profile.facilities[0].key)
    block = approve_all_assets(refresh_asset_source_context(additions['utility_analysis'], (source,)))
    section = next(s for s in known_sections() if s.key == 'scorecards')
    draft = ReportDraft(profile, ReportPeriod(2026, 9), 'Synthetic Editor', (section,), (block,), sources=(source,))
    library.save_snapshot(draft, expected_revision=0)
    reopened = library.load_snapshot(profile.contract, profile.key, draft.period).draft
    assert reopened == draft
    output = assemble_docx(reopened, acknowledged_fingerprint=reopened.fingerprint,
        asset_loader=lambda ref: library.read_asset(profile.contract, profile.key, ref))
    document = Document(BytesIO(output))
    assert len(document.inline_shapes) == 3
    assert [p.text for p in document.paragraphs if 'page/item' in p.text] == list(block.asset_captions)
    with pymupdf.open(stream=raw, filetype='pdf') as pdf:
        for shape, page in zip(document.inline_shapes, pdf):
            assert shape.width / shape.height == pytest.approx(page.rect.width / page.rect.height, rel=.01)
    assert sources.source_bytes(profile, source) == raw
    return output, block.asset_captions


def test_scorecard_saved_reopened_word_keeps_all_page_shapes(prepared):
    _saved_scorecard_word(prepared)


from tests.conftest import requires_libreoffice


@requires_libreoffice
def test_actual_scorecard_pdf_keeps_first_middle_last_pages(prepared, tmp_path, monkeypatch):
    import pymupdf
    from app import pdf_converter
    from app.monthly_report_render_compat import rendering_docx
    output, captions = _saved_scorecard_word(prepared)
    monkeypatch.setattr(pdf_converter, 'OUTPUT_DIR', tmp_path)
    path = tmp_path / 'synthetic-scorecard-output.docx'
    path.write_bytes(rendering_docx(output))
    result = pdf_converter.convert_to_pdf(path)
    with pymupdf.open(result) as pdf:
        texts = [page.get_text() for page in pdf]
        pages = []
        for caption in captions:
            matches = [n for n, text in enumerate(texts) if caption in text]
            assert len(matches) == 1
            pages.extend(matches)
        assert pages == sorted(set(pages)) and len(pages) == 3
        assert pages[-1] - pages[0] == 2


def test_scorecard_blocked_page_keeps_all_pages_out(tmp_path, monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, 'synthetic-priced-scorecard.pdf', pdf_bytes(bad_page='Invoice amount $500.'))
    before = asdict(content)
    with pytest.raises(ValueError, match='page 2'):
        prepare_whole_pdf(profile, content, {}, destination='utility_analysis')
    assert asdict(content) == before
