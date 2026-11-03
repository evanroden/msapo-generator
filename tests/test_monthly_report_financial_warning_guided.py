"""Financial owner navigation through the actual guided capture/save boundary."""
from dataclasses import replace
import fitz
import pytest
from app import monthly_report_sources as sources
from app.monthly_report_mbcx_financial_pages import review_pages,page_review_fingerprint,SEMANTICS
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft


@pytest.mark.parametrize('failure',[None,'storage','cas'])
@pytest.mark.parametrize('origin',['caption','batch'])
def test_unblurred_old_caption_survives_financial_owner_switch_without_consent(monkeypatch,tmp_path,failure,origin):
    from app import web_ui,monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    def ingest(name,text):
        pdf=fitz.open();pdf.new_page().insert_text((40,80),text)
        content,_=sources.ingest(draft.profile,name,pdf.tobytes());pdf.close()
        return replace(content,source=replace(content.source,classification='MBCx',facility=draft.profile.facilities[0].title,service_date='2026-09-01'))
    target=ingest('synthetic-financial-owner.pdf','ENFRA client report savings $125.')
    target=review_pages(draft.profile,target,(1,),source_confirmed=True,visual_fingerprints=((1,page_review_fingerprint(target.source,1)),),financial_semantics=SEMANTICS)
    block,=sources.prepare_pages(draft.profile,(target,),((target.source.id,'mbcx_report'),))
    target=replace(target,source=replace(target.source,financial_source_review=None))
    other=ingest('synthetic-ordinary-owner.pdf','Service date 2026-09-01. Reviewed synthetic commissioning pump performance.')
    blocks={b.key:b for b in draft.blocks};blocks[block.key]=block
    draft=replace(draft,blocks=tuple(blocks.values()),sources=(other.source,target.source))
    prefix=next(k[:-6] for k,v in app.session_state.filtered_state.items() if k.startswith('report_guided_') and k.endswith('_draft') and hasattr(v,'blocks'))
    local=prefix+'_evidence_section_mbcx_report';key=local+'_financial_'+target.source.id
    app.session_state[prefix+'_draft']=draft;app.session_state[prefix+'_evidence']=(other,target)
    app.session_state[prefix+'_evidence_section_routes']={other.source.id:'mbcx_report'}
    app.session_state[local+'_selected']=other.source.id;app.session_state[key+'_pages']=[]
    app.run();assert not app.exception
    if origin=='caption':
        # Whole-PDF inclusion is now the default. Deliberately enter the native
        # individual-page editor before testing an unblurred manual caption.
        next(w for w in app.toggle if w.label=='Review individual pages').set_value(True).run()
        assert not app.exception
    if origin=='batch':
        next(w for w in app.checkbox if w.key==local+'_financial_'+other.source.id+'_open').check().run()
        assert not app.exception
        next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').check().run()
        assert not app.exception
    before=current_draft(app)
    captions=[w for w in app.text_input if w.key==local+'_'+other.source.id+'_caption_1']
    assert len(captions)==(1 if origin=='caption' else 0)
    original_save=recovery_save.save
    if failure:
        def fail(*a,**k):raise ActiveWorkConflict('Synthetic CAS') if failure=='cas' else OSError('Synthetic storage failure')
        monkeypatch.setattr(recovery_save,'save',fail)
    if origin=='caption':captions[0].set_value('Pending ordinary source caption kept')
    else:next(w for w in app.multiselect if w.label=='Pages to review together').set_value([1])
    next(b for b in app.button if b.label=='Review financial source page 1').click().run()
    assert not app.exception
    after=current_draft(app)
    if origin=='caption':assert dict(after.sources[0].captions)[1]=='Pending ordinary source caption kept'
    else:assert after.sources[0]==before.sources[0]
    assert after.sources[1]==before.sources[1]
    assert next(b for b in after.blocks if b.key=='mbcx_report')==next(b for b in before.blocks if b.key=='mbcx_report')
    assert next(w for w in app.selectbox if w.key==local+'_selected').value==target.source.id
    assert next(w for w in app.multiselect if w.label=='Pages to review together').value==[]
    assert not next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').value
    assert not next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).value
    assert next(b for b in app.button if b.label=='Include reviewed financial pages').disabled
    assert any('enfra-page-correction-request' in m.value for m in app.markdown)
    app.run();assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)
    if failure:
        assert 'data-save-state="failed"' in '\n'.join(m.value for m in app.markdown)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run();assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(m.value for m in app.markdown)

    if origin=='batch':
        next(w for w in app.selectbox if w.key==local+'_selected').set_value(other.source.id).run()
        assert not app.exception
        next(w for w in app.checkbox if w.key==local+'_financial_'+other.source.id+'_open').check().run()
        assert not app.exception
        assert next(w for w in app.multiselect if w.label=='Pages to review together').value==[1]
        assert next(w for w in app.checkbox if w.label=='This is an ENFRA report intended for the client').value
        assert not next(w for w in app.checkbox if w.label.startswith('I reviewed these pages:')).value
        assert not current_draft(app).sources[0].financial_source_review
    if origin=='batch' and failure=='storage':
        from app import monthly_report_library as library
        from test_source_caption_manager_journey import reload_report
        next(b for b in app.button if b.label=='Save shared version').click().run()
        assert not app.exception
        final=current_draft(app)
        saved=library.load_snapshot(final.profile.contract,final.profile.key,final.period)
        assert saved is not None and not saved.draft.sources[0].financial_source_review
        fresh=reload_report(monkeypatch,final,'e'*32)
        assert not fresh.exception
        fresh_prefix=next(k[:-6] for k,v in fresh.session_state.filtered_state.items() if k.startswith('report_guided_') and k.endswith('_draft') and hasattr(v,'blocks'))
        fresh_local=fresh_prefix+'_evidence_section_mbcx_report'
        next(w for w in fresh.selectbox if w.key==fresh_local+'_selected').set_value(other.source.id).run()
        next(w for w in fresh.checkbox if w.key==fresh_local+'_financial_'+other.source.id+'_open').check().run()
        assert not fresh.exception
        assert not next(w for w in fresh.checkbox if w.label=='This is an ENFRA report intended for the client').value
        assert not next(w for w in fresh.checkbox if w.label.startswith('I reviewed these pages:')).value
