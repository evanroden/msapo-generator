"""Local actual expense UI browser checks; synthetic bytes, no external actions."""
from __future__ import annotations
import json
import os
import re
import shutil
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from urllib.parse import urlparse

import fitz
from dotenv import dotenv_values
from openpyxl import load_workbook
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-artifacts'/'expense-adaptive'
OUT.mkdir(parents=True,exist_ok=True)
URL='http://127.0.0.1:8518'
EVIDENCE={'synthetic_only':True,'browser_evidence':'Chromium and Playwright WebKit; injected segments are not hardware','checks':[]}


def check(name,passed,details=None):
    EVIDENCE['checks'].append({'name':name,'passed':bool(passed),'details':details})
    if not passed: raise AssertionError(name+': '+str(details))


def mode(page,expected):
    page.wait_for_function("expected=>document.querySelector('.epc-workspace')?.dataset.epcMode===expected",arg=expected)
    page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def inject(page,segments):
    page.evaluate("segments=>{Object.defineProperty(window,'viewport',{configurable:true,value:{segments}});window.dispatchEvent(new Event('resize'));}",segments)


def set_toggle(container,label,value,name):
    control=container.get_by_label(label,exact=True)
    # Streamlit 1.61 React Aria intentionally clips the semantic input inside
    # VisuallyHidden. The enclosing label is the normal pointer target.
    target=control.locator('xpath=ancestor::label[1]')
    target.scroll_into_view_if_needed()
    geometry=control.evaluate("""node=>{
        const label=node.closest('label'), r=label.getBoundingClientRect();
        const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
        return {input:node.getBoundingClientRect().toJSON(),label:r.toJSON(),
                inputClip:getComputedStyle(node).clip,parentClip:getComputedStyle(node.parentElement).clip,
                labelCenterHit:hit?.tagName,labelOwnsHit:Boolean(hit && label.contains(hit))};
    }""")
    if control.is_checked()!=value:
        target.click()
    expect(control).to_be_checked(checked=value)
    check(name+' normal label pointer toggles intended input',control.is_checked()==value,geometry)


def loaded_page(pair,index):
    image=pair.locator(f'figure[data-index="{index}"] img')
    expect(image).to_be_visible()
    expect(image).to_have_attribute('src',re.compile(r'^data:image/jpeg;base64,'))
    expect(image).to_have_js_property('complete',True)
    check(f'loaded preview page {index+1}',image.evaluate('(node)=>node.naturalWidth>0'))


def tabletop_reference(page, pair, title, name):
    expect(pair).to_have_attribute('data-epc-active','true')
    heading=pair.locator('.epc-context-title')
    expect(heading).to_have_text(title)
    expect(heading).to_be_visible()
    observed=pair.evaluate("""pair=>{
        const ref=pair.querySelector('.epc-workspace-reference');
        const title=ref.querySelector('.epc-context-title');
        const box=ref.getBoundingClientRect(), label=title.getBoundingClientRect();
        const hit=document.elementFromPoint(label.left+label.width/2,label.top+label.height/2);
        return {reference:box.toJSON(),title:label.toJSON(),
            unobscured:Boolean(hit&&title.contains(hit)),
            hidden:[...pair.closest('.epc-workspace').querySelectorAll('.epc-workspace-pair:not([data-epc-active="true"]) .epc-workspace-reference')]
                .map(node=>({display:getComputedStyle(node).display,rects:node.getClientRects().length}))};
    }""")
    check(name+' upper title fits active reference',
          observed['title']['top']>=observed['reference']['top'] and
          observed['title']['bottom']<=observed['reference']['bottom'] and observed['unobscured'],observed)
    # A hidden wrapper alone was insufficient: Streamlit child visibility
    # overrides leaked an inactive Mileage caption across the receipt preview.
    check(name+' inactive reference descendants cannot overlap active source',
          all(x['display']=='none' and x['rects']==0 for x in observed['hidden']),observed)




