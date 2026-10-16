"""Done must commit its delivered Water caption before closing native review."""
from dataclasses import replace

import pytest

from test_water_caption_actions import _included_editor
from test_monthly_report_section_uploads import button


@pytest.mark.parametrize('caption', ['Water note delivered with Done.', ''])
def test_native_done_keeps_the_caption_delivered_in_the_same_packet(monkeypatch, tmp_path, caption):
    app = _included_editor(monkeypatch, tmp_path)
    before = app.session_state['test_blocks']['water_reports']
    field = next(w for w in app.text_input if w.label == 'Page caption')
    original_id = field.proto.id
    field.set_value(caption)
    button(app, 'Done reviewing pages').click().run()
    app.run()  # Standalone caller has no guided post-commit refresh.
    assert not app.exception
    current = app.session_state['test_blocks']['water_reports']
    assert current.asset_captions == (caption,)
    assert dict(app.session_state['test_sources'][0].captions)[1] == caption
    assert current.asset_hashes == before.asset_hashes and current.references == before.references
    field = next(w for w in app.text_input if w.label == 'Page caption')
    assert field.value == caption and field.proto.id == original_id
    from app.monthly_report_asset_review import pending_asset_indexes
    assert pending_asset_indexes(current, app.session_state['test_sources']) == (0,)
    app.run()
    assert app.session_state['test_blocks']['water_reports'] == current


def test_old_done_native_action_cannot_close_a_new_source_revision(monkeypatch, tmp_path):
    app = _included_editor(monkeypatch, tmp_path)
    old_done = button(app, 'Done reviewing pages')
    old_done.click()
    contents = app.session_state['synthetic_evidence']
    revised = replace(contents[0].source, vendor='Corrected source vendor')
    app.session_state['synthetic_evidence'] = (replace(contents[0], source=revised),)
    app.run()
    assert not app.exception
    assert any(w.label == 'Done reviewing pages' for w in app.button)
    assert next(w for w in app.text_input if w.label == 'Vendor').value == 'Corrected source vendor'
    assert app.session_state['test_sources'][0] == revised


def current(app):
    from app.monthly_report_model import ReportDraft
    matches = [v for k, v in app.session_state.filtered_state.items()
               if k.startswith('report_guided_') and k.endswith('_draft') and isinstance(v,ReportDraft)]
    assert len(matches) == 1
    return matches[0]


TOKEN = 'd' * 32


