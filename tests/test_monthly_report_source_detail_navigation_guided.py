"""The real source form stays authoritative across exact Review navigation."""
from dataclasses import replace
from datetime import date
import pytest
from app.monthly_report_sources import ingest
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft


@pytest.mark.parametrize('code',['source_facility','source_date_unknown','source_period'])
@pytest.mark.parametrize('failure',[None,'storage','cas'])
def test_exact_date_site_owner_preserves_unblurred_caption_and_buffered_form_without_apply(monkeypatch,tmp_path,code,failure):
    from app import web_ui,monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    old,_=ingest(draft.profile,'synthetic-old-details.pdf',pdf_bytes(1))
    target,_=ingest(draft.profile,'synthetic-target-details.pdf',pdf_bytes(2))
    old=replace(old,source=replace(old.source,facility=draft.profile.facilities[0].title,service_date='2026-09-03',classification='Vendor service'))
    target=replace(target,source=replace(target.source,facility='' if code=='source_facility' else draft.profile.facilities[0].title,
        service_date='' if code=='source_date_unknown' else '2025-01-01' if code=='source_period' else '2026-09-03',classification='Vendor service'))
    draft=replace(draft,sources=(old.source,target.source))
    prefix=next(k[:-6] for k,v in app.session_state.filtered_state.items() if k.startswith('report_guided_') and k.endswith('_draft') and hasattr(v,'blocks'))
    app.session_state[prefix+'_draft']=draft;app.session_state[prefix+'_evidence']=(old,target)
    app.session_state[prefix+'_evidence_selected']=old.source.id
    app.session_state[prefix+'_source_active_selected']=old.source.id
    app.session_state[prefix+'_batch_files_open']=True
    app.run();assert not app.exception
    before=current_draft(app)
    original_save=recovery_save.save
    if failure:
        def fail(*a,**k):raise ActiveWorkConflict('Synthetic CAS') if failure=='cas' else OSError('Synthetic storage failure')
        monkeypatch.setattr(recovery_save,'save',fail)
    old_date=prefix+'_evidence_'+old.source.id+'_source_details_date'
    next(w for w in app.date_input if w.key==old_date).set_value(date(2025,2,3))
    next(w for w in app.text_input if w.key==prefix+'_evidence_'+old.source.id+'_caption_1').set_value('Unblurred old source caption')
    next(b for b in app.button if b.key==prefix+'_correct_source_'+target.source.id+'_'+code).click().run()
    assert not app.exception
    after=current_draft(app)
    assert dict(after.sources[0].captions)[1]=='Unblurred old source caption'
    assert after.sources[0].service_date==before.sources[0].service_date
    assert next(w for w in app.date_input if w.key==old_date).value==date(2025,2,3)
    assert after.sources[1]==before.sources[1]
    assert app.session_state[prefix+'_source_active_selected']==target.source.id
    markers=[m.value for m in app.markdown if 'enfra-source-review-target' in m.value]
    assert len(markers)==1 and 'data-source-id="'+target.source.id+'"' in markers[0]
    assert 'data-field="'+('site' if code=='source_facility' else 'date')+'"' in markers[0]
    app.run();assert not app.exception
    assert not any('enfra-source-review-target' in m.value for m in app.markdown)
    if failure:
        assert 'data-save-state="failed"' in '\n'.join(m.value for m in app.markdown)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run();assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(m.value for m in app.markdown)
    if failure is None and code=='source_facility':
        # Merely visiting retains absence; explicit Include records exactly the
        # shown default before calculating its page review, as before.
        current=current_draft(app)
        assert not current.sources[1].captions
        shown=next(w.value for w in app.text_input if w.key==prefix+'_evidence_'+target.source.id+'_caption_1')
        next(b for b in app.button if b.key.startswith(prefix+'_evidence_'+target.source.id+'_keep_page_')).click().run()
        assert not app.exception
        included=current_draft(app).sources[1]
        assert dict(included.captions)[1]==shown
        from app.monthly_report_content_policy import page_fingerprint
        assert dict(included.client_page_reviews)[1]==page_fingerprint(included,1)
        assert included.facility==target.source.facility


def test_same_source_warning_renews_only_delivered_caption_keeps_pending_date_unapplied(monkeypatch,tmp_path):
    from app import web_ui
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    content,_=ingest(draft.profile,'synthetic-same-source.pdf',pdf_bytes(1))
    content=replace(content,source=replace(content.source,classification='Vendor service',facility=draft.profile.facilities[0].title,service_date=''))
    draft=replace(draft,sources=(content.source,))
    prefix=next(k[:-6] for k,v in app.session_state.filtered_state.items() if k.startswith('report_guided_') and k.endswith('_draft') and hasattr(v,'blocks'))
    app.session_state[prefix+'_draft']=draft;app.session_state[prefix+'_evidence']=(content,)
    app.session_state[prefix+'_batch_files_open']=True
    app.run();assert not app.exception
    baseline=current_draft(app).sources[0]
    date_key=prefix+'_evidence_'+content.source.id+'_source_details_date'
    next(w for w in app.date_input if w.key==date_key).set_value(date(2026,9,3))
    next(w for w in app.text_input if w.key==prefix+'_evidence_'+content.source.id+'_caption_1').set_value('Explicit pending same-source caption')
    next(b for b in app.button if b.key==prefix+'_correct_source_'+content.source.id+'_source_date_unknown').click().run()
    assert not app.exception
    after=current_draft(app).sources[0]
    assert after==replace(baseline,captions=((1,'Explicit pending same-source caption'),))
    assert next(w for w in app.date_input if w.key==date_key).value==date(2026,9,3)
    assert any('enfra-source-review-target' in m.value for m in app.markdown)
    app.run();assert not app.exception
    assert current_draft(app).sources[0]==after
    assert not any('enfra-source-review-target' in m.value for m in app.markdown)
