"""Local harness contracts; these are not native-browser acceptance evidence."""
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]


def test_inputs_are_real_bounded_mixed_pdfs_and_no_auto_financial_grants(tmp_path,monkeypatch):
    from scripts.workspace_financial_pages import make_source
    from app.monthly_report_model import synthetic_profiles
    from app import monthly_report_sources as sources
    from app.monthly_report_mbcx_financial_pages import known_vendor_total
    monkeypatch.setenv('EPC_DATA_DIR',str(tmp_path/'data'))
    p=synthetic_profiles()[0]
    for vendor in (False,True):
        path=make_source(tmp_path,vendor);assert path.stat().st_size<10000
        content,_=sources.ingest(p,path.name,path.read_bytes())
        assert len(content.source.page_texts)==3 and content.source.classification=='MBCx'
        assert not content.source.financial_source_review and not content.source.financial_page_reviews
        assert known_vendor_total(content.source,3)==vendor


def test_native_gate_requires_both_complete_engines_and_scenarios():
    from scripts.qa_financial_pages import all_cases_passed,ENGINES,SCENARIOS
    cases={e+'/'+s:{'result':'passed','date_selector_contract':'passed'} for e in ENGINES for s in SCENARIOS}
    assert all_cases_passed({'cases':cases,'failures':[]})
    assert not all_cases_passed({'cases':{},'failures':[]})
    assert not all_cases_passed({'cases':cases,'failures':['failure']})
    for key in cases:
        assert not all_cases_passed({'cases':{k:v for k,v in cases.items() if k!=key},'failures':[]})
        assert not all_cases_passed({'cases':{**cases,key:{'result':'running'}},'failures':[]})


