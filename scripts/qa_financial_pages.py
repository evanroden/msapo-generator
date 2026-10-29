"""Hosted Chromium/WebKit acceptance, real upload and production MBCx UI.

No local browser execution is required. Only synthetic inputs are uploaded to a
loopback, cookie-isolated server. Failure injection can deny, never approve.
"""
from contextlib import ExitStack
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from zipfile import ZipFile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.qa_about_logo_refresh import controller_environment
from scripts.qa_import_receipts import wait_receipt
from scripts.workspace_financial_pages import make_source
from scripts.workspace_history_observations import namespace
OUT=ROOT/'test-artifacts/financial-pages';URL='http://127.0.0.1:8557'
ENGINES=('chromium','playwright-webkit');SCENARIOS=('client','vendor')
REPORT={'synthetic_only':True,'physical_device':False,'cases':{},'failures':[]}
OPEN='Review client-facing ENFRA financial pages'
SOURCE='This is an ENFRA report intended for the client'
VISUAL='I reviewed these pages: their amounts are client-facing ENFRA content, with no vendor-invoice totals'
INCLUDE='Include reviewed financial pages'


def all_cases_passed(report):
    return (set(report.get('cases',{}))=={e+'/'+s for e in ENGINES for s in SCENARIOS}
        and not report.get('failures') and all(c.get('result')=='passed' and c.get('date_selector_contract')=='passed' for c in report['cases'].values()))


def receipt(page,expected=None):return wait_receipt(page,'data-financial-pages',expected,timeout=120000)


def independent_page_pixels(source):
    # Independent oracle from the selected INPUT pages, not report asset IDs.
    import pymupdf as fitz
    from PIL import Image
    with fitz.open(source) as document:
        result=[]
        for page in document:
            image=Image.open(BytesIO(page.get_pixmap(dpi=150,alpha=False).tobytes('png'))).convert('RGB')
            image.thumbnail((1050,1350),Image.Resampling.LANCZOS)
            result.append(image)
    assert len(result)==3
    return result


def verify_outputs(directory, source):
    """Check actual Word/preview embedded pixels and real LibreOffice PDF paint."""
    import pymupdf as fitz
    from PIL import Image
    input_pages=independent_page_pixels(source)
    expected_assets=input_pages[:2];forbidden=input_pages[2]
    result={}
    for name in ('preview.docx','report.docx'):
        raw=(directory/name).read_bytes()
        with ZipFile(BytesIO(raw)) as z:
            media=[Image.open(BytesIO(z.read(n))).convert('RGB') for n in z.namelist() if n.startswith('word/media/')]
            xml=' '.join(z.read(n).decode(errors='replace') for n in z.namelist() if n.endswith('.xml'))
            assert '$450' not in xml and 'Vendor invoice' not in xml
        assert len(media)>=len(expected_assets),(name,len(media))
        for expected in expected_assets:
            assert any(image.size==expected.size and image.tobytes()==expected.tobytes() for image in media),name
        assert not any(image.size==forbidden.size and image.tobytes()==forbidden.tobytes() for image in media), 'Forbidden page3 embedded'
        marked=sum(any((r>200 and g<80 and b>200) or (r<50 and g>200 and b<50) for r,g,b in image.getdata()) for image in media)
        assert not any(any(r<50 and g>200 and b>200 for r,g,b in image.getdata()) for image in media), 'Forbidden page3 marker in Word media'
        assert marked==len(expected_assets), 'Unexpected unreviewed source page in '+name
        result[name]={'sha256':sha256(raw).hexdigest(),'images':len(media),'reviewed_page_images':marked}
    raw=(directory/'report.pdf').read_bytes()
    with fitz.open(stream=raw,filetype='pdf') as doc:
        colored=0;green=0;marked_pages=0;forbidden_pixels=0
        for page in doc:
            pixels=page.get_pixmap(colorspace=fitz.csRGB).samples
            marked=sum(r>200 and g<80 and b>200 for r,g,b in zip(pixels[::3],pixels[1::3],pixels[2::3]))
            green_page=sum(r<50 and g>200 and b<50 for r,g,b in zip(pixels[::3],pixels[1::3],pixels[2::3]))
            colored+=marked;green+=green_page;marked_pages+=bool(marked>100 or green_page>100)
            assert '$450' not in page.get_text() and 'Vendor invoice' not in page.get_text()
            forbidden_pixels+=sum(r<50 and g>200 and b>200 for r,g,b in zip(pixels[::3],pixels[1::3],pixels[2::3]))
        assert colored>1000 and green>1000 and marked_pages==len(expected_assets)
        assert forbidden_pixels<10, 'Forbidden page3 cyan marker in PDF'
        result['report.pdf']={'sha256':sha256(raw).hexdigest(),'pages':len(doc),'page1_magenta_pixels':colored,'page2_green_pixels':green,'forbidden_cyan_pixels':forbidden_pixels}
    return result


