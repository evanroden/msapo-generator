"""The actual Water editor must reconcile its controls after the canonical save."""
from dataclasses import replace
from io import BytesIO

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app import monthly_report_upload_ui as upload_ui
from test_monthly_report_section_uploads import button, reviewed_content
from test_monthly_report_sources import pdf_bytes

TOKEN = 'a' * 32
APP = '''
import streamlit as st
from dataclasses import replace
from types import SimpleNamespace
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from app.monthly_report_guided import _render_ordered_section, _refresh_period_editors_after_commit
from app.monthly_report_active_work import save
from app.monthly_report_ui import _field
prefix = 'water_commit'
profile = synthetic_profiles()[0]
draft = st.session_state.setdefault('canonical',
    replace(synthetic_draft(profile, ReportPeriod(2026,9)),prepared_by='Synthetic Editor'))
blocks={b.key:b for b in draft.blocks}
specs={b.key:b for s in draft.sections for b in s.blocks}
section=next(s for s in draft.sections if s.key=='water')
assets=st.session_state.setdefault('assets',{})
st.session_state['renders']=st.session_state.get('renders',0)+1
draft,blocks=_render_ordered_section(draft,section,blocks,specs,
    SimpleNamespace(profile=profile),prefix,assets,_field)
st.session_state['canonical']=replace(draft,blocks=tuple(blocks.values()))
saved=save('a'*32,st.session_state['canonical'],assets=assets,
    expected_revision=st.session_state.get('revision',0),
    expected_generation=st.session_state.get('generation',''),base_snapshot_revision=0)
st.session_state['revision']=saved.revision
st.session_state['generation']=saved.generation
st.session_state['committed_before_refresh']=saved.draft.fingerprint
st.session_state['refresh_requests']=st.session_state.get('refresh_requests',0)+int(bool(st.session_state.get(prefix+'_period_editor_refresh')))
_refresh_period_editors_after_commit(prefix)
'''


def app_for(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    stream=BytesIO(pdf_bytes(2)); stream.name='synthetic-water.pdf'
    monkeypatch.setattr(upload_ui.st,'file_uploader',
        lambda label, **kwargs:[stream] if label=='Water-treatment files' else [])
    app=AppTest.from_string(APP,default_timeout=20).run()
    assert not app.exception
    return app, stream.getvalue()


def test_final_native_review_returns_ready_controls_without_another_action(monkeypatch,tmp_path):
    app, original=app_for(monkeypatch,tmp_path)
    before=app.session_state['canonical']
    button(app,'Include page and continue').click().run()
    start=app.session_state['renders']
    button(app,'Include page and continue').click().run()
    assert not app.exception
    assert any(b.label=='Edit pages' for b in app.button), 'Saved pages left the pre-commit review form visible'
    assert app.session_state['refresh_requests']==1, 'Only one committed editor refresh is requested'
    end=app.session_state['renders']
    current=app.session_state['canonical']
    assert app.session_state['committed_before_refresh']==current.fingerprint
    stored=active.load(TOKEN,current.profile.contract,current.profile.key,current.period)
    assert stored.draft==current
    assert library.load_snapshot(current.profile.contract,current.profile.key,current.period) is None
    assert len(next(b for b in current.blocks if b.key=='water_reports').asset_hashes)==2
    assert [b for b in before.blocks if b.key!='water_reports']==[b for b in current.blocks if b.key!='water_reports']
    from app.monthly_report_sources import source_bytes
    assert source_bytes(current.profile,current.sources[0])==original
    sequence=stored.revision
    app.run()
    assert app.session_state['renders']==end+1
    assert app.session_state['revision']==sequence
    assert 'water_commit_period_editor_refresh' not in app.session_state.filtered_state


def test_failed_merge_does_not_refresh_or_acknowledge_unapplied_pages(monkeypatch,tmp_path):
    from app import monthly_report_guided as guided
    app,_=app_for(monkeypatch,tmp_path)
    monkeypatch.setattr(guided,'_apply_prepared',lambda draft,blocks,*args:(draft,blocks))
    button(app,'Include page and continue').click().run()
    count=app.session_state['renders']
    button(app,'Include page and continue').click().run()
    assert not app.exception
    assert app.session_state['refresh_requests']==0
    assert 'water_commit_evidence_section_water_reports_auto_include' in app.session_state.filtered_state
    assert 'water_commit_period_editor_refresh' not in app.session_state.filtered_state
    assert not any(b.asset_hashes for b in app.session_state['canonical'].blocks if b.key=='water_reports')


def test_acknowledgement_is_single_consumption_and_never_reruns_mid_editor(monkeypatch,tmp_path):
    profile,content=reviewed_content(monkeypatch,tmp_path,1)
    from app.monthly_report_section_uploads import prepare_section_pages
    block=prepare_section_pages(profile,(content,),'water_reports',{})['water_reports']
    fake={'probe_evidence_section_water_reports_auto_include':
          {'source_id':content.source.id,'pages':(1,)}}
    monkeypatch.setattr(upload_ui.st,'session_state',fake)
    monkeypatch.setattr(upload_ui.st,'rerun',lambda:pytest.fail('Rerun before canonical commit'))
    upload_ui.acknowledge_autoincluded_water_pages('probe',{'water_reports':block})
    assert fake.pop('probe_period_editor_refresh',False) is True
    upload_ui.acknowledge_autoincluded_water_pages('probe',{'water_reports':block})
    assert not fake