def preview_diagnostics(page):
    """Bounded geometry/readiness only; never receipt bytes or entered values."""
    return page.evaluate("""() => {
      const deep=(root,selector)=>{
        const nodes=[...root.querySelectorAll(selector)];
        for (const element of root.querySelectorAll('*'))
          if (element.shadowRoot) nodes.push(...deep(element.shadowRoot,selector));
        return nodes;
      };
      const rect=node=>node?.getBoundingClientRect().toJSON()||null;
      const root=document.querySelector('.epc-workspace');
      return {mode:root?.dataset.epcMode,root:rect(root),rootScroll:root?.scrollTop,
        viewport:{width:innerWidth,height:innerHeight},
        pairs:[...document.querySelectorAll('.epc-workspace-pair')].slice(0,24).map(pair=>{
          const panel=deep(pair,'.report-preview')[0];
          const state=panel?._previewState;
          let sent=null;
          try {const value=JSON.parse(state?.sent||'null');
            if(value) sent={visible:value.visible,pages:value.pages?.slice(0,2),dpi:value.dpi,generation:value.generation};
          } catch (_) {}
          return {id:pair.querySelector('[data-epc-pair]')?.dataset.epcPair,
            active:pair.dataset.epcActive,pair:rect(pair),
            reference:rect(pair.querySelector('.epc-workspace-reference')),panel:rect(panel),
            state:state?{page:state.page,visible:state.visible,sent,scope:state.scope,restore:state.restore}:null,
            images:deep(pair,'.report-preview figure').slice(0,2).map(figure=>{
              const image=figure.querySelector('img');return {index:figure.dataset.index,
                loaded:Boolean(image?.complete&&image.naturalWidth>0),width:image?.naturalWidth,height:image?.naturalHeight};
            }),
            acknowledgments:[...pair.querySelectorAll('[data-qa-preview-ack]')].slice(-2).map(node=>({
              key:node.dataset.qaPreviewAck,count:node.dataset.count,pages:node.dataset.requestPages}))};
        })};
    }""")


def preview_position(pair):
    return pair.locator('.report-preview').evaluate("""panel=>({
        page:panel._previewState.page,zoom:panel.querySelector('select').value,
        offset:panel._previewState.offset,scope:panel._previewState.scope,
        scrollTop:panel.querySelector('.report-preview-scroll').scrollTop,
        label:panel.querySelector('.report-preview-position').textContent
    })""")


def active_section(page, pair):
    pair.evaluate("""pair=>{const root=pair.closest('.epc-workspace');
        root.scrollTop+=pair.getBoundingClientRect().top-root.getBoundingClientRect().top+80;}
    """)
    expect(pair).to_have_attribute('data-epc-active','true')


def inspect_downloads(page, packet, name):
    packet.get_by_text('Other file and email options',exact=True).click()
    saved = {}
    for label, suffix in (('Download completed Excel report','xlsx'),('Download combined PDF packet','pdf')):
        with page.expect_download() as operation:
            packet.get_by_role('button',name=label,exact=True).click()
        download = operation.value
        path = OUT / f'{name}-actual-expense.{suffix}'
        download.save_as(path)
        saved[suffix] = path.read_bytes()
    workbook = load_workbook(BytesIO(saved['xlsx']),data_only=False)
    form=workbook['EXPENSE REIMBURSEMENT']
    check(name+' actual workbook preserves split lines and editable formulas',
          [form[f'H{row}'].value for row in (24,25,26)]==[13.25,11.25,24.5]
          and form['Q60'].value=='=H18+H39+H59'
          and form['C24'].value=='Unblurred synthetic expense correction'
          and form['C25'].value=='Synthetic split second reimbursement line',
          {'amounts':[form[f'H{row}'].value for row in (24,25,26)],'total_formula':form['Q60'].value})
    check(name+' each two-page receipt attached once despite split',len(workbook['RECEIPTS']._images)==4)
    with fitz.open(stream=saved['pdf'],filetype='pdf') as document:
        check(name+' real packet starts with signed form then original receipt pages',
              len(document)==5 and 'REIMBURSEMENT OF EXPENSES' in document[0].get_text()
              and 'Synthetic Employee' in document[0].get_text()
              and '49.00' in document[0].get_text()
              and all('Receipt 1 of 2' in document[i].get_text() for i in (1,2))
              and all('Receipt 2 of 2' in document[i].get_text() for i in (3,4)),
              {'pages':len(document),'expected_total':'49.00'})
    EVIDENCE.setdefault('generated_artifacts',{})[name]={suffix:sha256(raw).hexdigest() for suffix,raw in saved.items()}


