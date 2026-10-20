"""One manager retains originals, exact corrections and native edit capture."""
from dataclasses import replace
import pytest

from app import monthly_report_library as library, monthly_report_ai as ai, monthly_report_upload_ui as upload_ui
from app import monthly_report_sources as sources
from test_monthly_report_upload_ui import app_with_library, upload, button, current_draft, select
from test_monthly_report_utility_uploads import utility_pdf


def resolved_app(monkeypatch,tmp_path):
    app,_=app_with_library(monkeypatch,tmp_path)
    native_uploader=upload_ui.st.file_uploader
    upload(monkeypatch,'synthetic-resolved-utility.pdf',utility_pdf())
    app.run();button(app,'Read monthly files').click().run()
    button(app,'Include page and continue').click().run()
    button(app,'Add selected pages and tables to report').click().run()
    assert not app.exception
    # Only the real file bytes enter through the uploader seam. Restore the
    # native picker before checking the manager's actual reachable controls.
    monkeypatch.setattr(upload_ui.st,'file_uploader',native_uploader)
    app.run()
    assert not app.exception
    return app


def test_successful_add_collapses_exact_resolved_file_without_another_review_ritual(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    assert sum(b.label=='Manage source files' for b in app.button)==1
    assert sum(c.value=='1 source file' for c in app.caption)==1
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert not any(b.label in ('Include page and continue','Add selected pages and tables to report',
                              'Change','Review source files','Done with source files') for b in app.button)
    assert not any(e.label=='Choose pages for the client report' for e in app.expander)
    assert len(next(b for b in current_draft(app).blocks if b.key=='utility_analysis').asset_hashes)==1


def test_change_reaches_original_controls_and_done_changes_no_source_draft_or_standing_records(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    before=current_draft(app)
    source=before.sources[0]
    original=library.load_profile(before.profile.contract,before.profile.key)
    raw=sources.source_bytes(before.profile,source)
    monkeypatch.setattr(ai,'reserve_call',lambda *a: (_ for _ in ()).throw(AssertionError('Display cannot reserve paid reading')))
    button(app,'Manage source files').click().run()
    assert not app.exception
    assert any(e.label=='Choose pages for the client report' for e in app.expander)
    assert any(b.label=='Remove source from this draft' for b in app.button)
    assert any(b.label=='Use these source details' for b in app.button)
    assert any(w.label=='Monthly source files' for w in app.get('file_uploader'))
    assert any(w.label=='Read extracted text' for w in app.expander)
    assert current_draft(app)==before
    button(app,'Done with source files').click().run()
    assert not app.exception
    assert current_draft(app)==before
    assert library.load_profile(before.profile.contract,before.profile.key)==original
    assert sources.source_bytes(before.profile,source)==raw
    assert not list(tmp_path.rglob('snapshots/**/*.json'))
    assert sum(b.label=='Manage source files' for b in app.button)==1


def test_report_only_removed_page_stays_actionable_without_automatic_reinclusion(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    key=next(k for k,v in app.session_state.filtered_state.items() if k.startswith('report_guided_')
             and k.endswith('_draft') and hasattr(v,'blocks'))
    before=current_draft(app)
    current=replace(before,blocks=tuple(replace(b,asset_hashes=(),asset_captions=(),asset_provenance=())
                    if b.key=='utility_analysis' else b for b in before.blocks))
    app.session_state[key]=current
    app.run()
    assert not app.exception
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert any(b.label=='Review synthetic-resolved-utility.pdf' for b in app.button)
    assert not next(b for b in current_draft(app).blocks if b.key=='utility_analysis').asset_hashes
    button(app,'Manage source files').click().run()
    assert any(e.label=='Choose pages for the client report' for e in app.expander)
    assert not next(b for b in current_draft(app).blocks if b.key=='utility_analysis').asset_hashes


@pytest.mark.parametrize("inherited, blocked", [("Approved utility chart", False), ("Cost $125", True), ("0 · NR", False)])
def test_change_does_not_materialize_absent_source_caption_or_replace_inherited_caption(monkeypatch,tmp_path,inherited,blocked):
    from app.monthly_report_content_policy import page_fingerprint
    from app.monthly_report_asset_review import approve_all_assets
    app=resolved_app(monkeypatch,tmp_path)
    key=next(k for k,v in app.session_state.filtered_state.items() if k.startswith('report_guided_')
             and k.endswith('_draft') and hasattr(v,'blocks'))
    before=current_draft(app)
    source=replace(before.sources[0],captions=(),client_page_reviews=())
    source=replace(source,client_page_reviews=((1,page_fingerprint(source,1)),))
    evidence_key=key.removesuffix('_draft')+'_evidence'
    content=replace(app.session_state[evidence_key][0],source=source)
    app.session_state[evidence_key]=(content,)
    block,=sources.prepare_pages(before.profile,(content,),((source.id,'utility_analysis'),))
    block=approve_all_assets(replace(block,asset_captions=(inherited,)))
    app.session_state[key]=replace(before,sources=(source,),blocks=tuple(
        block if b.key=='utility_analysis' else b for b in before.blocks))
    app.run()
    assert not app.exception
    before=current_draft(app)
    assert not before.sources[0].captions
    button(app,'Manage source files').click().run()
    assert not app.exception
    assert current_draft(app)==before
    assert not current_draft(app).sources[0].captions
    assert next(w for w in app.text_input if w.label=='Page caption').value==inherited
    assert button(app,'Include page and continue').disabled is blocked


def test_done_consumes_delivered_caption_before_retiring_its_native_control(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    before=current_draft(app)
    old=next(b for b in before.blocks if b.key=='utility_analysis')
    button(app,'Manage source files').click().run()
    next(w for w in app.text_input if w.label=='Page caption').set_value('New caption delivered with Done')
    button(app,'Done with source files').click().run()
    assert not app.exception
    current=current_draft(app)
    assert dict(current.sources[0].captions)[1]=='New caption delivered with Done'
    attached = next(b for b in current.blocks if b.key=='utility_analysis')
    assert attached.asset_captions==('New caption delivered with Done',)
    assert attached.asset_hashes==old.asset_hashes
    from app.monthly_report_asset_review import pending_asset_indexes
    assert pending_asset_indexes(attached,current.sources)==(0,), 'Done captures the caption but never approves the changed page.'
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert button(app,'Manage source files')


def test_mixed_sources_keep_one_actionable_card_and_reach_the_unresolved_file(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    before=current_draft(app)
    button(app,'Manage source files').click().run()
    native_uploader=upload_ui.st.file_uploader
    upload(monkeypatch,'synthetic-reference.txt',b'An undecided fictional source note.')
    app.run();button(app,'Read monthly files').click().run()
    monkeypatch.setattr(upload_ui.st,'file_uploader',native_uploader)
    app.run();button(app,'Done with source files').click().run()
    assert not app.exception
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert not any('Source files to review' in e.value for e in app.markdown)
    assert sum(b.label=='Manage source files' for b in app.button)==1
    assert sum(c.value=='2 source files' for c in app.caption)==1
    assert next(b for b in current_draft(app).blocks if b.key=='utility_analysis')==(
        next(b for b in before.blocks if b.key=='utility_analysis'))
    button(app,'Manage source files').click().run()
    assert not app.exception
    picker=select(app,'File to review')
    unknown=next(s for s in current_draft(app).sources if s.filename=='synthetic-reference.txt')
    picker.set_value(unknown.id).run()
    assert select(app,'File to review').value==unknown.id
    assert any(b.label=='Remove source from this draft' for b in app.button)


def test_reader_completion_and_done_capture_caption_in_same_native_event(monkeypatch,tmp_path):
    from concurrent.futures import Future
    from io import BytesIO
    from app import receipt_jobs

    app,_=app_with_library(monkeypatch,tmp_path)
    native_uploader=upload_ui.st.file_uploader
    raw=utility_pdf()
    upload(monkeypatch,'synthetic-utility.pdf',raw)
    app.run();button(app,'Read monthly files').click().run()
    stream=BytesIO(raw);stream.name='synthetic-utility.pdf'
    monkeypatch.setattr(upload_ui.st,'file_uploader',lambda label,*a,**kw:
        [stream] if label=='Add activity files (optional)' else native_uploader(label,*a,**kw))
    future=Future();future.set_running_or_notify_cancel()
    starts=[]
    monkeypatch.setattr(ai,'ANTHROPIC_API_KEY','synthetic-never-sent')
    monkeypatch.setattr(ai,'cached',lambda *a:None)
    monkeypatch.setattr(receipt_jobs,'start_receipt',lambda *a:starts.append(1) or future)
    app.run();button(app,'Read selected files').click().run()
    assert len(starts)==1 and button(app,'Done with source files')
    source=current_draft(app).sources[0]
    future.set_result({'items':[{'source':source.id,'page':1,
        'text':'Electricity consumption: 1250 kWh. Synthetic test data.',
        'row':[],'include_page':True}], 'visual_pages':[[source.id,1]], 'notices':[]})
    delivered='Caption delivered when reading finishes'
    next(w for w in app.text_input if w.label=='Page caption').set_value(delivered)
    button(app,'Done with source files').click().run()
    assert not app.exception
    current=current_draft(app)
    assert dict(current.sources[0].captions)[1]==delivered
    assert len(starts)==1
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert button(app,'Manage source files')


def test_failed_add_keeps_original_manager_error_and_current_report(monkeypatch,tmp_path):
    from app import monthly_report_setup as setup
    app=resolved_app(monkeypatch,tmp_path)
    before=current_draft(app)
    button(app,'Manage source files').click().run()
    def reject(*args,**kwargs):
        raise ValueError('Synthetic current table conflict; nothing was replaced.')
    monkeypatch.setattr(setup,'merge_report_block',reject)
    button(app,'Add selected pages and tables to report').click().run()
    assert not app.exception
    assert current_draft(app)==before
    assert any('Synthetic current table conflict' in w.value for w in app.error)
    assert any(e.label=='Choose pages for the client report' for e in app.expander)
    assert button(app,'Done with source files')
    assert not any(e.label=='Included files and pictures' for e in app.expander)


def test_one_source_manager_entry_reopens_ready_pages_in_one_action(monkeypatch,tmp_path):
    app=resolved_app(monkeypatch,tmp_path)
    before=current_draft(app)
    assert sum(b.label=='Manage source files' for b in app.button)==1
    assert not any(b.label in ('Change','Review source files') for b in app.button)
    assert not any(e.label=='Included files and pictures' for e in app.expander)
    assert sum(c.value=='1 source file' for c in app.caption)==1
    button(app,'Manage source files').click().run()
    assert not app.exception
    assert any(e.label=='Choose pages for the client report' for e in app.expander)
    assert button(app,'Done with source files')
    assert current_draft(app)==before


def test_eight_optional_files_remain_available_without_eight_generic_review_reminders(monkeypatch,tmp_path):
    from io import BytesIO
    app,_=app_with_library(monkeypatch,tmp_path)
    native_uploader=upload_ui.st.file_uploader
    originals={f'synthetic-reference-{n}.txt':f'Optional synthetic source note {n}.'.encode()
               for n in range(8)}
    streams=[]
    for name,raw in originals.items():
        stream=BytesIO(raw);stream.name=name;streams.append(stream)
    monkeypatch.setattr(upload_ui.st,'file_uploader',lambda label,*a,**kw:
        streams if label=='Monthly source files' else native_uploader(label,*a,**kw))
    app.run();button(app,'Read monthly files').click().run()
    monkeypatch.setattr(upload_ui.st,'file_uploader',native_uploader)
    app.run();button(app,'Done with source files').click().run()
    assert not app.exception
    before=current_draft(app)
    assert len(before.sources)==8
    assert sum(c.value=='8 source files' for c in app.caption)==1
    assert not any("Review this file's use" in c.value for c in app.caption)
    assert sum(b.label=='Manage source files' for b in app.button)==1
    button(app,'Manage source files').click().run()
    assert len(select(app,'File to review').options)==8
    assert current_draft(app)==before
    for source in before.sources:
        assert sources.source_bytes(before.profile,source)==originals[source.filename]


def test_specific_problem_opens_its_file_beside_optional_references(monkeypatch,tmp_path):
    from datetime import date
    app=resolved_app(monkeypatch,tmp_path)
    utility=current_draft(app).sources[0]
    button(app,'Manage source files').click().run()
    native_uploader=upload_ui.st.file_uploader
    upload(monkeypatch,'synthetic-reference.txt',b'Optional synthetic reference note.')
    app.run();button(app,'Read monthly files').click().run()
    monkeypatch.setattr(upload_ui.st,'file_uploader',native_uploader)
    app.run()
    select(app,'File to review').set_value(utility.id).run()
    next(w for w in app.date_input if w.label=='Source date').set_value(date(2026,8,1))
    button(app,'Use these source details').click().run()
    # Leave another file selected before closing. The correction action must
    # reopen this exact dated original, not merely whichever file was last seen.
    reference=next(s for s in current_draft(app).sources if s.filename=='synthetic-reference.txt')
    select(app,'File to review').set_value(reference.id).run()
    button(app,'Done with source files').click().run()
    before=current_draft(app)
    assert not app.exception
    assert sum(b.label=='Manage source files' for b in app.button)==1
    assert any('Check the source reporting date.' in c.value for c in app.caption)
    assert not any("Review this file's use" in c.value for c in app.caption)
    button(app,'Review '+utility.filename).click().run()
    assert not app.exception
    assert select(app,'File to review').value==utility.id
    assert next(w for w in app.date_input if w.label=='Source date').value==date(2026,8,1)
    assert current_draft(app)==before
