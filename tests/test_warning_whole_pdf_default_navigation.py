"""An exact warning must reveal its page without a preliminary mode click."""
from dataclasses import replace

import pytest

from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import page_fingerprint, page_allowed
from app.monthly_report_sources import ingest
from app.monthly_report_section_uploads import prepare_section_pages
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft


@pytest.mark.parametrize('destination,classification', [('mbcx_report', 'MBCx'),
                                                        ('utility_analysis', 'Utility results')])
def test_warning_reveals_exact_caption_from_default_whole_pdf_mode(monkeypatch, tmp_path,
                                                                 destination, classification):
    app = monthly(monkeypatch, tmp_path)
    next(w for w in app.text_input if w.label == 'Prepared by').set_value('Synthetic Editor').run()
    draft = current_draft(app)
    content, _ = ingest(draft.profile, 'synthetic-warning-pages.pdf', pdf_bytes(2))
    source = replace(content.source, facility=draft.profile.facilities[0].title,
                     service_date='2026-09-10', classification=classification)
    source = replace(source, client_page_reviews=tuple((n, page_fingerprint(source, n)) for n in (1, 2)))
    content = replace(content, source=source)
    block = prepare_section_pages(draft.profile, (content,), destination, {})[destination]
    source = replace(source, captions=((2, 'Exact second-page source caption needing review'),))
    content = replace(content, source=source)
    blocks = {b.key: b for b in draft.blocks}; blocks[block.key] = block
    draft = replace(draft, blocks=tuple(blocks.values()), sources=(source,))
    prefix = next(k[:-6] for k, v in app.session_state.filtered_state.items()
                  if k.startswith('report_guided_') and k.endswith('_draft') and hasattr(v, 'blocks'))
    app.session_state[prefix + '_draft'] = draft
    app.session_state[prefix + '_evidence'] = (content,)
    app.session_state[prefix + '_evidence_section_routes'] = {source.id: destination}
    app.run(); assert not app.exception
    assert any(w.label == 'Review individual pages' and not w.value for w in app.toggle)
    assert not any(w.label == 'Page caption' and w.value == dict(source.captions)[2]
                   for w in app.text_input), 'The exact target is not already open.'
    before = current_draft(app)
    target = next(c.targets[0] for c in preflight(before)
                  if c.code == 'client_source_page' and c.block_key == destination
                  and c.targets[0].page == 2)
    next(b for b in app.button
         if b.key == prefix + '_page_correction_' + target.token + '_client_source_page').click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label == 'Preview page / item').value == 2
    assert next(w for w in app.text_input if w.label == 'Page caption').value == dict(source.captions)[2]
    after = current_draft(app)
    assert after.sources == before.sources
    assert after.blocks == before.blocks
    assert after.fingerprint == before.fingerprint
    assert not page_allowed(after.sources[0], 2)
    assert after.sources[0].financial_source_review is None
    assert any('enfra-page-correction-request' in m.value for m in app.markdown)
    app.run(); assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)
    assert current_draft(app).sources == before.sources