def packet_journey(page, first, name):
    # Finish the existing split using normal controls, then invoke the actual
    # production generation button. The fixture calls the genuine builder.
    description=first.get_by_label('Description / business purpose *',exact=True)
    description.first.press('Tab')
    description.nth(1).fill('Synthetic split second reimbursement line')
    description.nth(1).press('Tab')
    amount=first.get_by_label('Reimbursable amount *',exact=True).nth(1)
    amount.fill('11.25');amount.press('Tab')
    confirmation='I confirm this generated signature represents me and will review it again before sending the Outlook draft.'
    set_toggle(page,confirmation,True,name+' generated signature')
    generate=page.get_by_role('button',name='Generate expense report and email draft',exact=True)
    expect(generate).to_be_enabled()
    generate.click()
    page.get_by_text('Synthetic expense generation count: 1',exact=True).wait_for(timeout=150000)
    packet=page.locator('.st-key-epc_pair_expense_packet')
    packet.scroll_into_view_if_needed()
    packet.locator('img[alt="Generated expense packet — page 1"]').wait_for(timeout=30000)
    loaded_page(packet,0)
    inspect_downloads(page,packet,name)
    packet.get_by_label('Preview zoom',exact=True).select_option('1.25')
    packet.get_by_role('button',name='Next preview page',exact=True).click()
    expect(packet.locator('.report-preview-position')).to_have_text('2 / 5')
    expect(packet.locator('[data-qa-preview-ack]')).to_have_attribute('data-request-pages',re.compile(r'(^|,)1(,|$)'))
    loaded_page(packet,1)
    before=preview_position(packet)
    app_runs=page.get_by_text(re.compile(r'^Synthetic full app runs:')).text_content()
    # Receipt inspection is deliberate navigation in the SAME ordered editor.
    # No synthetic compare control or fabricated packet is added to the app.
    inject(page,[{'x':0,'y':0,'width':1440,'height':420},{'x':0,'y':440,'width':1440,'height':560}]);mode(page,'tabletop')
    active_section(page,packet)
    tabletop_reference(page,packet,'Generated expense packet',name+' packet')
    loaded_page(packet,1)
    page.screenshot(path=str(OUT/f'{name}-actual-packet-tabletop.png'))
    active_section(page,first)
    tabletop_reference(page,first,'Receipt 1',name+' temporary receipt inspection')
    loaded_page(first,1)
    first.get_by_label('Preview zoom',exact=True).select_option('1.5')
    active_section(page,packet)
    tabletop_reference(page,packet,'Generated expense packet',name+' packet return')
    loaded_page(packet,1)
    inject(page,None);mode(page,'wide')
    after=preview_position(packet)
    check(name+' temporary source inspection restores exact generated packet view',
          all(before[key]==after[key] for key in ('page','zoom','scope','label'))
          and abs(before['offset']-after['offset'])<=3
          and abs(before['scrollTop']-after['scrollTop'])<=3,{'before':before,'after':after})
    check(name+' packet and receipt view changes cause no full rerun or generation',
          app_runs==page.get_by_text(re.compile(r'^Synthetic full app runs:')).text_content()
          and page.get_by_text('Synthetic expense generation count: 1',exact=True).count()==1)
    page.screenshot(path=str(OUT/f'{name}-actual-packet-wide.png'))
    # A real content correction still invalidates the old generated files.
    edited=first.get_by_label('Reimbursable amount *',exact=True).first
    edited.fill('12.25');edited.press('Tab')
    expect(packet).to_have_count(0)
    expect(page.get_by_role('button',name='Download combined PDF packet',exact=True)).to_have_count(0)
    check(name+' substantive edit withholds obsolete packet without regenerating',
          page.get_by_text('Synthetic expense generation count: 1',exact=True).count()==1)


