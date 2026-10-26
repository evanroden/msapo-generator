"""Local non-browser checks of the hosted fixture; never fake a browser pass."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.workspace_cover_template_fallback import make_source, install_template


def test_synthetic_source_hits_real_native_budget_not_upload_budget(tmp_path):
    from app.monthly_report_import import inspect_docx, MAX_DOCX_BYTES
    from app.monthly_report_compatibility_view import MAX_VIEW_SOURCE_BYTES
    from app.monthly_report_source_view_runtime import derive_import_view
    source=make_source(tmp_path)
    assert MAX_VIEW_SOURCE_BYTES==24*1024*1024
    assert MAX_VIEW_SOURCE_BYTES < source.stat().st_size < MAX_DOCX_BYTES
    inspection=inspect_docx(source)
    assert any(i.kind=='unsupported' for i in inspection.items)
    with pytest.raises(ValueError,match='source byte budget'):
        derive_import_view(source,inspection)


def test_template_fixture_refuses_unmarked_shared_root(tmp_path,monkeypatch):
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path))
    with pytest.raises(ValueError):install_template(tmp_path,'d'*32)
    assert not (tmp_path/'monthly_reports').exists()


def test_full_fixture_controls_and_saved_output_without_browser(tmp_path):
    # Subprocess confines fixture's process-wide outbound-network audit guard.
    script=r'''
from io import BytesIO
from pathlib import Path
import json,re,sys
from html import unescape
from streamlit.testing.v1 import AppTest
from scripts.workspace_cover_template_fallback import make_source,EDITED
from app import monthly_report_section_ui as ui
source=make_source(Path(sys.argv[1])/'input');upload=BytesIO(source.read_bytes())
upload.name=source.name;upload.size=len(upload.getvalue())
real=ui.st.file_uploader
ui.st.file_uploader=lambda label,*a,**kw: upload if label=='Starting report' else real(label,*a,**kw)
# Container-only seam: AppTest does not serialize lazy-expander events.
real_expander=ui.st.expander
class OpenContainer:
 def __init__(self,box):self.box=box;self.open=True
 def __enter__(self):return self.box.__enter__()
 def __exit__(self,*args):return self.box.__exit__(*args)
ui.st.expander=lambda *a,**kw:OpenContainer(real_expander(*a,**kw))
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py',default_timeout=60)
app.session_state['_monthly_dom_app_test_token']='d'*32
app.run();assert not app.exception
next(b for b in app.button if b.label=='Install synthetic independent template').click().run()
assert not app.exception,[e.message for e in app.exception]
assert any('limited to 24 MiB' in w.value for w in app.warning)
radio=next(r for r in app.radio if r.key.endswith('_section_activity_action'))
radio.set_value('Edit text or change pictures').run()
next(t for t in app.text_area if t.label=='Work completed this month').set_value(EDITED).run()
next(b for b in app.button if b.label=='Use ENFRA template and keep this review').click().run()
assert not app.exception,[e.message for e in app.exception]
def receipt():
 text=next(x.proto.body for x in app.get('html') if 'data-enfra-template-fallback=' in x.proto.body)
 return json.loads(unescape(re.search('data-enfra-template-fallback="([^"]+)"',text)[1]))
assert not receipt()['saved'] and EDITED in receipt()['staged_texts']
next(b for b in app.button if b.label=='Continue to this month’s updates').click().run()
assert not app.exception,[e.message for e in app.exception]
assert receipt()['saved']
next(b for b in app.button if b.label=='Build saved synthetic DOCX').click().run()
assert not app.exception,[e.message for e in app.exception]
assert receipt()['output']['edited_text_present'] and receipt()['output']['unread_source_art_absent']
'''
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    env={**os.environ,'EPC_DATA_DIR':str(tmp_path),'EPC_MONTHLY_DOM_FIXTURE':'1',
         'EPC_MONTHLY_COVER_FALLBACK_TASK':'1','EPC_MONTHLY_DOM_APPTEST':'1',
         'ANTHROPIC_API_KEY':'','SMARTSHEET_API_MODE':'disabled'}
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=Path(__file__).resolve().parents[1],
                          env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert not (tmp_path/'monthly_reports').exists()
