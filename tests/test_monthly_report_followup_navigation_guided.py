"""Exact issue/proposal jumps through the complete guided owner/save lifecycle."""
from dataclasses import replace
import pytest
from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import current_draft
from test_monthly_report_followup_navigation import fixture


@pytest.mark.parametrize('category',['issue','proposal'])
@pytest.mark.parametrize('failure',[None,'storage','cas'])
def test_guided_warning_captures_old_card_before_pagination_and_reports_save_truth(monkeypatch,tmp_path,category,failure):
    from app import web_ui, monthly_report_recovery_save as recovery_save
    from app.monthly_report_active_work import ActiveWorkConflict
    monkeypatch.setattr(web_ui,'device_token',lambda cookies:'b'*32)
    app=monthly(monkeypatch,tmp_path)
    next(w for w in app.text_input if w.label=='Prepared by').set_value('Synthetic Editor').run()
    draft=current_draft(app)
    draft=replace(draft,follow_ups=fixture(category).follow_ups,
                  blocks=tuple(replace(b,text='') if b.key=='equipment_issues' else b for b in draft.blocks))
    prefix=next(key[:-6] for key,value in app.session_state.filtered_state.items()
                if key.startswith('report_guided_') and key.endswith('_draft') and hasattr(value,'blocks'))
    app.session_state[prefix+'_draft']=draft
    app.run()
    assert not app.exception
    if category=='proposal':
        next(b for b in app.button if b.label=='Update proposal').click().run()
    label='Issue description' if category=='issue' else 'Proposal scope'
    old_field=next(w for w in app.text_area if w.label==label)
    original_save=recovery_save.save
    if failure:
        def fail_save(*args,**kwargs):
            raise ActiveWorkConflict('Synthetic CAS conflict') if failure=='cas' else OSError('Synthetic recovery storage failure')
        monkeypatch.setattr(recovery_save,'save',fail_save)
    old_field.set_value('Unblurred native card survives the exact warning jump')
    next(b for b in app.button if b.label=='Correct '+category+' · description').click().run()
    assert not app.exception
    updated=current_draft(app)
    assert updated.follow_ups[0].text=='Unblurred native card survives the exact warning jump'
    assert updated.follow_ups[-1]==draft.follow_ups[-1]
    assert next(w for w in app.selectbox if w.label==('Issue page' if category=='issue' else 'Proposal page')).value==2
    assert any('enfra-page-correction-request' in m.value for m in app.markdown)
    app.run()
    assert not app.exception
    assert not any('enfra-page-correction-request' in m.value for m in app.markdown)
    if failure:
        assert 'data-save-state="failed"' in '\n'.join(m.value for m in app.markdown)
        assert any(('not kept for recovery' if failure=='cas' else 'not saved for a refresh') in e.value for e in app.error)
        monkeypatch.setattr(recovery_save,'save',original_save)
        app.run()
        assert not app.exception
        assert 'data-save-state="saved"' in '\n'.join(m.value for m in app.markdown)
        assert current_draft(app).follow_ups[0].text=='Unblurred native card survives the exact warning jump'