def run(browser_type,name):
    browser=browser_type.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    from workspace_wire_observations import WireObservations
    wire=WireObservations(8518)
    wire.attach(page)
    errors=[];page.on('pageerror',lambda e:errors.append(getattr(e,'stack',None) or str(e)))
    blocked=[]
    def local_request(route):
        parsed=urlparse(route.request.url)
        if parsed.scheme in {'blob','data'} or (parsed.hostname=='127.0.0.1' and parsed.port==8518):
            route.continue_()
        else:
            blocked.append(parsed.scheme+':'+(parsed.hostname or 'external'))
            route.abort()
    page.context.route('**/*',local_request)
    EVIDENCE.setdefault('blocked_external',{})[name]=blocked
    try:
        page.goto(URL)
        mode(page,'wide')
        pairs=page.locator('.epc-workspace-pair:has([data-epc-pair^="expense_receipt_"])')
        expect(pairs).to_have_count(2)
        first=pairs.nth(0);second=pairs.nth(1)
        first.scroll_into_view_if_needed()
        expect(first.get_by_text('Preview · 2 pages',exact=True)).to_be_visible()
        loaded_page(first,0)
        set_toggle(first,'Split this receipt into multiple reimbursement lines',True,name+' receipt split')
        amount=first.get_by_label('Reimbursable amount *',exact=True).first
        amount.fill('13.25');amount.press('Tab')
        source=first.locator('.epc-workspace-reference')
        editor=first.locator('.epc-workspace-editor')
        bounds={'editor':editor.bounding_box(),'source':source.bounding_box()}
        check(name+' expense fields left of original source',bounds['editor']['x']<bounds['source']['x'],bounds)
        first.get_by_role('button',name='Next preview page',exact=True).click()
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        first.get_by_label('Preview zoom',exact=True).select_option('1.5')
        loaded_page(first,1)
        acknowledgement=first.locator('[data-qa-preview-ack]')
        expect(acknowledgement).to_have_attribute('data-request-pages','1')
        # A page/zoom change is a fragment-only view event, not a whole app rerun.
        counter=page.get_by_text(re.compile(r'^Synthetic full app runs:')).text_content()
        fragment_count=acknowledgement.get_attribute('data-count')
        first.get_by_role('button',name='Previous preview page',exact=True).click()
        expect(first.locator('.report-preview-position')).to_have_text('1 / 2')
        expect(acknowledgement).not_to_have_attribute('data-count',fragment_count)
        expect(acknowledgement).to_have_attribute('data-request-pages','0')
        loaded_page(first,0)
        check(name+' preview-only navigation does not rerun whole app',counter==page.get_by_text(re.compile(r'^Synthetic full app runs:')).text_content())
        first.get_by_role('button',name='Next preview page',exact=True).click()
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        expect(acknowledgement).to_have_attribute('data-request-pages','1')
        loaded_page(first,1)
        first.get_by_label('Preview zoom',exact=True).select_option('page')
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        inject(page,[{'x':0,'y':0,'width':640,'height':1000},{'x':672,'y':0,'width':768,'height':1000}]);mode(page,'book')
        first.get_by_role('button',name='Enlarge',exact=True).click()
        enlarged=first.locator('.report-preview').bounding_box()
        check(name+' enlargement stays clear of book crease',enlarged['x']>=678 and enlarged['x']+enlarged['width']<=1440 and enlarged['y']+enlarged['height']<=1000,enlarged)
        page.keyboard.press('Escape')
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        expect(first.get_by_label('Preview zoom',exact=True)).to_have_value('page')
        description=first.get_by_label('Description / business purpose *',exact=True).first
        description.fill('Unblurred synthetic expense correction')
        description.evaluate('(node)=>node.setSelectionRange(4,9)')
        current=description.evaluate('(node)=>({value:node.value,start:node.selectionStart,end:node.selectionEnd})')
        page.screenshot(path=str(OUT/f'{name}-expense-book.png'))
        inject(page,[{'x':0,'y':0,'width':1440,'height':420},{'x':0,'y':440,'width':1440,'height':560}]);mode(page,'tabletop')
        check(name+' unblurred expense text and selection preserved',current==description.evaluate('(node)=>({value:node.value,start:node.selectionStart,end:node.selectionEnd})'))
        check(name+' expense focus preserved',description.evaluate('(node)=>document.activeElement===node'))
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        expect(first.get_by_label('Preview zoom',exact=True)).to_have_value('page')
        tabletop_reference(page,first,'Receipt 1',name)
        loaded_page(first,1)
        page.screenshot(path=str(OUT/f'{name}-expense-tabletop.png'))
        first.get_by_role('button',name='Enlarge',exact=True).click()
        enlarged=first.locator('.report-preview').bounding_box()
        check(name+' enlargement stays in upper tabletop segment',enlarged['y']>=0 and enlarged['y']+enlarged['height']<=414+2,enlarged)
        page.keyboard.press('Escape')
        expect(first.locator('.report-preview-position')).to_have_text('2 / 2')
        expect(first.get_by_label('Preview zoom',exact=True)).to_have_value('page')
        page.locator('.epc-workspace').evaluate("root=>{const n=root.querySelectorAll('.epc-workspace-pair')[1];root.scrollTop+=n.getBoundingClientRect().top-root.getBoundingClientRect().top+80;}")
        expect(second).to_have_attribute('data-epc-active','true')
        tabletop_reference(page,second,'Receipt 2',name)
        loaded_page(second,0)
        check(name+' second receipt shows its own source',second.locator('.epc-workspace-reference').is_visible())
        inject(page,None);mode(page,'wide')
        expect(amount).to_have_value('13.25')
        check(name+' split preserved',first.get_by_label('Split this receipt into multiple reimbursement lines',exact=True).is_checked())
        packet_journey(page,first,name)
        mileage=browser.new_page(viewport={'width':1180,'height':820})
        wire.attach(mileage)
        mileage.goto(URL+'?mileage_only=1');mode(mileage,'wide')
        check(name+' mileage-only has no fabricated receipt',mileage.locator('[data-epc-pair^="expense_receipt_"]').count()==0)
        set_toggle(mileage,'Include reimbursable business mileage',True,name+' mileage')
        expect(mileage.get_by_label('Business miles *',exact=True)).to_be_visible()
        check(name+' mileage-only has actual trip review',mileage.get_by_text('Current trips and reimbursement',exact=True).count()==1)
        mileage.screenshot(path=str(OUT/f'{name}-mileage-only.png'))
        check(name+' no browser errors',not errors,errors)
        check(name+' zero external browser requests',not blocked,blocked)
    except Exception:
        try:
            EVIDENCE.setdefault('failure_diagnostics',{})[name]=preview_diagnostics(page)
            page.screenshot(path=str(OUT/f'{name}-failure.png'))
        except Exception as capture_error:
            EVIDENCE.setdefault('failure_capture_errors',{})[name]=str(capture_error)[:500]
        raise
    finally:
        (OUT/f'{name}-wire.json').write_text(json.dumps(wire.snapshot(),indent=2))
        browser.close()


