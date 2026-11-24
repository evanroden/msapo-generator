"""Invented-data system appearance regression, WebKit and Chromium, no hardware claim."""
import json,os,subprocess,sys,tempfile,time
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-artifacts'/'system-appearance'
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 results=[]
 with tempfile.TemporaryDirectory() as data,(OUT/'server.log').open('w') as log:
  server=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/workspaces/duo_app.py','--server.port','8524'],cwd=ROOT,env=dict(os.environ,EPC_DATA_DIR=data,ANTHROPIC_API_KEY='synthetic-unused'),stdout=log,stderr=log)
  try:
   for _ in range(120):
    try:urlopen('http://127.0.0.1:8524/_stcore/health',timeout=1);break
    except OSError:time.sleep(.2)
   with sync_playwright() as p:
    for name in os.environ.get('QA_ENGINES','chromium,webkit').split(','):
     browser=getattr(p,name).launch(**({'executable_path':os.environ.get('QA_CHROMIUM_EXECUTABLE',p.chromium.executable_path)} if name=='chromium' else {'executable_path':os.environ.get('QA_WEBKIT_EXECUTABLE',p.webkit.executable_path)}))
     for width in (390,669,1280):
      page=browser.new_page(viewport={'width':width,'height':900},color_scheme='light')
      # A previous native override must not pin users to light appearance.
      page.add_init_script("localStorage.setItem('stActiveTheme-/-v2',JSON.stringify('Light'))")
      page.goto('http://127.0.0.1:8524')
      notes=page.get_by_label('Synthetic notes',exact=True)
      expect(notes).to_be_visible(timeout=30000)
      receipt=page.get_by_text('Appearance fixture pass ',exact=False)
      before=receipt.inner_text()
      notes.fill('Invented text survives system changes')
      notes.press('Tab')
      expect(receipt).not_to_have_text(before)
      for scheme in ('light','dark','light','dark'):
       page.emulate_media(color_scheme=scheme)
       expected='rgb(237, 245, 240)' if scheme=='dark' else 'rgb(0, 0, 0)'
       expect(notes).to_have_css('color',expected)
       assert notes.input_value()=='Invented text survives system changes'
       idle=page.locator('.st-key-workflow_mode [role=radio][aria-checked=false]').first
       expect(idle).to_have_css('color',expected if scheme=='dark' else 'rgb(9, 43, 36)')
       assert page.get_by_test_id('stThemeSwitcher').count()==0
       record=page.evaluate('''() => ({scheme:matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light',body:getComputedStyle(document.querySelector('.stApp')).backgroundImage,overflow:document.documentElement.scrollWidth>innerWidth+1,override:localStorage.getItem('stActiveTheme-/-v2')})''')
       assert not record['overflow'],record
       assert record['override']=='"System"',record
       results.append(dict(engine=name,width=width,**record))
       page.get_by_test_id('stMain').evaluate('n=>n.scrollTop=0')
       page.screenshot(path=str(OUT/f'{name}-{width}-{scheme}.png'))
      if width==390:
       for workflow in ('Expense reimbursement','Monthly report','Purchase order'):
        before=receipt.inner_text()
        page.get_by_role('radio',name=workflow,exact=True).click()
        expect(receipt).not_to_have_text(before)
        expect(notes).to_have_count(1)
        expect(page.locator('.st-key-workflow_mode [role=radio][aria-checked=true]')).to_have_text(workflow)
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        page.get_by_role('combobox',name='Synthetic site',exact=True).focus()
        page.get_by_role('combobox',name='Synthetic site',exact=True).press('ArrowDown')
        expect(page.get_by_role('option',name='Invented B',exact=True)).to_be_visible()
        page.screenshot(path=str(OUT/f'{name}-{workflow.split()[0]}-popover.png'))
        page.get_by_role('option',name='Invented B',exact=True).click()
        page.get_by_role('button',name='View preview',exact=True).click()
        image=page.locator('.report-preview img').first
        expect(image).to_be_visible()
        expect(image).to_have_js_property('complete',True)
        expect(page.locator('.report-preview-page').first).to_have_css('background-color','rgb(255, 255, 255)')
        expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
        expect(page.locator('[data-stale="true"]')).to_have_count(0)
        page.screenshot(path=str(OUT/f'{name}-{workflow.split()[0]}-preview.png'))
        page.get_by_role('button',name='Back to editing',exact=True).click()
        assert notes.input_value()=='Invented text survives system changes'
      page.close()
     browser.close()
  finally:server.terminate();server.wait(timeout=20)
 (OUT/'results.json').write_text(json.dumps(results,indent=2));print('Passed',len(results))
if __name__=='__main__':main()