def upload_source_pdf(page, source):
    """Choose the source-file owner, not the separate image-page uploader.

    Keep strict uniqueness: duplicated/stale source owners must fail rather than
    silently choosing the first native input or uploading to another route.
    """
    from playwright.sync_api import expect
    uploader=page.get_by_test_id('stFileUploader').filter(
        has=page.get_by_text('MBCx report files',exact=True))
    expect(uploader).to_have_count(1)
    control=uploader.locator('input[type=file]')
    expect(control).to_have_count(1)
    control.set_input_files(str(source))


def source_date_widget(page, details):
    # `has` is evaluated relative to each candidate widget. Its inner locator
    # must start at the page, NOT include the ancestor details locator again.
    return details.get_by_test_id('stDateInput').filter(
        has=page.get_by_text('Source date',exact=True))


def fill_source_date(page, details, value):
    """The visible widget label owns a native field named 'Select a date.'."""
    from playwright.sync_api import expect
    expect(details).to_have_count(1)
    widget=source_date_widget(page,details)
    expect(widget).to_have_count(1)
    control=widget.get_by_test_id('stDateInputField')
    expect(control).to_have_count(1)
    expect(control).to_be_visible()
    expect(control).to_be_enabled()
    control.fill(value)
    control.press('Tab')


def date_selector_contract(context):
    """Hosted real selector engine test, isolated from the application/session.

    Minimal markup retains the observed Streamlit label/field/ancestor shape.
    This page has no report state and cannot prime an application review.
    """
    from playwright.sync_api import expect
    probe=context.new_page()
    def widget(label,identifier):
        return ('<div data-testid="stDateInput"><label data-testid="stWidgetLabel">'
                '<span aria-hidden="true"><div><p>'+label+'</p></div></span></label>'
                '<input id="'+identifier+'" data-testid="stDateInputField" '
                'aria-label="Select a date." type="text" placeholder="YYYY-MM-DD"></div>')
    def markup(labels):
        return ('<div data-testid="stExpander"><details open><summary>Date and facility · target</summary>'
                + ''.join(widget(label,'target-'+str(i)) for i,label in enumerate(labels))
                + '</details></div><div data-testid="stExpander"><details open>'
                '<summary>Other source</summary>'+widget('Source date','unrelated')+'</details></div>')
    def details():
        return probe.get_by_test_id('stExpander').filter(
            has=probe.locator('summary').filter(has_text='Date and facility · target'))
    try:
        probe.set_content(markup(('Report date','Source date')))
        owner=details()
        # Reproduce the old implementation's zero-match using Playwright itself.
        wrong=owner.get_by_test_id('stDateInput').filter(has=owner.get_by_text('Source date',exact=True))
        expect(wrong).to_have_count(0)
        expect(source_date_widget(probe,owner)).to_have_count(1)
        fill_source_date(probe,owner,'2026-09-02')
        expect(probe.locator('#target-1')).to_have_value('2026-09-02')
        expect(probe.locator('#target-0')).to_have_value('')
        expect(probe.locator('#unrelated')).to_have_value('')
        probe.set_content(markup(('Source date','Source date')))
        expect(source_date_widget(probe,details())).to_have_count(2)
        probe.set_content(markup(('Report date','Source date extra')))
        expect(source_date_widget(probe,details())).to_have_count(0)
    finally:
        probe.close()
    return 'passed'


