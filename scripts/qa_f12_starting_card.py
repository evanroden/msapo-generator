"""Local invented-card geometry, plus ordinary sidebar clearing; no live data."""
import os,subprocess,sys,time,json
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-artifacts/f12-starting-card';OUT.mkdir(parents=True,exist_ok=True)
server=subprocess.Popen([sys.executable,'-m','streamlit','run','tests/fixtures/f12_starting_card.py','--server.port','8548','--server.headless','true','--browser.gatherUsageStats','false'],cwd=ROOT,stdout=(OUT/'server.log').open('w'),stderr=subprocess.STDOUT)
try:
 for _ in range(60):
  try:
   if urlopen('http://127.0.0.1:8548/_stcore/health',timeout=1).status==200:break
  except OSError:time.sleep(.2)
 with sync_playwright() as p:
  results=[]
  for name in ('chromium','webkit'):
   browser=getattr(p,name).launch()
   for width in (390,1280):
    page=browser.new_page(viewport={'width':width,'height':900});page.goto('http://127.0.0.1:8548')
    expect(page.get_by_text('Loaded file:',exact=False)).to_be_visible()
    expect(page.get_by_role('button',name='Continue to reviewed updates',exact=True)).to_be_visible()
    sidebar=page.get_by_test_id('stSidebar')
    if sidebar.get_attribute('aria-expanded')=='false':page.get_by_test_id('stExpandSidebarButton').click()
    panel=sidebar.get_by_test_id('stExpander').filter(has_text='Starting report options')
    expect(panel).to_be_visible();expect(sidebar.get_by_role('button',name='Clear pending starting report')).to_be_hidden()
    page.screenshot(path=str(OUT/f'{name}-{width}-collapsed.png'))
    panel.locator('summary').click();action=sidebar.get_by_role('button',name='Clear pending starting report',exact=True)
    expect(action).to_be_visible();page.screenshot(path=str(OUT/f'{name}-{width}-expanded.png'))
    action.click();expect(page.get_by_text('Pending review cleared. Saved report remains unchanged.')).to_be_visible()
    expect(page.get_by_text('Loaded file:',exact=False)).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    results.append({'engine':name,'width':width,'passed':True});page.close()
   browser.close()
  (OUT/'results.json').write_text(json.dumps(results,indent=2));print(results)
finally:server.terminate();server.wait(timeout=20)
