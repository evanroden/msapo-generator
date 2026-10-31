"""Full ordinary guided owner/commit/refresh route, not a replacement editor."""
from dataclasses import replace
import pytest
from app.monthly_report_content_policy import page_fingerprint, page_allowed
from app.monthly_report_sources import ingest
from app.monthly_report_section_uploads import prepare_section_pages
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft


@pytest.mark.parametrize('failure',[None,'storage','cas'])
def test_guided_warning_commits_old_caption_before_opening_exact_page(monkeypatch,tmp_path,failure):
    from app import web_ui, monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    content,_=ingest(draft.profile,'synthetic-navigation-pages.pdf',pdf_bytes(2))
    source=replace(content.source,facility=draft.profile.facilities[0].title,
                   service_date='2026-09-10',classification='Water treatment')
    source=replace(source,client_page_reviews=tuple((n,page_fingerprint(source,n)) for n in (1,2)))
    content=replace(content,source=source)
    block=prepare_section_pages(draft.profile,(content,),'water_reports',{})['water_reports']
    source=replace(source,captions=tuple(sorted({**dict(source.captions),2:'Changed second page caption'}.items())))
    content=replace(content,source=source)
    blocks={b.key:b for b in draft.blocks};blocks[block.key]=block
    draft=replace(draft,blocks=tuple(blocks.values()),sources=(source,))
    prefix=next(key[:-6] for key,value in app.session_state.filtered_state.items()
                if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value,'blocks'))
    app.session_state[prefix+'_draft']=draft
    app.session_state[prefix+'_evidence']=(content,)
    app.run()
    assert not app.exception
    pages=[w for w in app.selectbox if w.label=='Page to review']
    assert len(pages)==1
    pages[0].set_value(1).run()
    assert not app.exception
    captions=[w for w in app.text_input if w.label=='Page caption']
    assert len(captions)==1
    original_save=recovery_save.save
    if failure:
        def fail_save(*args,**kwargs):
            raise (ActiveWorkConflict('Synthetic CAS conflict') if failure=='cas' else OSError('Synthetic recovery storage failure'))
        monkeypatch.setattr(recovery_save,'save',fail_save)
    captions[0].set_value('Unblurred caption retained by the real guided workflow')
    actions=[b for b in app.button if b.label=='Review source page 2 · picture 2']
    assert len(actions)==1
    actions[0].click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Page to review').value==2
    updated=current_draft(app)
    water=next(b for b in updated.blocks if b.key=='water_reports')
    assert water.asset_captions[0]=='Unblurred caption retained by the real guided workflow'
    assert updated.sources[0].selected_pages==source.selected_pages
    assert not page_allowed(updated.sources[0],1)
    assert not page_allowed(updated.sources[0],2)
    assert any('enfra-page-correction-request' in item.value for item in app.markdown)
    assert prefix+'_page_navigation_pending' not in app.session_state.filtered_state
    assert prefix+'_page_navigation_ready' not in app.session_state.filtered_state
    app.run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Page to review').value==2
    assert not any('enfra-page-correction-request' in item.value for item in app.markdown)
    if failure:
        markup='\n'.join(item.value for item in app.markdown)
        assert 'data-save-state="failed"' in markup
        assert any(('not kept for recovery' if failure=='cas' else 'not saved for a refresh') in e.value for e in app.error)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run()
        assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(item.value for item in app.markdown)
        assert next(b for b in current_draft(app).blocks if b.key=='water_reports').asset_captions[0]==(
            'Unblurred caption retained by the real guided workflow')