@pytest.mark.parametrize('vendor',(False,True))
def test_actual_ordered_section_fixture_review_recovery_and_save(tmp_path,vendor):
    script=r'''
from pathlib import Path
from io import BytesIO
from datetime import date
from streamlit.testing.v1 import AppTest
from scripts.workspace_financial_pages import make_source
from app import monthly_report_upload_ui as ui
from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import page_allowed
import sys
f=make_source(Path(sys.argv[1]),sys.argv[2]=='True');u=BytesIO(f.read_bytes());u.name=f.name;u.size=len(u.getvalue())
# AppTest cannot deliver upload bytes; this local seam is NOT used by native QA.
real=ui.st.file_uploader;ui.st.file_uploader=lambda *a,**kw:[u]
a=AppTest.from_file(str(Path.cwd()/'tests/fixtures/workspaces/monthly_app.py'),default_timeout=60)
a.session_state['_monthly_dom_app_test_token']='a'*32;a.run()
def button(label):
 next(b for b in a.button if b.label==label).click().run();assert not a.exception,[e.message for e in a.exception]
def check(starts,value=True):
 next(c for c in a.checkbox if c.label.startswith(starts)).set_value(value).run();assert not a.exception
next(t for t in a.toggle if t.label=='Review individual pages').set_value(True).run();assert not a.exception
button('Include page');button('Add reviewed pages')
ordinary=a.session_state['financial_draft'];assert len(ordinary.blocks[-1].asset_hashes)==1
check('Review client');a.multiselect[0].set_value([2]).run()
assert next(b for b in a.button if b.label=='Include reviewed financial pages').disabled
assert not a.session_state['financial_draft'].sources[0].financial_page_reviews
check('This is an ENFRA')
assert next(b for b in a.button if b.label=='Include reviewed financial pages').disabled
a.selectbox[0].set_value('Preview unavailable').run()
assert next(c for c in a.checkbox if c.label.startswith('I reviewed')).disabled
assert not a.session_state['financial_draft'].sources[0].financial_page_reviews
a.selectbox[0].set_value('None').run()
assert len(a.get('image'))>=1
check('I reviewed');button('Include reviewed financial pages')
accepted=a.session_state['financial_draft'];assert len(accepted.blocks[-1].asset_hashes)==2
assert accepted.blocks[-1].asset_instances[0]==ordinary.blocks[-1].asset_instances[0]
assert page_allowed(accepted.sources[0],1,profile=accepted.profile,destination='mbcx_report')
a.multiselect[0].set_value([2,3]).run();before=a.session_state['financial_draft']
if sys.argv[2]=='True':
 assert next(b for b in a.button if b.label=='Include reviewed financial pages').disabled
else:
 a.selectbox[0].set_value('Last page preparation fails').run();check('I reviewed');button('Include reviewed financial pages')
 assert any('No selected pages' in c.value for c in a.caption)
assert a.session_state['financial_draft']==before
a.selectbox[0].set_value('None').run();a.multiselect[0].set_value([2]).run();check('I reviewed');button('Include reviewed financial pages')
check('Review client',False)
next(c for c in a.date_input if c.label=='Source date').set_value(date(2026,9,2)).run();button('Use these source details')
stale=a.session_state['financial_draft'];assert stale.sources[0].service_date=='2026-09-02'
assert not page_allowed(stale.sources[0],2,profile=stale.profile,destination='mbcx_report')
check('Review client')
w=a.multiselect[0]
assert w.value==[2], w.value
assert [int(w.proto.options[i].split()[1]) for i in w.proto.default]==w.value
assert not w.proto.set_value
assert not page_allowed(a.session_state['financial_draft'].sources[0],2,profile=stale.profile,destination='mbcx_report')
a.multiselect[0].set_value([1,2]).run();assert not next(c for c in a.checkbox if c.label.startswith('I reviewed')).value
check('I reviewed');button('Include reviewed financial pages')
renewed=a.session_state['financial_draft']
assert renewed.blocks[-1].asset_hashes==accepted.blocks[-1].asset_hashes
assert [i.key for i in renewed.blocks[-1].asset_instances]==[i.key for i in accepted.blocks[-1].asset_instances]
assert renewed.blocks[-1].asset_captions==accepted.blocks[-1].asset_captions
assert not [c for c in preflight(renewed) if c.blocking]
# The unreviewed third page has been displayed but never edited or accepted.
assert 3 not in dict(renewed.sources[0].captions)
button('Save synthetic draft')
ui.st.file_uploader=lambda *a,**kw:[]
# New native browser session restores exclusively from the real snapshot.
b=AppTest.from_file(str(Path.cwd()/'tests/fixtures/workspaces/monthly_app.py'),default_timeout=60)
b.session_state['_monthly_dom_app_test_token']='a'*32;b.run();assert not b.exception
assert b.session_state['financial_draft']==renewed
'''
    (tmp_path/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    env={**os.environ,'EPC_DATA_DIR':str(tmp_path),'EPC_MONTHLY_DOM_FIXTURE':'1',
        'EPC_MONTHLY_FINANCIAL_PAGES_TASK':'1','EPC_MONTHLY_DOM_APPTEST':'1','ANTHROPIC_API_KEY':'','SMARTSHEET_API_MODE':'disabled'}
    result=subprocess.run([sys.executable,'-c',script,str(tmp_path),str(vendor)],cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stdout+result.stderr
    assert not (tmp_path/'monthly_reports').exists()


def test_hosted_workflow_requires_actual_pdf_and_no_native_bypass():
    workflow=(ROOT/'.github/workflows/monthly-financial-pages.yml').read_text()
    native=(ROOT/'scripts/qa_financial_pages.py').read_text()
    assert 'libreoffice-writer' in workflow and 'libreoffice-calc' in workflow
    assert "assert not root.findall('.//skipped')" in workflow
    assert 'chromium webkit' in workflow
    assert 'set_input_files' in native and 'verify_outputs' in native
    assert 'force=True' not in native and 'add_init_script' not in native and 'session_state' not in native


@pytest.mark.parametrize('mutation',('none','word_vendor','pdf_vendor','pdf_duplicate','pdf_text','word_text'))
def test_output_oracle_uses_input_page_identity_not_report_asset_claims(tmp_path,mutation):
    from io import BytesIO
    from docx import Document
    import fitz
    from scripts.workspace_financial_pages import make_source
    from scripts.qa_financial_pages import independent_page_pixels,verify_outputs
    source=make_source(tmp_path,vendor=True);images=independent_page_pixels(source)
    doc=Document();pdf=fitz.open()
    for number in ((0,2) if mutation=='word_vendor' else (0,1)):
        raw=BytesIO();images[number].save(raw,format='PNG');doc.add_picture(BytesIO(raw.getvalue()))
    if mutation=='word_text':doc.add_paragraph('Vendor invoice Total: $450.')
    for name in ('preview.docx','report.docx'):doc.save(tmp_path/name)
    choices=(0,2) if mutation=='pdf_vendor' else (0,0) if mutation=='pdf_duplicate' else (0,1)
    for number in choices:
        raw=BytesIO();images[number].save(raw,format='PNG')
        page=pdf.new_page();page.insert_image(page.rect,stream=raw.getvalue())
        if mutation=='pdf_text':page.insert_text((40,30),'Vendor invoice Total: $450.')
    pdf.save(tmp_path/'report.pdf');pdf.close()
    if mutation!='none':
        with pytest.raises(AssertionError):verify_outputs(tmp_path,source)
    else:assert verify_outputs(tmp_path,source)['report.pdf']['pages']==2


@pytest.mark.parametrize('labels,expected',[
    (('Image page for MBCx report','MBCx report files'),1),
    (('MBCx report files','Image page for MBCx report'),1),
    (('MBCx report files',),1),
    (('Image page for MBCx report','MBCx report files extra'),0),
    (('MBCx report files','MBCx report files'),2),
])
def test_source_upload_locator_is_exact_unique_and_not_image_owner(monkeypatch,labels,expected):
    """Offline locator contract, not native-browser proof.

    Model the fluent locator operations against two independently labelled DOM
    subtrees. Duplicate or missing source owners must fail before any upload.
    """
    import sys
    from types import SimpleNamespace
    from scripts.qa_financial_pages import upload_source_pdf
    uploads=[]
    class Locator:
        def __init__(self,nodes):self.nodes=nodes
        def filter(self,*,has):
            return Locator([n for n in self.nodes if n['label'] in has.nodes])
        def locator(self,selector):
            assert selector=='input[type=file]'
            return Locator(self.nodes)
        def set_input_files(self,path):
            assert len(self.nodes)==1
            uploads.append((self.nodes[0]['label'],path))
    class Page:
        def get_by_test_id(self,identifier):
            assert identifier=='stFileUploader'
            return Locator([{'label':label} for label in labels])
        def get_by_text(self,text,*,exact):
            assert exact is True and text=='MBCx report files'
            return Locator([label for label in labels if label==text])
    class Expect:
        def __init__(self,locator):self.locator=locator
        def to_have_count(self,count):assert len(self.locator.nodes)==count
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    if expected!=1:
        with pytest.raises(AssertionError):upload_source_pdf(Page(),Path('synthetic.pdf'))
        assert uploads==[]
    else:
        upload_source_pdf(Page(),Path('synthetic.pdf'))
        assert uploads==[('MBCx report files','synthetic.pdf')]


def test_source_upload_label_matches_production_owner_and_ui_call_is_preserved():
    from app.monthly_report_section_uploads import SECTION_UPLOADS
    from scripts.qa_financial_pages import upload_source_pdf,exercise
    import inspect
    assert SECTION_UPLOADS['mbcx_report'][1]=='MBCx report files'
    helper=inspect.getsource(upload_source_pdf)
    assert 'first(' not in helper and 'nth(' not in helper and 'force=' not in helper
    assert "get_by_text('MBCx report files',exact=True)" in helper
    flow=inspect.getsource(exercise)
    assert "name='Add files',exact=True" not in flow
    assert flow.index('upload_source_pdf(page,source)') < flow.index('select_individual_pages(page)')
    assert flow.index('select_individual_pages(page)') < flow.index("name='Include page',exact=True")


@pytest.mark.parametrize('labels', [
    ('Review individual pages',),
    ('Other choice', 'Review individual pages'),
    (),
    ('Review individual pages extra',),
    ('Review individual pages', 'Review individual pages'),
])
def test_individual_page_route_uses_one_exact_native_control(monkeypatch, labels):
    """Offline locator contract; no browser execution or synthetic app bypass."""
    import sys
    from types import SimpleNamespace
    from scripts.qa_financial_pages import select_individual_pages
    checks = []
    class Control:
        def __init__(self, matched):self.matched=matched
        def check(self):
            assert len(self.matched)==1
            checks.append(self.matched[0])
    class Page:
        def get_by_label(self, label, *, exact):
            assert label=='Review individual pages' and exact is True
            return Control([s for s in labels if s==label])
    class Expect:
        def __init__(self,control):self.control=control
        def to_have_count(self,count):assert len(self.control.matched)==count
        def to_be_visible(self):assert len(self.control.matched)==1
        def to_be_enabled(self):assert len(self.control.matched)==1
        def to_be_checked(self):assert checks==['Review individual pages']
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    if labels.count('Review individual pages')!=1:
        with pytest.raises(AssertionError):select_individual_pages(Page())
        assert checks==[]
    else:
        select_individual_pages(Page())
        assert checks==['Review individual pages']


@pytest.mark.parametrize('labels,expected',[
    (('Report date','Source date'),1),
    (('Source date','Report date'),1),
    (('Source date',),1),
    (('Source date extra','Report date'),0),
    (('Source date','Source date'),2),
])
def test_native_date_field_is_scoped_by_visible_widget_label(monkeypatch,labels,expected):
    """Offline contract models the observed native input's non-label aria name."""
    import sys
    from types import SimpleNamespace
    from scripts.qa_financial_pages import fill_source_date
    events=[]
    class Locator:
        def __init__(self,nodes):self.nodes=nodes
        def filter(self,*,has):return Locator([n for n in self.nodes if n in has.nodes])
        def get_by_test_id(self,testid):
            assert testid=='stDateInputField'
            return Field(self.nodes)
    class Field(Locator):
        def fill(self,value):
            assert len(self.nodes)==1;events.append(('fill',self.nodes[0],value))
        def press(self,key):events.append(('press',key))
    class Details(Locator):
        def __init__(self):self.nodes=['details']
        def get_by_test_id(self,testid):
            assert testid=='stDateInput';return Locator(list(labels))
        def get_by_text(self,*args,**kwargs):raise AssertionError('has locator must not repeat ancestor details')
    class Page:
        def get_by_text(self,label,*,exact):
            assert exact and label=='Source date';return Locator([v for v in labels if v==label])
        def get_by_role(self,*args,**kwargs):raise AssertionError('Visible Source date is not a textbox accessible name')
    class Expect:
        def __init__(self,locator):self.locator=locator
        def to_have_count(self,n):assert len(self.locator.nodes)==n
        def to_be_visible(self):assert len(self.locator.nodes)==1
        def to_be_enabled(self):assert len(self.locator.nodes)==1
    monkeypatch.setitem(sys.modules,'playwright.sync_api',SimpleNamespace(expect=Expect))
    if expected!=1:
        with pytest.raises(AssertionError):fill_source_date(Page(),Details(),'2026-09-02')
        assert not events
    else:
        fill_source_date(Page(),Details(),'2026-09-02')
        assert events==[('fill','Source date','2026-09-02'),('press','Tab')]


def test_date_control_keeps_form_submission_and_canonical_receipt_assertion():
    import inspect
    from scripts.qa_financial_pages import fill_source_date,exercise
    helper=inspect.getsource(fill_source_date)
    assert 'first(' not in helper and 'force=' not in helper and 'timeout=' not in helper
    flow=inspect.getsource(exercise)
    assert "fill_source_date(page,details,'2026-09-02')" in flow
    assert "name='Use these source details',exact=True" in flow
    assert "'sources.0.service_date':'2026-09-02'" in flow


def test_hosted_selector_contract_is_required_for_case_acceptance():
    from scripts.qa_financial_pages import all_cases_passed,ENGINES,SCENARIOS,date_selector_contract,exercise
    import inspect
    cases={e+'/'+s:{'result':'passed','date_selector_contract':'passed'} for e in ENGINES for s in SCENARIOS}
    for key in cases:
        for status in (None,'running','failed'):
            assert not all_cases_passed({'cases':{**cases,key:{'result':'passed','date_selector_contract':status}},'failures':[]})
    contract=inspect.getsource(date_selector_contract)
    assert 'probe.set_content' in contract and 'expect(wrong).to_have_count(0)' in contract
    assert "fill_source_date(probe,owner,'2026-09-02')" in contract
    assert '.to_have_count(2)' in contract and '.to_have_count(0)' in contract
    assert 'date_selector_contract(context)' in inspect.getsource(exercise)
    assert 'force=' not in contract and '.first' not in contract


def test_native_page_actions_require_visible_choices_matching_server_receipt():
    import inspect
    from scripts.qa_financial_pages import exercise
    flow=inspect.getsource(exercise)
    assert "current=receipt(page)['review_pages']" in flow
    assert "r'^Remove Page '" in flow and '.to_have_count(len(current))' in flow
    assert "act(lambda:combo.press('Backspace'))" in flow


def test_component_diagnostics_identify_caption_only_without_changing_digest():
    from dataclasses import replace
    from scripts.workspace_financial_pages import draft_component_hashes
    from app.monthly_report_model import ReportDraft, ReportPeriod, ReportSource, synthetic_profiles
    source=ReportSource('synthetic','client.pdf','a'*64,'.pdf')
    draft=ReportDraft(synthetic_profiles()[0],ReportPeriod(2026,9),'Synthetic',(),(),sources=(source,))
    changed=replace(draft,sources=(replace(source,captions=((3,'client.pdf · page/item 3'),)),))
    before=draft.fingerprint
    a,b=draft_component_hashes(draft),draft_component_hashes(changed)
    assert {key for key in a if a[key]!=b[key]}=={'sources','sources.0.captions'}
    assert draft.fingerprint==before and changed.fingerprint!=before
