"""Local actual expense UI browser checks; synthetic bytes, no external actions."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
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
    check(f'loaded original page {index+1}',image.evaluate('(node)=>node.naturalWidth>0'))


def tabletop_reference(page, pair, title, name):
    expect(pair).to_have_attribute('data-epc-active','true')
    heading=pair.locator('.epc-context-title')
    expect(heading).to_have_text(title)
    expect(heading).to_be_visible()
    observed=pair.evaluate("""pair=>{
        const ref=pair.querySelector('.epc-workspace-reference');
        const title=ref.querySelector('.epc-context-title');
        const box=ref.getBoundingClientRect(), label=title.getBoundingClientRect();
        return {reference:box.toJSON(),title:label.toJSON(),
            hidden:[...pair.closest('.epc-workspace').querySelectorAll('.epc-workspace-pair:not([data-epc-active="true"]) .epc-workspace-reference')]
                .map(node=>({display:getComputedStyle(node).display,rects:node.getClientRects().length}))};
    }""")
    check(name+' upper title fits active reference',
          observed['title']['top']>=observed['reference']['top'] and
          observed['title']['bottom']<=observed['reference']['bottom'],observed)
    # A hidden wrapper alone was insufficient: Streamlit child visibility
    # overrides leaked an inactive Mileage caption across the receipt preview.
    check(name+' inactive reference descendants cannot overlap active source',
          all(x['display']=='none' and x['rects']==0 for x in observed['hidden']),observed)


def run(browser_type,name):
    browser=browser_type.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(getattr(e,'stack',None) or str(e)))
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
        mileage=browser.new_page(viewport={'width':1180,'height':820})
        mileage.goto(URL+'?mileage_only=1');mode(mileage,'wide')
        check(name+' mileage-only has no fabricated receipt',mileage.locator('[data-epc-pair^="expense_receipt_"]').count()==0)
        set_toggle(mileage,'Include reimbursable business mileage',True,name+' mileage')
        expect(mileage.get_by_label('Business miles *',exact=True)).to_be_visible()
        check(name+' mileage-only has actual trip review',mileage.get_by_text('Current trips and reimbursement',exact=True).count()==1)
        mileage.screenshot(path=str(OUT/f'{name}-mileage-only.png'))
        check(name+' no browser errors',not errors,errors)
    except Exception:
        page.screenshot(path=str(OUT/f'{name}-failure.png'))
        raise
    finally:
        browser.close()


def main():
    with tempfile.TemporaryDirectory(prefix='expense-adaptive-synthetic-') as temp:
        env=dict(os.environ,EPC_DATA_DIR=temp,ANTHROPIC_API_KEY='test-key-not-used')
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
                (OUT/'results.json').write_text(json.dumps(EVIDENCE,indent=2))


if __name__=='__main__':main()
