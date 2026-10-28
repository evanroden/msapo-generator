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
    cases={e+'/'+s:{'result':'passed'} for e in ENGINES for s in SCENARIOS}
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
stale=a.session_state['financial_draft'];assert not page_allowed(stale.sources[0],2,profile=stale.profile,destination='mbcx_report')
check('Review client');a.multiselect[0].set_value([1,2]).run();assert not next(c for c in a.checkbox if c.label.startswith('I reviewed')).value
check('I reviewed');button('Include reviewed financial pages')
renewed=a.session_state['financial_draft']
assert renewed.blocks[-1].asset_hashes==accepted.blocks[-1].asset_hashes
assert [i.key for i in renewed.blocks[-1].asset_instances]==[i.key for i in accepted.blocks[-1].asset_instances]
assert renewed.blocks[-1].asset_captions==accepted.blocks[-1].asset_captions
assert not [c for c in preflight(renewed) if c.blocking]
button('Save synthetic draft')
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