def main():
    renderer=shutil.which('libreoffice') or shutil.which('soffice')
    if not renderer: raise RuntimeError('Expense actual-output browser acceptance requires LibreOffice Calc')
    EVIDENCE['renderer']=subprocess.check_output([renderer,'--version'],text=True).strip()
    EVIDENCE['output_builder']='app.expense_report.build_expense_package'
    with tempfile.TemporaryDirectory(prefix='expense-adaptive-synthetic-') as temp:
        (Path(temp)/'.synthetic-expense-fixture').write_text('synthetic-only')
        env=dict(os.environ,**{key:value for key,value in dotenv_values(ROOT/'.env.example').items() if value is not None})
        env.update(EPC_DATA_DIR=temp,ANTHROPIC_API_KEY='test-key-not-used',SMARTSHEET_API_MODE='disabled',PDF_BACKEND='libreoffice')
        with (OUT/'streamlit.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/expense_app.py','--server.address','127.0.0.1','--server.port','8518','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    if process.poll() is not None:raise RuntimeError('Synthetic expense fixture stopped')
                    try:
                        with urllib.request.urlopen(URL+'/_stcore/health',timeout=1) as result:
                            if result.status==200:break
                    except OSError:pass
                    time.sleep(.1)
                failures=[]
                with sync_playwright() as p:
                    for browser_type,name in ((p.chromium,'chromium'),(p.webkit,'playwright-webkit')):
                        try:
                            run(browser_type,name)
                        except Exception as exc:
                            # Independent fresh first attempts; preserve failures
                            # while allowing the other engine to collect evidence.
                            failures.append({'engine':name,'error':str(exc),'traceback':traceback.format_exc()})
                EVIDENCE['failures']=failures
                if failures:
                    raise AssertionError('Expense browser acceptance failed: '+', '.join(failure['engine'] for failure in failures))
            finally:
                process.terminate();process.wait(timeout=15)
                evidence=Path(temp)/'evidence'
                if evidence.exists(): shutil.copytree(evidence,OUT/'actual-packets',dirs_exist_ok=True)
                (OUT/'results.json').write_text(json.dumps(EVIDENCE,indent=2))


if __name__=='__main__':main()
