"""Actual local Streamlit DOM geometry evidence using synthetic inputs only.

Starts a disposable fixture process; never connects to Render or a real report.
Injected segment getters exercise the production resolver, not hardware support.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts' / 'adaptive-workspaces'
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'synthetic_only':True,'segment_evidence':'injected geometry; not physical hardware', 'browsers':{},'checks':[]}
URL = 'http://127.0.0.1:8517'


def check(name, condition, detail=None):
    REPORT['checks'].append({'name':name,'passed':bool(condition),'detail':detail})
    if not condition:
        raise AssertionError(name + ': ' + str(detail))


def geometry(page):
    return page.locator('.epc-workspace').evaluate('''root => {
      const describe = node => {
        if (!node) return null;
        const style=getComputedStyle(node);
        return {tag:node.tagName,classes:node.className,testid:node.dataset.testid,
          bounds:node.getBoundingClientRect().toJSON(),
          display:style.display,position:style.position,height:style.height,
          minHeight:style.minHeight,maxHeight:style.maxHeight,flex:style.flex,
          alignSelf:style.alignSelf,alignItems:style.alignItems,
          overflow:style.overflow,transform:style.transform,
          previewHeight:style.getPropertyValue('--epc-preview-height')};
      };
      return ({
      mode:root.dataset.epcMode,reason:root.dataset.epcReason,
      root:root.getBoundingClientRect().toJSON(),scrollTop:root.scrollTop,
      pairs:Array.from(root.querySelectorAll('.epc-workspace-pair')).map(pair=>({
        id:pair.querySelector('[data-epc-pair]').dataset.epcPair,active:pair.dataset.epcActive,
        pair:pair.getBoundingClientRect().toJSON(),
        preview:pair.querySelector('.epc-workspace-reference').getBoundingClientRect().toJSON(),
        stickyTop:parseFloat(getComputedStyle(pair.querySelector('.epc-workspace-reference')).top),
        visibility:getComputedStyle(pair.querySelector('.epc-workspace-reference')).visibility,
        surface:describe(pair.querySelector('.report-preview') ||
          Array.from(pair.querySelectorAll('*')).map(n=>n.shadowRoot?.querySelector('.report-preview')).find(Boolean)),
        reference:describe(pair.querySelector('.epc-workspace-reference')),
        ancestors:(()=>{let n=pair.querySelector('.epc-workspace-reference'),a=[];
          for(let i=0;n && i<7;i++,n=n.parentElement)a.push(describe(n));return a;})()
      }))});}''')


def settled(page, mode):
    page.wait_for_function("mode => document.querySelector('.epc-workspace')?.dataset.epcMode === mode",arg=mode)
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')


def inject(page, segments):
    page.evaluate('''segments => {
      Object.defineProperty(window,'viewport',{configurable:true,value:{segments}});
      window.dispatchEvent(new Event('resize'));
    }''',segments)


def capture(page, browser, label):
    observed=geometry(page)
    REPORT['browsers'].setdefault(browser,{})[label]=observed
    page.screenshot(path=str(OUT/f'{browser}-{label}.png'))
    return observed


def exercise(browser_type, name):
    browser=browser_type.launch(headless=True)
    page=browser.new_page(viewport={'width':1440,'height':900})
    errors=[]; page.on('pageerror',lambda exc:errors.append(str(exc)))
    page.goto(URL,wait_until='domcontentloaded')
    page.wait_for_selector('.epc-workspace-row')
    settled(page,'wide')
    first=page.locator('.st-key-epc_pair_monthly_activity')
    preview=first.locator('.epc-workspace-reference')
    # A wrapper alone is not a viewer. Wait for actual bounded raster content,
    # then let its ResizeObserver size settle before measuring sticky geometry.
    preview.locator('.report-preview img').first.wait_for(state='visible',timeout=30000)
    page.locator('[data-testid="stMain"]').evaluate('(node)=>{node.scrollTop=500}')
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    wide=capture(page,name,'wide-sticky')
    firstGeo=wide['pairs'][0]
    check(name+' actual preview surface mounted',firstGeo['surface'] is not None and firstGeo['surface']['bounds']['height']>180,firstGeo)
    check(name+' long preview pins at measured top',abs(firstGeo['preview']['top']-firstGeo['stickyTop']) <= 3, firstGeo)
    check(name+' viewer fits actual viewport',preview.locator('.report-preview').bounding_box()['y']+preview.locator('.report-preview').bounding_box()['height'] <= 900+3)
    page.locator('[data-testid="stMain"]').evaluate('''(node)=>{
      const pair=document.querySelector('.st-key-epc_pair_monthly_activity');
      node.scrollTop+=pair.getBoundingClientRect().bottom-200;
    }''')
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    boundary=capture(page,name,'forward-boundary')
    check(name+' preview releases at its section boundary',boundary['pairs'][0]['preview']['bottom'] <= boundary['pairs'][0]['pair']['bottom']+3,boundary['pairs'][0])
    page.locator('[data-testid="stMain"]').evaluate('(node)=>{node.scrollTop=500}')
    page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    reverse=capture(page,name,'reverse-boundary')
    check(name+' reverse scroll restores same preview',abs(reverse['pairs'][0]['preview']['top']-reverse['pairs'][0]['stickyTop'])<=3)
    preview.get_by_role('button',name='Next preview page').click()
    preview.get_by_label('Preview zoom').select_option('page')
    page.wait_for_function("() => Array.from(document.querySelector('.st-key-epc_pair_monthly_activity').querySelectorAll('*')).some(n=>n.shadowRoot?.querySelector('.report-preview-position')?.textContent==='2 / 2')")
    field=page.get_by_label('Work summary activity',exact=True)
    field.click(); field.fill('Typed without blur; preserved through geometry transitions')
    field.evaluate('(node)=>node.setSelectionRange(6,11)')
    before=field.evaluate('(node)=>({value:node.value,start:node.selectionStart,end:node.selectionEnd})')
    inject(page,[{'x':0,'y':0,'width':650,'height':900},{'x':690,'y':0,'width':750,'height':900}])
    settled(page,'book'); book=capture(page,name,'asymmetric-book')
    check(name+' asymmetric crease clearance',book['pairs'][0]['preview']['left']>=696-3,book['pairs'][0])
    inject(page,[{'x':0,'y':0,'width':1440,'height':380},{'x':0,'y':410,'width':1440,'height':490}])
    settled(page,'tabletop'); table=capture(page,name,'tabletop')
    active=[p for p in table['pairs'] if p['active']=='true']
    check(name+' one upper preview',len(active)==1 and active[0]['preview']['bottom']<=380 and active[0]['preview']['top']>=0,active)
    check(name+' lower working scroll root',table['root']['top']>=416-3 and table['root']['bottom']<=900+3,table['root'])
    after=field.evaluate('(node)=>({value:node.value,start:node.selectionStart,end:node.selectionEnd})')
    check(name+' unblurred input and selection survive',before==after,after)
    check(name+' input node retained and focus preserved',field.evaluate('(node)=>node===document.activeElement'))
    check(name+' page and zoom retained through book and tabletop',preview.locator('.report-preview-position').inner_text()=='2 / 2' and preview.get_by_label('Preview zoom').input_value()=='page')
    page.locator('.epc-workspace').evaluate('''root=>{
       const next=root.querySelector('.st-key-epc_pair_monthly_scorecards');
       root.scrollTop+=next.getBoundingClientRect().top-root.getBoundingClientRect().top+80;
    }''')
    page.wait_for_function("document.querySelector('.st-key-epc_pair_monthly_scorecards').dataset.epcActive==='true'")
    capture(page,name,'tabletop-next-section')
    inject(page,None); settled(page,'wide')
    page.set_viewport_size({'width':390,'height':844});settled(page,'compact')
    check(name+' one editor remains after transitions',page.get_by_label('Work summary activity',exact=True).count()==1)
    check(name+' compact has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+2'))
    first.get_by_role('button',name='View preview',exact=True).click()
    check(name+' compact preview opens',first.locator('.epc-workspace-reference').is_visible())
    first.get_by_role('button',name='Back to editing',exact=True).click()
    check(name+' compact returns to editor',first.locator('.epc-workspace-reference').is_hidden())
    capture(page,name,'compact')
    check(name+' no uncaught browser errors',not errors,errors)
    browser.close()


def main():
    with tempfile.TemporaryDirectory(prefix='adaptive-synthetic-') as temp:
        env=dict(os.environ,EPC_DATA_DIR=temp,ANTHROPIC_API_KEY='test-key-not-used')
        log=(OUT/'streamlit.log').open('w')
        process=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/app.py','--server.address','127.0.0.1','--server.port','8517','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Synthetic Streamlit fixture stopped')
                try:
                    with urllib.request.urlopen(URL+'/_stcore/health',timeout=1) as response:
                        if response.status==200: break
                except OSError: pass
                time.sleep(.1)
            with sync_playwright() as p:
                exercise(p.chromium,'chromium')
                exercise(p.webkit,'playwright-webkit')
        finally:
            process.terminate(); process.wait(timeout=15); log.close()
            (OUT/'geometry-and-results.json').write_text(json.dumps(REPORT,indent=2))


if __name__=='__main__': main()
