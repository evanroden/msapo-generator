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


def test_confirmation_settlement_rejects_transient_and_persistent_duplicate_cards():
    from scripts.qa_import_retention import SETTLED_CONFIRMATION_JS
    script = r'''
const assert = require('node:assert/strict');
const check = eval('(' + process.argv[1] + ')');
let state = 'notRunning', nodes = [];
const node = (checked, stale=false, title='Monthly Activity Summary') => ({
 checked,
 getAttribute: () => 'This work belongs in September 2026',
 closest: selector => selector === '[data-stale="true"]' ? (stale ? {} : null) :
   {querySelector: () => ({textContent: title})}
});
global.document = {
 querySelector: () => ({getAttribute: () => state}),
 querySelectorAll: () => nodes
};
const arg = {label:'This work belongs in September 2026'};
nodes=[node(false)]; assert.equal(check(arg),false);
nodes=[node(true)]; state='running'; assert.equal(check(arg),false);
state='notRunning'; nodes=[node(true,true)]; assert.equal(check(arg),false);
// The actual trace briefly retained one current and one stale keyed card.
nodes=[node(true),node(true,true)]; assert.equal(check(arg),false);
nodes=[node(true)]; assert.equal(check(arg),true);
// A genuine persistent duplicate never becomes acceptable, even if both agree.
nodes=[node(true),node(true)];
for(let frame=0;frame<100;frame++) assert.equal(check(arg),false);
const pollFrames = frames => {
 for (const frame of frames) { nodes=frame; if(check(arg)) return true; }
 throw new Error('confirmation never became unique and current');
};
assert.equal(pollFrames([[node(false)], [node(true),node(true,true)], [node(true)]]),true);
assert.throws(() => pollFrames(Array.from({length:100}, () => [node(true),node(true)])),
 /never became unique/);
nodes=[]; assert.equal(check(arg),false);
nodes=[node(true,false,'Training')]; assert.equal(check(arg),false);
nodes=[node(true,false,'Activity Summary')]; assert.equal(check(arg),true);
'''
    result=subprocess.run(['node','-e',script,SETTLED_CONFIRMATION_JS],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr


def test_confirmation_wait_preserves_strict_native_assertion_and_five_second_budget():
    from scripts.qa_import_retention import wait_for_settled_confirmation, SETTLED_CONFIRMATION_JS
    class Handle:
        disposed = False
        def dispose(self): self.disposed = True
    handle = Handle()
    class Page:
        def wait_for_function(self, expression, *, arg, timeout):
            assert expression == SETTLED_CONFIRMATION_JS
            assert arg == {'label': 'This work belongs in September 2026'}
            assert timeout == 5000
            return handle
    remaining = wait_for_settled_confirmation(Page(), 'This work belongs in September 2026')
    assert 0 < remaining <= 5000
    assert handle.disposed
    source=Path('scripts/qa_import_retention.py').read_text()
    assert "label.click()\n                remaining = wait_for_settled_confirmation(page, 'This work belongs in September 2026')\n                expect(confirmation).to_be_checked(timeout=remaining)" in source
