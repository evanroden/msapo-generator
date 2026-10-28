"""Synthetic boundaries for the recovered single-source intake."""
from concurrent.futures import Future
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest
from app import monthly_report_upload_ui as ui
from app import monthly_report_ai as ai, monthly_report_structured_uploads as structured, receipt_jobs

APP = '''
import streamlit as st
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_upload_ui import render_structured_uploads

def field(key, value):
    st.session_state.setdefault(key, value)
    return key
blocks = st.session_state.setdefault("blocks", {"activity_summary": ResolvedBlock("activity_summary", "This month", text="Independent human note.")})
sources, additions, _ = render_structured_uploads(synthetic_profiles()[0], ReportPeriod(2026, 9), "intake", field,
    "activity_summary", blocks=blocks, managed=True)
blocks.update(additions)
st.session_state["sources"] = sources
'''


def setup(monkeypatch, tmp_path, files):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ai, 'cached', lambda *args: None)
    monkeypatch.setattr(ai, 'ANTHROPIC_API_KEY', 'synthetic-not-used')
    values = []
    def uploaded(label, *args, **kwargs):
        if label != 'Add source files':
            return None
        streams=[]
        for name, raw in files:
            stream=BytesIO(raw);stream.name=name;streams.append(stream)
        return streams
    monkeypatch.setattr(ui.st, 'file_uploader', uploaded)
    def start(prepare, reader):
        values.append(prepare())
        return Future()
    monkeypatch.setattr(receipt_jobs, 'start_receipt', start)
    charges=[]
    monkeypatch.setattr(ai, 'reserve_call', lambda *args: charges.append(args))
    return AppTest.from_string(APP).run(), values, charges


@pytest.mark.parametrize('heading', ['Reference memo', 'Water treatment', 'Utility results', 'MBCx', 'Capital renewal', 'Proposal', 'Training'])
def test_managed_non_activity_source_never_enters_native_or_paid_activity(monkeypatch, tmp_path, heading):
    raw=(heading+'\nFacility: Demo North\nInspected valve ZZ-21.').encode()
    app, starts, charges=setup(monkeypatch,tmp_path,[('synthetic-evidence.txt',raw)])
    assert not app.exception
    assert app.session_state['blocks']['activity_summary'].text == 'Independent human note.'
    assert not any(b.label == 'Read selected files' for b in app.button)
    assert starts == charges == []
    assert len(app.session_state['sources']) == 1, 'Keep the original available for its actual section.'


def test_mixed_managed_read_is_explicit_and_sends_only_activity_sources(monkeypatch,tmp_path):
    good=b'Maintenance report\nFacility: Demo North\nInspected valve ZZ-21.'
    water=b'Water treatment\nFacility: Demo North\nInspected conductivity sensor.'
    app, starts, charges=setup(monkeypatch,tmp_path,[('synthetic-service.txt',good),('synthetic-water.txt',water)])
    assert not app.exception
    assert starts == charges == [], 'Upload must not start a paid job.'
    seen=[]
    monkeypatch.setattr(structured,'reader_batches',lambda profile,contents,*args,**kwargs: seen.extend(c.source.id for c in contents) or [{'synthetic':True}])
    next(b for b in app.button if b.label=='Read selected files').click().run()
    assert not app.exception
    good_id=sha256(good).hexdigest()
    assert seen == [good_id]
    assert len(starts)==len(charges)==1
    job=app.session_state['intake_evidence_structured_activity_summary_job']
    assert [c.source.id for c in job['contents']] == [good_id]
    app.run()
    assert len(starts)==len(charges)==1, 'Focus/rerender cannot repeat the read.'


def test_explicit_classification_enables_only_first_native_activity_use(monkeypatch,tmp_path):
    raw=b'Reference memo\nFacility: Demo North\nInspected valve ZZ-21.'
    app, starts, charges=setup(monkeypatch,tmp_path,[('synthetic-note.txt',raw)])
    assert app.session_state['blocks']['activity_summary'].text=='Independent human note.'
    content,=app.session_state['intake_evidence']
    app.session_state['intake_evidence']=(replace(content,source=replace(content.source,classification='Vendor service')),)
    app.run()
    assert not app.exception
    assert 'ZZ-21' in app.session_state['blocks']['activity_summary'].text
    first=app.session_state['blocks']['activity_summary']
    app.run()
    assert app.session_state['blocks']['activity_summary']==first
    assert starts==charges==[]


