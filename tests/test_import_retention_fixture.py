"""Validate disposable fixture wiring without claiming native-browser proof."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.workspace_import_retention import make_source, FIRST, SECOND


def test_sources_reproduce_both_production_classification_paths(tmp_path):
    from app.monthly_report_import import inspect_docx
    from app.monthly_report_start_import import analyze_starting_report
    from app.monthly_report_model import synthetic_profiles, ReportPeriod
    p=synthetic_profiles()[0];sites=synthetic_profiles()[1].facilities
    stale=analyze_starting_report(inspect_docx(make_source(tmp_path,'stale')),p,ReportPeriod(2026,9),sites)
    assert stale.site_relation=='same' and len(stale.period_review_items)==2
    scope=analyze_starting_report(inspect_docx(make_source(tmp_path,'scope')),p,ReportPeriod(2026,9),sites)
    assert scope.site_relation=='other'


@pytest.mark.parametrize('scenario',('stale','scope'))
def test_full_isolated_fixture_save(tmp_path,scenario):
    script=r'''
from io import BytesIO
from pathlib import Path
from streamlit.testing.v1 import AppTest
import sys,json,re
from html import unescape
from scripts.workspace_import_retention import make_source,EDITED,FIRST
from app import monthly_report_section_ui as ui
source=make_source(Path(sys.argv[1])/'input',sys.argv[2]);upload=BytesIO(source.read_bytes())
upload.name=source.name;upload.size=len(upload.getvalue())
real=ui.st.file_uploader
ui.st.file_uploader=lambda label,*a,**kw: upload if label=='Starting report' else real(label,*a,**kw)
app=AppTest.from_file('tests/fixtures/workspaces/monthly_app.py',default_timeout=60)
app.session_state['_monthly_dom_app_test_token']='d'*32
app.run();assert not app.exception
next(b for b in app.button if b.label=='Prepare disposable site catalog').click().run()
assert not app.exception,[e.message for e in app.exception]
if sys.argv[2]=='stale':
 next(r for r in app.radio if r.key.endswith('_section_activity_action')).set_value('Edit text or change pictures').run()
 next(t for t in app.text_area if t.label=='Work completed this month').set_value(EDITED).run()
 next(c for c in app.checkbox if c.label=='This work belongs in September 2026').check().run()
else:
 app.multiselect[0].set_value(['north']).run()
 next(b for b in app.button if b.label=='Confirm source sites').click().run()
next(b for b in app.button if b.label=='Continue to this month’s updates').click().run()
assert not app.exception,[e.message for e in app.exception]
text=next(x.proto.body for x in app.get('html') if 'data-import-retention=' in x.proto.body)
r=json.loads(unescape(re.search('data-import-retention="([^"]+)"',text)[1]))
assert r['saved'] and r['sites']==['north'] and any(FIRST in t for t in r['saved_texts'])
'''
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    env={**os.environ,'EPC_DATA_DIR':str(tmp_path),'EPC_MONTHLY_DOM_FIXTURE':'1',
         'EPC_MONTHLY_IMPORT_RETENTION_TASK':'1','EPC_MONTHLY_DOM_APPTEST':'1',
         'ANTHROPIC_API_KEY':'','SMARTSHEET_API_MODE':'disabled'}
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path),scenario],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert not (tmp_path/'monthly_reports').exists()


def test_native_receipt_cannot_pass_with_setup_failure_missing_or_running_cases():
    from scripts.qa_import_retention import all_cases_passed
    assert not all_cases_passed({'cases':{},'failures':[]})
    cases={engine+'/'+scenario:{'result':'passed'} for engine in ('chromium','playwright-webkit') for scenario in ('stale','scope')}
    assert all_cases_passed({'cases':cases,'failures':[]})
    assert not all_cases_passed({'cases':cases,'failures':['setup failed']})
    for key in cases:
        partial={k:v for k,v in cases.items() if k!=key}
        assert not all_cases_passed({'cases':partial,'failures':[]})
        assert not all_cases_passed({'cases':{**cases,key:{'result':'running'}},'failures':[]})


def test_atomic_receipt_gate_rejects_duplicate_running_and_stale_dom():
    import json
    from scripts.qa_import_receipts import READY_RECEIPT_JS
    script = r'''
const assert = require('node:assert/strict');
const check = eval('(' + process.argv[1] + ')');
let state = 'notRunning', values = [];
global.document = {
 querySelector: () => ({getAttribute: () => state}),
 querySelectorAll: () => values.map(value => ({getAttribute: () => value}))
};
const arg = {selector:'[data-test]', attribute:'data-test', expected:{saved:true,'output.kept':true}};
const good = JSON.stringify({saved:true,output:{kept:true},source_sha256:'unchanged'});
values = [good]; assert.equal(check(arg).source_sha256, 'unchanged');
values = [good, good]; assert.equal(check(arg), false);
values = [good, JSON.stringify({saved:false})]; assert.equal(check(arg), false);
values = []; assert.equal(check(arg), false);
values = [JSON.stringify({saved:false})]; assert.equal(check(arg), false);
values = [good]; state = 'running'; assert.equal(check(arg), false);
state = 'notRunning'; values = ['invalid json']; assert.equal(check(arg), false);
values = [JSON.stringify({saved:true,output:{kept:false}})]; assert.equal(check(arg), false);
'''
    result=subprocess.run(['node','-e',script,READY_RECEIPT_JS],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr
