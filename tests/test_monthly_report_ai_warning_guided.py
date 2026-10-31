"""Read-only fact-page context through the actual guided save lifecycle."""
from dataclasses import replace
import pytest
from app import monthly_report_ai as ai
from app.monthly_report_sources import ingest,source_reference
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft
from test_monthly_report_ai import prepared


@pytest.mark.parametrize('failure',[None,'storage','cas'])
def test_fact_page_jump_preserves_pending_notes_and_read_choices_without_reading_or_acceptance(monkeypatch,tmp_path,failure):
    from app import web_ui,monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    def forbidden(*a,**k):raise AssertionError('Navigation cannot start paid reading')
    monkeypatch.setattr(ai,'reserve_call',forbidden)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    target_content,_=ingest(draft.profile,'synthetic-fact-source.txt',b'Synthetic Service inspected PMP-1 and replaced 2 seals on 09/03/2026.')
    other_content,_=ingest(draft.profile,'synthetic-other-source.txt',b'Service date: 2026-09-03\nInspected the other synthetic pump.')
    _,block=prepared()
    original_fact=prepared()[0].facts[0]
    source=replace(target_content.source,service_date='2026-09-03',facility=draft.profile.facilities[0].title,
                   classification='Vendor service',facts=(replace(original_fact,source_id=target_content.source.id,date='2026-09-25'),))
    target_content=replace(target_content,source=source)
    other=replace(other_content.source,service_date='2026-09-03',facility=draft.profile.facilities[0].title,classification='Vendor service')
    other_content=replace(other_content,source=other)
    ref=source_reference(source,1)
    block=replace(block,references=(ref,),ai_paragraphs=(replace(block.ai_paragraphs[0],references=(ref,)),),
                  ai_evidence_fingerprint=ai.evidence_fingerprint((source,),(ref,)))
    blocks={b.key:b for b in draft.blocks};blocks[block.key]=block
    draft=replace(draft,blocks=tuple(blocks.values()),sources=(other,source))
    prefix=next(key[:-6] for key,value in app.session_state.filtered_state.items()
                if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value,'blocks'))
    app.session_state[prefix+'_draft']=draft
    app.session_state[prefix+'_evidence']=(other_content,target_content)
    app.session_state[prefix+'_ai_source']=source.id
    app.run()
    assert not app.exception
    next(w for w in app.multiselect if w.label=='Pages to read for facts').set_value([]).run()
    next(w for w in app.selectbox if w.label=='File to read for work performed').set_value(other.id).run()
    # Deliver this owner's reading choice in the same packet as the warning.
    next(w for w in app.multiselect if w.label=='Pages to read for facts').set_value([])
    before=current_draft(app)
    original_save=recovery_save.save
    if failure:
        def fail_save(*a,**k):
            raise ActiveWorkConflict('Synthetic CAS conflict') if failure=='cas' else OSError('Synthetic storage failure')
        monkeypatch.setattr(recovery_save,'save',fail_save)
    next(w for w in app.text_area if w.label=='Your other notes').set_value('Unblurred human note remains intact.')
    next(b for b in app.button if b.label=='Open cited source page 1').click().run()
    assert not app.exception
    after=current_draft(app)
    assert next(b for b in after.blocks if b.key=='activity_summary').text.startswith('Unblurred human note remains intact.')
    assert after.sources==before.sources
    assert not next(b for b in after.blocks if b.key=='activity_summary').reviewed
    assert next(w for w in app.selectbox if w.label=='File to read for work performed').value==source.id
    assert next(w for w in app.multiselect if w.label=='Pages to read for facts').value==[]
    assert app.session_state['report_draft_mirror'][prefix+'_ai_read_pages_'+other.id]==[]
    assert any('Source page 1 of 1' in c.value for c in app.caption)
    assert any('enfra-page-correction-request' in m.value for m in app.markdown)
    assert not any(b.label=='Use these facts' for b in app.button)
    app.run()
    assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)
    if failure:
        assert 'data-save-state="failed"' in '\n'.join(m.value for m in app.markdown)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run()
        assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(m.value for m in app.markdown)

    # Re-mount the prior native owner, not just its hidden state receipt.
    next(w for w in app.selectbox if w.label=='File to read for work performed').set_value(other.id).run()
    assert not app.exception
    assert next(w for w in app.multiselect if w.label=='Pages to read for facts').value==[]
    assert current_draft(app).sources==before.sources
    if failure is None:
        from app import monthly_report_library as library
        from test_source_caption_manager_journey import reload_report
        next(b for b in app.button if b.label=='Save shared version').click().run()
        assert not app.exception
        final=current_draft(app)
        saved=library.load_snapshot(final.profile.contract,final.profile.key,final.period)
        assert saved is not None
        retained=next(b for b in saved.draft.blocks if b.key=='activity_summary')
        assert retained.text.startswith('Unblurred human note remains intact.')
        assert not retained.reviewed and saved.draft.sources==before.sources
        fresh=reload_report(monkeypatch,final,'d'*32)
        reopened=next(b for b in current_draft(fresh).blocks if b.key=='activity_summary')
        assert reopened.text==retained.text and reopened.ai_paragraphs==retained.ai_paragraphs
        assert not reopened.reviewed