def test_removed_source_can_be_readded_after_clearing_same_file(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_upload_ui import button,current_draft
    files=[]
    app=monthly(monkeypatch,tmp_path)
    setup(monkeypatch,tmp_path,files)
    raw=b'Reference memo for later review.'
    files.append(('synthetic-reference.txt',raw))
    # Fresh intake is already visible; deliver the selected uploader values.
    app.run()
    assert not app.exception and len(current_draft(app).sources)==1
    button(app,'Remove source from this draft').click().run()
    assert not app.exception and current_draft(app).sources==()
    app.run()
    assert current_draft(app).sources==(), 'A lingering uploader must not undo Remove.'
    files.clear();app.run()
    files.append(('synthetic-reference.txt',raw));app.run()
    assert not app.exception and len(current_draft(app).sources)==1
    source,=current_draft(app).sources
    assert ui.sources.source_bytes(current_draft(app).profile,source)==raw


def test_native_classification_click_routes_without_an_unrelated_second_action(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_upload_ui import button,current_draft
    files=[]
    app=monthly(monkeypatch,tmp_path)
    setup(monkeypatch,tmp_path,files)
    files.append(('synthetic-reference.txt',b'Reference memo: inspected valve ZZ-21.'))
    # Fresh intake is already visible; deliver the selected uploader values.
    app.run()
    assert not app.exception
    assert 'ZZ-21' not in next(b.text for b in current_draft(app).blocks if b.key=='activity_summary')
    next(w for w in app.selectbox if w.label=='Classification').set_value('Vendor service').run()
    assert not app.exception
    assert 'ZZ-21' in next(b.text for b in current_draft(app).blocks if b.key=='activity_summary')


def test_adding_another_file_does_not_resurrect_a_removed_uploader_selection(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_upload_ui import button,current_draft
    files=[]
    app=monthly(monkeypatch,tmp_path)
    setup(monkeypatch,tmp_path,files)
    a=('synthetic-reference-A.txt',b'Reference memo A for later review.')
    b=('synthetic-reference-B.txt',b'Reference memo B for later review.')
    files.append(a)
    # Fresh intake is already visible; deliver the selected uploader values.
    app.run()
    button(app,'Remove source from this draft').click().run()
    files.append(b);app.run()
    assert not app.exception
    assert [source.filename for source in current_draft(app).sources]==[b[0]]
    # Only removing A from the chooser and deliberately selecting it again
    # releases its tombstone. B and both original files remain unchanged.
    files.remove(a);app.run()
    files.append(a);app.run()
    assert not app.exception
    assert {source.filename for source in current_draft(app).sources}=={a[0],b[0]}


def test_fresh_pdf_read_starts_on_first_explicit_click_after_source_controls_settle(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_sources import pdf_bytes
    from test_monthly_report_upload_ui import button,current_draft
    files=[]
    app=monthly(monkeypatch,tmp_path)
    _,starts,charges=setup(monkeypatch,tmp_path,files)
    files.append(('synthetic-maintenance report.pdf',pdf_bytes(1)))
    # Fresh intake is already visible; deliver the selected uploader values.
    app.run()
    assert not app.exception
    assert starts==charges==[], 'Settling default captions is not paid-read consent.'
    assert current_draft(app).sources[0].captions, 'The page owner has committed its initial caption.'
    button(app,'Read selected files').click().run()
    assert not app.exception
    assert len(starts)==len(charges)==1, 'The first click must not target a pre-caption source fingerprint.'
    app.run()
    assert len(starts)==len(charges)==1


def test_delivered_non_activity_classification_rejects_finished_activity_read_before_apply(monkeypatch,tmp_path):
    from test_monthly_report_ui import monthly
    from test_monthly_report_sources import pdf_bytes
    from test_monthly_report_upload_ui import button,current_draft
    files=[]
    app=monthly(monkeypatch,tmp_path)
    setup(monkeypatch,tmp_path,files)
    raw=pdf_bytes(1)
    files.append(('synthetic-maintenance report.pdf',raw))
    # Fresh intake is already visible; deliver the selected uploader values.
    app.run()
    future=Future()
    starts=[]
    def start(prepare,reader):
        starts.append(prepare())
        return future
    monkeypatch.setattr(receipt_jobs,'start_receipt',start)
    applied=[]
    original=structured.reader_update
    def reader_update(*args,**kwargs):
        applied.append(args[0])
        return original(*args,**kwargs)
    monkeypatch.setattr(structured,'reader_update',reader_update)
    button(app,'Read selected files').click().run()
    assert not app.exception and len(starts)==1
    before_text=next(block.text for block in current_draft(app).blocks if block.key=='activity_summary')
    future.set_result({'items':[{'source':sha256(raw).hexdigest(),'page':1,
        'text':'Completed inspection of DEMO-01.','row':[],'include_page':True}],
        'visual_pages':[[sha256(raw).hexdigest(),1]]})
    next(w for w in app.selectbox if w.label=='Classification').set_value('Water treatment').run()
    draft=current_draft(app)
    assert not app.exception and draft.sources[0].classification=='Water treatment'
    assert applied==[], 'A source routing decision delivered with completion must win before application.'
    assert not any(block.asset_hashes for block in draft.blocks)
    assert next(block.text for block in draft.blocks if block.key=='activity_summary')==before_text
    assert len(starts)==1, 'The post-commit refresh cannot start another paid read.'
