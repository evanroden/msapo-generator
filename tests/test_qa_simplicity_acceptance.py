from test_monthly_report_ui import monthly
from test_monthly_report_upload_ui import upload, button, current_draft

def state(app):
 s=app.session_state.filtered_state
 return {k:v for k,v in s.items() if k.endswith(('_source_manager_resolution','_batch_files_open','_open_request','_pending_accepted_workorders'))}

def test_fresh_csv_acceptance_transition(monkeypatch,tmp_path):
 app=monthly(monkeypatch,tmp_path,saved=False)
 next(w for w in app.checkbox if w.label=='United Memorial Medical Center').check().run()
 button(app,'Use ENFRA template').click().run()
 next(w for w in app.text_input if w.label=='Your name').set_value('Synthetic Simplicity Reviewer').run()
 button(app,'Start this report').click().run()
 assert not current_draft(app).sources
 button(app,'Done with source files').click().run();app.run()
 button(app,'Manage source files').click().run()
 upload(monkeypatch,'synthetic-simplicity-orders.csv',b'Work Order,Date,Status,Facility\nTEST-001,2026-09-04,Completed,United Memorial Medical Center\n')
 app.run()
 assert not app.exception
 resolution=next(v for k,v in state(app).items() if k.endswith('_source_manager_resolution'))
 assert len(resolution)==1 and list(resolution.values())==[False]
 button(app,'Add totals to summary').click().run()
 assert not app.exception
 assert any('_source_manager_panel{display:none' in m.value for m in app.markdown)
 assert not any(b.label=='Add totals to summary' for b in app.button)
 assert '1 total, 1 completed, 0 open' in next(b.text for b in current_draft(app).blocks if b.key=='activity_summary')
 assert all(next(v for k,v in state(app).items() if k.endswith('_source_manager_resolution')).values())
 app.run()
 assert any('_source_manager_panel{display:none' in m.value for m in app.markdown)

import pytest
@pytest.fixture(autouse=True)
def diagnostics_enabled(monkeypatch,tmp_path):
 import streamlit as st
 from app import monthly_report_guided as guided
 from scripts import qa_simplicity_delivery as diagnostic
 for key in ('EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS','EPC_MONTHLY_DOM_FIXTURE','EPC_MONTHLY_FRESH_TASK','EPC_MONTHLY_SIMPLICITY_TASK'):
  monkeypatch.setenv(key,'1')
 monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
 (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
 monkeypatch.setattr(st,'button',st.button)
 monkeypatch.setattr(guided,'_render_ordered_section',guided._render_ordered_section)
 rows=[]
 diagnostic.install(st,guided,rows.append)
 yield
 callbacks=[r for r in rows if r['kind']=='accept-callback']
 assert [r['phase'] for r in callbacks]==['before','after']
 assert not callbacks[0]['state'][0]['pending']
 assert callbacks[1]['state'][0]['pending']
 assert any(r['kind']=='activity-render' and r['phase']=='after' and r['state'] and not r['state'][0]['manager'] for r in rows)
