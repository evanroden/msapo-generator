"""Actual shared-source manager capture, exact page switch and recovery truth."""
from dataclasses import replace
import pytest
from app.monthly_report_content_policy import page_fingerprint,page_allowed
from app.monthly_report_sources import ingest
from app.monthly_report_section_uploads import prepare_section_pages
from app.monthly_report_page_controls import revise_included_page
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft


@pytest.mark.parametrize('scenario',['single','shared','source_switch'])
@pytest.mark.parametrize('failure',[None,'storage','cas'])
def test_manager_warning_preserves_old_caption_and_independent_occurrences(monkeypatch,tmp_path,scenario,failure):
    duplicate=scenario=="shared"
    source_switch=scenario=="source_switch"
    from app import web_ui,monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    content,_=ingest(draft.profile,'synthetic-shared-source.pdf',pdf_bytes(2))
    source=replace(content.source,facility=draft.profile.facilities[0].title,service_date='2026-09-10',classification='Vendor service')
    source=replace(source,client_page_reviews=tuple((n,page_fingerprint(source,n)) for n in (1,2)))
    content=replace(content,source=source)
    block=prepare_section_pages(draft.profile,(content,),'improvements',{})['improvements']
    block,source=revise_included_page(block,source,2,'caption',caption='Changed second caption',all_sources=(source,))
    content=replace(content,source=source)
    blocks={b.key:b for b in draft.blocks};blocks[block.key]=block
    if duplicate:blocks['vendor_reports']=replace(block,key='vendor_reports',asset_captions=('Independent first caption','Independent second caption'))
    contents=(content,)
    target_key='improvements'
    if source_switch:
        other=replace(source,id='independent-same-name-and-bytes')
        other=replace(other,client_page_reviews=tuple((n,page_fingerprint(other,n)) for n in (1,2)))
        other_content=replace(content,source=other)
        other_block=prepare_section_pages(draft.profile,(other_content,),'vendor_reports',{})['vendor_reports']
        other_block,other=revise_included_page(other_block,other,2,'caption',caption='Independent target page',all_sources=(other,))
        blocks['vendor_reports']=other_block
        contents=(content,replace(other_content,source=other))
        target_key='vendor_reports'
        assert other.filename==source.filename and other.sha256==source.sha256
    draft=replace(draft,blocks=tuple(blocks.values()),sources=tuple(c.source for c in contents))
    prefix=next(key[:-6] for key,value in app.session_state.filtered_state.items()
                if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value,'blocks'))
    app.session_state[prefix+'_draft']=draft
    app.session_state[prefix+'_evidence']=contents
    app.session_state[prefix+'_evidence_selected']=source.id
    app.session_state[prefix+'_source_active_selected']=source.id
    app.session_state[prefix+'_batch_files_open']=True
    app.session_state[prefix+'_evidence_'+source.id+'_page']=1
    app.run()
    assert not app.exception
    captions=[w for w in app.text_input if w.label=='Page caption']
    assert len(captions)==1
    before=current_draft(app)
    original_save=recovery_save.save
    if failure:
        def fail_save(*args,**kwargs):
            raise ActiveWorkConflict('Synthetic CAS conflict') if failure=='cas' else OSError('Synthetic recovery storage failure')
        monkeypatch.setattr(recovery_save,'save',fail_save)
    if source_switch:
        from datetime import date
        buffered_date=next(w for w in app.date_input if w.key==prefix+'_evidence_'+source.id+'_source_details_date')
        buffered_date.set_value(date(2025,1,2))  # Deliberately not submitted.
    captions[0].set_value('Unblurred old source caption')
    # Multiple occurrences have distinct warning buttons; select exact known
    # originating occurrence by its immutable action key, not a filename.
    from app.monthly_report_checks import preflight
    target=next(c.targets[0] for c in preflight(before) if c.code=='client_source_page' and c.block_key==target_key and c.targets[0].page==2)
    button=next(b for b in app.button if b.key==prefix+'_page_correction_'+target.token+'_client_source_page')
    button.click().run()
    assert not app.exception
    updated=current_draft(app)
    assert dict(updated.sources[0].captions)[1]=='Unblurred old source caption'
    assert next(w for w in app.selectbox if w.label=='Preview page / item').value==2
    assert updated.sources[0].selected_pages==before.sources[0].selected_pages
    assert not page_allowed(updated.sources[0],1)
    assert not page_allowed(updated.sources[-1] if source_switch else updated.sources[0],2)
    if source_switch:
        assert app.session_state[prefix+'_source_active_selected']=='independent-same-name-and-bytes'
        assert updated.sources[0].service_date==before.sources[0].service_date
        assert next(w for w in app.date_input if w.key==prefix+'_evidence_'+source.id+'_source_details_date').value==date(2025,1,2)
        assert dict(updated.sources[1].captions).get(1)!= 'Unblurred old source caption'
        assert next(b for b in updated.blocks if b.key=='vendor_reports').asset_captions==next(b for b in before.blocks if b.key=='vendor_reports').asset_captions
    if duplicate:
        for key in ('improvements','vendor_reports'):
            assert next(b for b in updated.blocks if b.key==key).asset_captions==next(b for b in before.blocks if b.key==key).asset_captions
    else:assert next(b for b in updated.blocks if b.key=='improvements').asset_captions[0]=='Unblurred old source caption'
    markup='\n'.join(m.value for m in app.markdown)
    assert 'enfra-page-correction-request' in markup
    assert 'data-field-kind="combobox"' in markup
    app.run()
    assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)
    if failure:
        assert 'data-save-state="failed"' in '\n'.join(m.value for m in app.markdown)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run()
        assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(m.value for m in app.markdown)
        assert dict(current_draft(app).sources[0].captions)[1]=='Unblurred old source caption'


def test_same_page_warning_caption_remains_unapproved_through_saved_version_and_reopen(monkeypatch,tmp_path):
    from app import web_ui
    from app.monthly_report_asset_review import pending_asset_indexes
    from test_source_caption_manager_journey import prepared_app,save_and_reload,page
    from test_monthly_report_upload_ui import button
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'a'*32)
    app=prepared_app(monkeypatch,tmp_path)
    button(app,'Manage source files').click().run()
    next(w for w in app.text_input if w.label=='Page caption').set_value('Initial unreviewed caption').run()
    old=current_draft(app)
    next(w for w in app.text_input if w.label=='Page caption').set_value('Unblurred same-page caption retained')
    action=next(b for b in app.button if b.label=='Open source page 1 · picture 1')
    action.click().run()
    assert not app.exception
    current=current_draft(app)
    assert page(current).asset_captions==('Unblurred same-page caption retained',)
    assert pending_asset_indexes(page(current),current.sources)
    assert current.sources[0].client_page_reviews==old.sources[0].client_page_reviews
    fresh,saved=save_and_reload(monkeypatch,app,1)
    assert page(saved.draft).asset_captions==('Unblurred same-page caption retained',)
    assert pending_asset_indexes(page(current_draft(fresh)),current_draft(fresh).sources)
    button(fresh,'Manage source files').click().run()
    assert next(w for w in fresh.text_input if w.label=='Page caption').value=='Unblurred same-page caption retained'