def loaded_water(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from app import web_ui, monthly_report_active_work as active, monthly_report_library as library
    from app.monthly_report_sources import ingest
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_section_uploads import prepare_section_pages
    from test_monthly_report_sources import pdf_bytes
    from test_monthly_report_ui import monthly, choose_report, ROOT
    monkeypatch.setattr(web_ui, 'device_token', lambda cookies: TOKEN)
    app = monthly(monkeypatch, tmp_path)
    draft = current(app)
    content, _ = ingest(draft.profile, 'synthetic-water.pdf', pdf_bytes(2))
    source = replace(content.source, client_page_reviews=tuple(
        (n, page_fingerprint(content.source, n)) for n in (1, 2)))
    content = replace(content, source=source)
    water = prepare_section_pages(draft.profile, (content,), 'water_reports', {})['water_reports']
    blocks = {b.key:b for b in draft.blocks};blocks[water.key] = water
    draft = replace(draft, blocks=tuple(blocks.values()), sources=(source,), prepared_by='Synthetic Editor',
                    sections=tuple(replace(s,included=True) if s.key=='water' else s for s in draft.sections))
    library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Editor')
    prefix = next(k[:-6] for k,v in app.session_state.filtered_state.items()
                  if k.startswith('report_guided_') and k.endswith('_draft') and v==current(app))
    active.discard(TOKEN,draft.profile.contract,draft.profile.key,draft.period,
                   expected_revision=app.session_state[prefix+'_active_sequence'],
                   expected_generation=app.session_state[prefix+'_active_generation'])
    app = AppTest.from_file(ROOT/'run_web.py',default_timeout=20).run()
    app.segmented_control[0].set_value('Monthly report').run()
    choose_report(app,draft.profile.facilities[0].title)
    assert not app.exception and any(w.label=='Edit pages' for w in app.button)
    return app


def assert_durable(app):
    from app import monthly_report_active_work as active
    draft=current(app)
    stored=active.load(TOKEN,draft.profile.contract,draft.profile.key,draft.period)
    assert stored.draft==draft
    return stored


def test_native_open_preserves_same_packet_activity_before_canonical_save(monkeypatch,tmp_path):
    app=loaded_water(monkeypatch,tmp_path)
    next(w for w in app.text_area if w.label=='Activity summary').set_value('Activity delivered while opening Water pages.')
    button(app,'Edit pages').click().run()
    assert not app.exception
    assert next(b for b in current(app).blocks if b.key=='activity_summary').text=='Activity delivered while opening Water pages.'
    assert any(w.label=='Page caption' for w in app.text_input)
    assert_durable(app)


def test_native_done_saves_all_edited_pages_metadata_and_same_packet_activity(monkeypatch,tmp_path):
    from app import monthly_report_library as library
    from app.monthly_report_asset_review import pending_asset_indexes
    from app.monthly_report_sources import source_bytes
    app=loaded_water(monkeypatch,tmp_path);before=current(app)
    original=source_bytes(before.profile,before.sources[0]);shared=library.load_snapshot(before.profile.contract,before.profile.key,before.period)
    button(app,'Edit pages').click().run()
    next(w for w in app.selectbox if w.label=='Page to review').set_value(2).run()
    next(w for w in app.text_input if w.label=='Page caption').set_value('Second page remains an entered note.').run()
    button(app,'Include page and continue').click().run()
    next(w for w in app.selectbox if w.label=='Page to review').set_value(1).run()
    next(w for w in app.text_area if w.label=='Activity summary').set_value('Activity delivered with Done Water pages.')
    next(w for w in app.text_input if w.label=='Page caption').set_value('First page delivered with Done.')
    next(w for w in app.text_input if w.label=='Vendor').set_value('Corrected Synthetic Water Vendor')
    button(app,'Done reviewing pages').click().run()
    assert not app.exception
    after=current(app);block=next(b for b in after.blocks if b.key=='water_reports')
    assert block.asset_captions==('First page delivered with Done.','Second page remains an entered note.')
    assert next(b for b in after.blocks if b.key=='activity_summary').text=='Activity delivered with Done Water pages.'
    assert after.sources[0].vendor=='Corrected Synthetic Water Vendor'
    assert 0 in pending_asset_indexes(block,after.sources), 'Closing does not approve changed wording'
    assert next(w for w in app.text_input if w.label=='Page caption').value=='First page delivered with Done.'
    saved=assert_durable(app)
    assert source_bytes(after.profile,after.sources[0])==original
    assert library.load_snapshot(after.profile.contract,after.profile.key,after.period)==shared
    app.run();assert assert_durable(app)==saved


def test_done_then_review_returns_to_summary_before_next_explicit_edit(monkeypatch,tmp_path):
    from app.monthly_report_asset_review import pending_asset_indexes
    app=loaded_water(monkeypatch,tmp_path)
    button(app,'Edit pages').click().run()
    # Match the browser's actual reviewed, nonempty source caption. This
    # fixture otherwise begins with an inherited caption absent on the source.
    next(w for w in app.text_input if w.label=='Page caption').set_value('Synthetic reviewed source caption.').run()
    button(app,'Include page and continue').click().run()
    next(w for w in app.selectbox if w.label=='Page to review').set_value(1).run()
    next(w for w in app.text_input if w.label=='Page caption').set_value('')
    button(app,'Done reviewing pages').click().run()
    assert not app.exception
    assert pending_asset_indexes(next(b for b in current(app).blocks if b.key=='water_reports'),current(app).sources)==(0,)
    assert_durable(app)
    button(app,'Include page and continue').click().run()
    assert not app.exception
    assert not any(w.label=='Page to review' for w in app.selectbox)
    saved=assert_durable(app)
    button(app,'Edit pages').click().run()
    assert not app.exception and any(w.label=='Page to review' for w in app.selectbox)
    assert assert_durable(app)==saved
    assert next(w for w in app.text_input if w.label=='Page caption').value==''


def test_done_save_failure_keeps_current_edit_and_honest_error_without_earlier_rerun(monkeypatch,tmp_path):
    from app import monthly_report_active_work as active
    app=loaded_water(monkeypatch,tmp_path)
    button(app,'Edit pages').click().run();before=assert_durable(app)
    next(w for w in app.text_input if w.label=='Page caption').set_value('Unsaved Water caption retained in browser.')
    next(w for w in app.text_area if w.label=='Activity summary').set_value('Unsaved Activity retained in browser.')
    original_save=active.save
    def fail(*args,**kwargs):raise OSError('Synthetic Water recovery-write failure')
    monkeypatch.setattr(active,'save',fail)
    button(app,'Done reviewing pages').click().run()
    assert not app.exception
    draft=current(app);block=next(b for b in draft.blocks if b.key=='water_reports')
    assert block.asset_captions[0]=='Unsaved Water caption retained in browser.'
    assert next(b for b in draft.blocks if b.key=='activity_summary').text=='Unsaved Activity retained in browser.'
    assert any('Automatic recovery could not keep these edits' in w.value for w in app.error)
    assert active.load(TOKEN,draft.profile.contract,draft.profile.key,draft.period)==before
    monkeypatch.setattr(active,'save',original_save)
    app.run();assert_durable(app)


@pytest.mark.parametrize('boundary', ['source', 'incarnation', 'qa-generation', 'omitted-block'])
def test_old_done_packet_and_caption_cannot_change_replacement_context(monkeypatch,tmp_path,boundary):
    from app.monthly_report_content_policy import page_fingerprint
    app=_included_editor(monkeypatch,tmp_path)
    old_caption=next(w for w in app.text_input if w.label=='Page caption')
    old_id=old_caption.proto.id
    old_caption.set_value('Late caption from prior context.')
    action=button(app,'Done reviewing pages')
    contents=app.session_state['synthetic_evidence']
    block=app.session_state['test_blocks']['water_reports']
    source=contents[0].source
    if boundary=='source':
        source=replace(source,vendor='New source revision under same filename',captions=((1,'New source wording.'),))
        source=replace(source,client_page_reviews=((1,page_fingerprint(source,1)),))
        block=replace(block,asset_captions=('New source wording.',))
        app.session_state['synthetic_evidence']=(replace(contents[0],source=source),)
    elif boundary=='incarnation':
        app.session_state['synthetic_rich_text_epoch']='replacement-report-incarnation'
    elif boundary=='qa-generation':
        app.session_state['_monthly_qa_generation']='replacement-test-generation'
    else:
        block=replace(block,source='Omit')
    app.session_state['test_blocks']['water_reports']=block
    action.click().run()
    assert not app.exception
    assert app.session_state['test_blocks']['water_reports']==block
    assert app.session_state['test_sources'][0]==source
    field=next(w for w in app.text_input if w.label=='Page caption')
    assert field.proto.id!=old_id and field.value!='Late caption from prior context.'


def test_plain_caption_edits_and_review_keep_native_caption_identity(monkeypatch,tmp_path):
    app=_included_editor(monkeypatch,tmp_path)
    field=next(w for w in app.text_input if w.label=='Page caption');native_id=field.proto.id
    field.set_value('First ordinary edit.').run()
    assert next(w for w in app.text_input if w.label=='Page caption').proto.id==native_id
    next(w for w in app.text_input if w.label=='Page caption').set_value('').run()
    assert next(w for w in app.text_input if w.label=='Page caption').proto.id==native_id
    button(app,'Include page and continue').click().run()
    assert next(w for w in app.text_input if w.label=='Page caption').proto.id==native_id
    next(w for w in app.text_input if w.label=='Page caption').set_value('Reentered after clear.').run()
    assert next(w for w in app.text_input if w.label=='Page caption').proto.id==native_id


@pytest.mark.parametrize('boundary', ['incarnation','qa-generation'])
def test_old_included_page_omit_cannot_act_in_replaced_editor_scope(monkeypatch,tmp_path,boundary):
    app=_included_editor(monkeypatch,tmp_path)
    before=app.session_state['test_blocks']['water_reports']
    sources=app.session_state['test_sources']
    old_omit=button(app,'Leave page out and continue')
    if boundary=='incarnation':app.session_state['synthetic_rich_text_epoch']='new-scope'
    else:app.session_state['_monthly_qa_generation']='new-generation'
    old_omit.click().run()
    assert not app.exception
    assert app.session_state['test_blocks']['water_reports']==before
    assert app.session_state['test_sources']==sources


def test_malformed_pending_page_action_preserves_the_report(monkeypatch,tmp_path):
    app=_included_editor(monkeypatch,tmp_path)
    before=app.session_state['test_blocks']['water_reports']
    sources=app.session_state['test_sources']
    app.session_state['synthetic_evidence_section_water_reports_page_edit']='damaged action receipt'
    app.run()
    assert not app.exception
    assert app.session_state['test_blocks']['water_reports']==before
    assert app.session_state['test_sources']==sources
    assert any('report changed after' in w.value for w in app.warning)