def exercise(engine,name,source,base,scenario):
    from playwright.sync_api import expect
    out=OUT/name/scenario;out.mkdir(parents=True,exist_ok=True)
    record=REPORT['cases'][name+'/'+scenario]={'result':'running'}
    browser=engine.launch();context=browser.new_context(viewport={'width':1440,'height':1100})
    token=secrets.token_hex(16);context.add_cookies([{'name':'epc_device_id','value':token,'url':URL}])
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page();errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def guard(route):
        from urllib.parse import urlparse
        u=urlparse(route.request.url)
        if u.scheme in ('http','https') and u.netloc!='127.0.0.1:8557':external.append(route.request.url);route.abort()
        else:route.continue_()
    context.route('**/*',guard)
    def act(action):
        before=receipt(page)['render'];action()
        handle=page.wait_for_function("""before => {
          const app=document.querySelector('[data-testid="stApp"]');
          const nodes=document.querySelectorAll('[data-financial-pages]');
          if(app?.getAttribute('data-test-script-state')!=='notRunning'||nodes.length!==1)return false;
          try{return JSON.parse(nodes[0].getAttribute('data-financial-pages')).render>before;}catch{return false;}
        }""",arg=before,timeout=120000)
        handle.dispose();return receipt(page)
    def check(label,value=True):
        control=page.get_by_role('checkbox',name=label,exact=True)
        expect(control).to_have_count(1)
        if control.is_checked()!=value:act(lambda:control.locator('xpath=ancestor::label').click())
        if value:expect(control).to_be_checked()
        else:expect(control).not_to_be_checked()
        receipt(page)
    def select(label,text):
        if label=='Synthetic failure injection' and receipt(page)['fault']==text:return
        combo=page.get_by_role('combobox',name=label,exact=True)
        combo.click();act(lambda:page.get_by_role('option',name=text,exact=True).click())
    def pages(numbers):
        current=receipt(page)['review_pages']
        widget=page.get_by_test_id('stMultiSelect').filter(
            has=page.get_by_text('Pages to review together',exact=True))
        expect(widget).to_have_count(1)
        # Never treat a hidden/stale server choice as a removable native tag.
        # A mismatch is a product hydration failure, not a reason to skip an action.
        expect(widget.get_by_role('button',name=__import__('re').compile(r'^Remove Page '))).to_have_count(len(current))
        for number in current:
            expect(widget.get_by_role('button',name=__import__('re').compile(r'^Remove Page '+str(number)+r' ·'))).to_have_count(1)
        combo=page.get_by_role('combobox',name='Pages to review together',exact=True)
        # Ordinary keyboard removal, not DOM or session-state mutation.
        combo.click()
        for _ in range(len(current)):
            act(lambda:combo.press('Backspace'))
        combo.press('Escape');receipt(page)
        for number in numbers:
            combo.click();act(lambda:page.get_by_role('option',name=__import__('re').compile(r'^Page '+str(number)+r' ·')).click());combo.press('Escape')
    try:
        record['date_selector_contract']=date_selector_contract(context)
        page.goto(URL);receipt(page)
        page.get_by_role('button',name='Add files',exact=True).click()
        upload_source_pdf(page,source)
        initial=receipt(page,{'sources.0.sha256':sha256(source.read_bytes()).hexdigest()})
        assert len(initial['sources'])==1
        assert initial['sources'][0]['sha256']==sha256(source.read_bytes()).hexdigest()
        assert not initial['sources'][0]['financial_grants'] and not initial['assets']
        page.keyboard.press('Escape')
        # Existing nonfinancial route: real Include then ordinary Add reviewed pages.
        act(lambda:page.get_by_role('button',name='Include page',exact=True).click())
        act(lambda:page.get_by_role('button',name='Add reviewed pages',exact=True).click())
        ordinary=receipt(page);assert len(ordinary['assets'])==1
        assert ordinary['sources'][0]['allowed']==[1]
        check(OPEN);pages([2])
        include=page.get_by_role('button',name=INCLUDE,exact=True)
        expect(include).to_be_disabled()
        assert not receipt(page)['sources'][0]['financial_grants']
        check(SOURCE);expect(include).to_be_disabled() # source audience alone is not page approval
        select('Synthetic failure injection','Preview unavailable')
        expect(page.get_by_role('checkbox',name=VISUAL,exact=True)).to_be_disabled()
        expect(include).to_be_disabled();assert receipt(page)['assets']==ordinary['assets']
        assert not receipt(page)['sources'][0]['financial_grants']
        select('Synthetic failure injection','None')
        expect(page.get_by_test_id('stImage').first).to_be_visible()
        check(VISUAL);act(include.click)
        accepted=receipt(page);assert len(accepted['assets'])==2
        assert accepted['assets'][0]==ordinary['assets'][0]
        assert accepted['occurrences'][0]==ordinary['occurrences'][0]
        assert accepted['sources'][0]['financial_grants']==[2]
        assert accepted['sources'][0]['allowed']==[1,2]
        # Existing page2 + new page3 must reject as one batch, retaining all state.
        pages([2,3]);before=receipt(page)
        if scenario=='vendor':
            expect(page.get_by_text('Page 3 identifies a vendor-invoice total and cannot be included.',exact=True)).to_be_visible()
            expect(include).to_be_disabled()
        else:
            select('Synthetic failure injection','Last page preparation fails')
            check(VISUAL);act(include.click)
            expect(page.get_by_text('No selected pages or reviews were accepted. Your report is unchanged.',exact=True)).to_be_visible()
        rejected=receipt(page)
        for key in ('assets','occurrences','captions','sources','fingerprint'):assert rejected[key]==before[key],key
        select('Synthetic failure injection','None');pages([2])
        # Re-review the existing original in place: no duplicate, caption or ID loss.
        check(VISUAL);act(include.click);renewed=receipt(page)
        for key in ('assets','occurrences','captions'):assert renewed[key]==accepted[key],key
        # Change source date through production details; invalidates financial permission.
        check(OPEN,False)
        details=page.get_by_test_id('stExpander').filter(has=page.locator('summary').filter(has_text='Date and facility'))
        if not details.locator('details').evaluate('n=>n.open'):details.locator('summary').click()
        fill_source_date(page,details,'2026-09-02')
        act(lambda:details.get_by_role('button',name='Use these source details',exact=True).click())
        stale=receipt(page,{'sources.0.service_date':'2026-09-02'});assert 2 not in stale['sources'][0]['allowed']
        assert stale['assets']==accepted['assets']
        check(OPEN);pages([1,2]);expect(page.get_by_role('checkbox',name=VISUAL,exact=True)).not_to_be_checked()
        check(VISUAL);act(include.click);renewed=receipt(page)
        assert renewed['sources'][0]['allowed']==[1,2]
        for key in ('assets','occurrences','captions'):assert renewed[key]==accepted[key],key
        act(lambda:page.get_by_role('button',name='Save synthetic draft',exact=True).click())
        saved=receipt(page);assert saved['saved']==saved['fingerprint']
        page.reload();reopened=receipt(page)
        for key in ('assets','occurrences','captions','sources','fingerprint'):assert reopened[key]==saved[key],(key, {name:(saved.get('components',{}).get(name),value) for name,value in reopened.get('components',{}).items() if saved.get('components',{}).get(name)!=value})
        page.get_by_role('button',name='Build synthetic preview and outputs',exact=True).click()
        built=receipt(page,{'output.draft':reopened['fingerprint']})
        assert built['output']['pdf']>0 and built['output']['preview']>0
        target,_,_=namespace(base,token)
        record['output']=verify_outputs(target/'financial-output',source)
        (out/'uploaded-source.pdf').write_bytes(source.read_bytes())
        for f in (target/'financial-output').iterdir():(out/f.name).write_bytes(f.read_bytes())
        assert receipt(page)['sources']==reopened['sources']
        # The intake hashes the original; original bytes can use content-addressed names.
        assert all(s['sha256']==sha256(source.read_bytes()).hexdigest() for s in reopened['sources'])
        assert not (base/'monthly_reports').exists() and not errors and not external
        page.screenshot(path=str(out/'complete.png'),full_page=True)
        record.update(result='passed',initial=initial,ordinary=ordinary,accepted=accepted,rejected=rejected,reopened=reopened)
    except Exception as exc:
        record.update(result='failed',error=type(exc).__name__+': '+str(exc)[:2000])
        page.screenshot(path=str(out/'failure.png'),full_page=True)
        (out/'failure.html').write_text(page.content());raise
    finally:
        context.tracing.stop(path=str(out/'trace.zip'))
        (out/'receipt.json').write_text(json.dumps(record,indent=2));context.close();browser.close()


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True,exist_ok=True)
    REPORT['tested_checkout']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    with tempfile.TemporaryDirectory(prefix='financial-native-') as temp, ExitStack() as controller:
        base=Path(temp);(base/'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
        inputs={s:make_source(base/'input',vendor=s=='vendor') for s in SCENARIOS}
        controller.enter_context(controller_environment(base))
        env=dict(os.environ,EPC_DATA_DIR=temp,EPC_MONTHLY_DOM_FIXTURE='1',EPC_MONTHLY_FINANCIAL_PAGES_TASK='1',
            ANTHROPIC_API_KEY='',SMARTSHEET_API_MODE='disabled',PYTHONDONTWRITEBYTECODE='1')
        for key in tuple(env):
            if key.startswith('EPC_MONTHLY_') and (key.endswith('_TASK') or key=='EPC_MONTHLY_DOM_APPTEST') and key!='EPC_MONTHLY_FINANCIAL_PAGES_TASK':env.pop(key)
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/monthly_app.py','--server.address','127.0.0.1','--server.port','8557','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None:raise RuntimeError('Synthetic server stopped')
                    try:
                        with urlopen(URL+'/_stcore/health',timeout=1) as r:
                            if r.status==200:break
                    except OSError:time.sleep(.1)
                else:raise RuntimeError('Synthetic server not ready')
                with sync_playwright() as p:
                    for engine,name in ((p.chromium,ENGINES[0]),(p.webkit,ENGINES[1])):
                        for scenario,source in inputs.items():
                            try:exercise(engine,name,source,base,scenario)
                            except Exception as exc:REPORT['failures'].append(name+'/'+scenario+': '+str(exc)[:300])
            finally:
                process.terminate()
                try:process.wait(timeout=20)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                REPORT['result']='passed' if all_cases_passed(REPORT) else 'failed'
                (OUT/'results.json').write_text(json.dumps(REPORT,indent=2))
    if not all_cases_passed(REPORT):raise AssertionError('Financial native acceptance incomplete: '+str(REPORT['failures']))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        REPORT['result']='failed';REPORT['failures'].append(type(exc).__name__+': '+str(exc)[:1000])
        OUT.mkdir(parents=True,exist_ok=True);(OUT/'results.json').write_text(json.dumps(REPORT,indent=2));raise
