"""One native proposal/onsite/request editing journey per engine; synthetic data only."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlparse
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STATUS = 'On hold — awaiting owner decision'
NOTE = 'Synthetic decision: inspect the existing valve; no price included.'
TASK = 'Synthetic onsite task: inspect AHU-TEST-04 and retain follow-up.'
ASSET = 'AHU-TEST-0042'
REQUEST = 'Synthetic request: confirm the control sequence drawing for the north air handler.'
REQUEST_SITE = 'Synthetic North'
PROPOSALS = '.st-key-epc_pair_monthly_proposals'
ONSITE = '.st-key-epc_pair_monthly_maintenance'
REQUESTS = '.st-key-epc_pair_monthly_rfi'


ROW_OBSERVER = r'''(() => {
  const identities=new WeakMap(), events=[];
  let next=0;
  const identity=node=>{
    if(!identities.has(node))identities.set(node,++next);
    return identities.get(node);
  };
  const describe=node=>{
    const rect=node.getBoundingClientRect();
    return {node:identity(node),connected:node.isConnected,disabled:node.disabled,
      visible:Boolean(node.getClientRects().length),focused:document.activeElement===node,
      caret:[node.selectionStart??null,node.selectionEnd??null],
      rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height}};
  };
  for(const type of ['pointerdown','pointerup','click'])document.addEventListener(type,event=>{
    const button=event.target?.closest?.('button');
    const pair=button?.closest('.st-key-epc_pair_monthly_proposals,.st-key-epc_pair_monthly_maintenance,.st-key-epc_pair_monthly_rfi');
    if(!pair)return;
    events.push({type,time:performance.now(),label:button.textContent.trim(),
      point:{x:event.clientX,y:event.clientY},...describe(button),
      running:document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state'),
      scroll:document.querySelector('[data-testid="stMain"]')?.scrollTop});
    if(events.length>128)events.shift();
  },true);
  window.ENFRARowObservation={describe,events};
})();'''


def receipt(page, *, field=None, value=None):
    page.wait_for_function('''wanted => {
      const node=[...document.querySelectorAll('[data-enfra-row-receipt]')].at(-1);
      if(!node)return false;
      const s=JSON.parse(node.dataset.enfraRowReceipt);
      return JSON.stringify(s.working)===JSON.stringify(s.durable) &&
        (!wanted.field || Object.values(s.working.rows).some(block=>block.tables.some(table=>{
          const index=table.columns.indexOf(wanted.field);
          return index>=0&&table.rows.some(row=>row[index]===wanted.value);
        }))) && document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }''', arg={'field': field, 'value': value}, timeout=30000)
    return json.loads(page.locator('[data-enfra-row-receipt]').last.get_attribute('data-enfra-row-receipt'))


def assert_outputs(word, pdf):
    from lxml import etree
    import pymupdf
    with ZipFile(BytesIO(word)) as package:
        root = etree.fromstring(package.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        tables = [[[''.join(cell.xpath('.//w:t/text()', namespaces=ns)) for cell in row.findall('w:tc', ns)]
                   for row in table.findall('w:tr', ns)] for table in root.findall('.//w:tbl', ns)]
        proposal = next(table for table in tables if any('Q-TEST-731' in row for row in table))
        onsite = next(table for table in tables if any('WO-TEST-1005' in row for row in table))
        request = next((table for table in tables if any(REQUEST in row for row in table)), None)
        assert request is not None, 'Word lacks the entered request'
        assert [row for row in request if REQUEST in row] == [[REQUEST_SITE, REQUEST, '']]
        assert not any(row and not any(cell.strip() for cell in row) for row in request[1:])
        assert any('Q-TEST-731' in row and STATUS in row and NOTE in row for row in proposal)
        assert any('WO-TEST-1005' in row and TASK in row and ASSET in row for row in onsite)
        assert 'Status' in proposal[0] and 'Asset' in onsite[0]
        full='\n'.join(root.xpath('.//w:t/text()', namespaces=ns))
        assert full.count(NOTE)==1 and full.count(TASK)==1 and full.count(REQUEST)==1
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        text=' '.join(' '.join(page.get_text().split()) for page in doc)
        assert all(' '.join(value.split()) in text for value in (STATUS, NOTE, TASK, ASSET, REQUEST))
        pages=len(doc)
    return {'docx': {'bytes':len(word),'sha256':sha256(word).hexdigest()},
            'pdf': {'bytes':len(pdf),'sha256':sha256(pdf).hexdigest(),'pages':pages},
            'scope':'Native DOCX rows and actual PDF text; not all-page visual or Microsoft Word acceptance.'}


def browser_task(browser_type, name):
    from playwright.sync_api import expect
    from scripts import qa_monthly_adaptive as qa, qa_monthly_live as live
    browser=browser_type.launch(headless=True)
    context=browser.new_context(viewport={'width':1365,'height':900})
    context.add_init_script(qa.CLIENT_INIT)
    context.add_init_script(ROW_OBSERVER)
    context.add_cookies([{'name':'epc_device_id','value':secrets.token_hex(16),'url':qa.URL}])
    errors=[]; external=[]
    def route(request):
        url=urlparse(request.request.url)
        if url.scheme in {'data','blob'} or (url.hostname=='127.0.0.1' and url.port==8520):
            request.continue_()
        else:
            external.append(url.hostname);request.abort()
    context.route('**/*', route)
    page=context.new_page();page.set_default_timeout(20000)
    page.on('pageerror',lambda error:errors.append(str(error)))
    out=qa.OUT/name;out.mkdir(parents=True,exist_ok=True)
    record={'synthetic_only':True,'steps':[],'errors':errors,'external':external}
    def capture(stage, *, field=None, value=None):
        state=receipt(page,field=field,value=value)
        record['steps'].append({'stage':stage,'receipt':state})
        assert state['working']['unrelated']==baseline['working']['unrelated']
        assert (state['scope'],state['generation'],state['saved_revision'])==(baseline['scope'],baseline['generation'],baseline['saved_revision'])
        assert not errors and not external
        assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+2')
        return state
    try:
        page.goto(qa.URL,wait_until='domcontentloaded')
        live.load_fixture(page,'prefill')
        baseline=receipt(page)
        proposal=page.locator(PROPOSALS)
        expect(proposal.get_by_text('Status: Pending',exact=True)).to_be_visible()
        proposal.get_by_role('button',name='Edit proposal',exact=True).click()
        field=proposal.get_by_role('textbox',name='Status',exact=True)
        field.fill(STATUS)
        typed=field.evaluate('node=>window.ENFRARowObservation.describe(node)')
        # One ordinary blur followed by one structural Close; no rescue click.
        field.press('Tab')
        capture('status-durable',field='Status',value=STATUS)
        acknowledged=field.evaluate('node=>window.ENFRARowObservation.describe(node)')
        record['active_field_continuity']={'typed':typed,'acknowledged':acknowledged}
        assert typed['node']==acknowledged['node'] and acknowledged['visible'] and not acknowledged['disabled']
        proposal.get_by_role('textbox',name='Technical Notes',exact=True).fill(NOTE)
        proposal.get_by_role('button',name='Close editing',exact=True).click()
        capture('pending-note-delivered-with-close',field='Technical Notes',value=NOTE)
        proposal.get_by_role('button',name='Edit proposal',exact=True).click()
        expect(proposal.get_by_role('textbox',name='Status',exact=True)).to_have_value(STATUS)
        expect(proposal.get_by_role('textbox',name='Technical Notes',exact=True)).to_have_value(NOTE)
        proposal.get_by_role('button',name='Close editing',exact=True).click()
        capture('desktop-proposal-reentry')
        # Add request opens named fields, not an empty grid. Both typed fields
        # arrive with the one Close action, without a separate blur.
        requests=page.locator(REQUESTS)
        expect(requests.get_by_text('No requests added.',exact=True)).to_be_visible()
        requests.get_by_role('button',name='Add request',exact=True).click()
        expect(requests.locator('[data-testid="stDataFrame"]')).to_have_count(0)
        requests.get_by_role('textbox',name='Facility',exact=True).fill(REQUEST_SITE)
        requests.get_by_role('textbox',name='Requested item',exact=True).fill(REQUEST)
        requests.get_by_role('button',name='Close editing',exact=True).click()
        request_state=capture('request-delivered-with-close',field='Requested item',value=REQUEST)
        assert request_state['working']['rows']['rfi_matrix']['tables'][0]['rows']==[[REQUEST_SITE,REQUEST,'']]
        expect(requests.get_by_text(REQUEST,exact=True)).to_be_visible()
        expect(requests.get_by_text('No requests added.',exact=True)).to_have_count(0)
        # A request opened and cancelled while blank is never a row.
        requests.get_by_role('button',name='Add request',exact=True).click()
        expect(requests.get_by_role('textbox',name='Requested item',exact=True)).to_have_value('')
        requests.get_by_role('button',name='Close editing',exact=True).click()
        assert capture('blank-request-cancelled')['working']['rows']==request_state['working']['rows']
        page.set_viewport_size({'width':545,'height':757})
        onsite=page.locator(ONSITE)
        onsite.get_by_role('button',name='Edit onsite call',exact=True).click()
        onsite.get_by_role('textbox',name='Asset',exact=True).fill(ASSET)
        onsite.get_by_role('textbox',name='Asset',exact=True).press('Tab')
        capture('narrow-asset-durable',field='Asset',value=ASSET)
        onsite.get_by_role('textbox',name='Task',exact=True).fill(TASK)
        onsite.get_by_role('button',name='Close editing',exact=True).click()
        state=capture('narrow-task-delivered-with-close',field='Task',value=TASK)
        page.reload(wait_until='domcontentloaded')
        assert capture('reload-exact-rows')==state
        onsite=page.locator(ONSITE)
        requests=page.locator(REQUESTS)
        requests.get_by_role('button',name='Edit request',exact=True).click()
        expect(requests.get_by_role('textbox',name='Requested item',exact=True)).to_have_value(REQUEST)
        requests.get_by_role('button',name='Close editing',exact=True).click()
        capture('request-reload-reentry')
        onsite.get_by_role('button',name='Edit onsite call',exact=True).click()
        expect(onsite.get_by_role('textbox',name='Asset',exact=True)).to_have_value(ASSET)
        expect(onsite.get_by_role('textbox',name='Task',exact=True)).to_have_value(TASK)
        # Retain the original rapid native sequence. Waiting for the full
        # report to settle here would hide the observed moving-button defect.
        event_index=page.evaluate('window.ENFRARowObservation.events.length')
        onsite.get_by_role('button',name='Close editing',exact=True).click()
        proposal=page.locator(PROPOSALS)
        proposal.get_by_role('button',name='Edit proposal',exact=True).click()
        expect(proposal.get_by_role('textbox',name='Status',exact=True)).to_have_value(STATUS)
        transition=page.evaluate('index=>window.ENFRARowObservation.events.slice(index)',event_index)
        record['rapid_transition']=transition
        activated=[event for event in transition if event['label']=='Edit proposal']
        assert [event['type'] for event in activated]==['pointerdown','pointerup','click']
        assert len({event['node'] for event in activated})==1
        proposal.get_by_role('button',name='Close editing',exact=True).click()
        capture('narrow-proposal-and-onsite-reentry')
        qa.capture(page,name,'row-cards-narrow')
        live.ROOT=out;live.EVIDENCE={'checks':{},'events':[],'artifacts':{},'synthetic_only':True}
        live.request_qa_generation(page,'row-card-journey')
        word=live.download(page,'Download isolated QA DOCX','row-cards.docx')
        pdf=live.download(page,'Download isolated QA PDF','row-cards.pdf')
        record['outputs']=assert_outputs(word,pdf)
        record['generation']=live.EVIDENCE
        assert not errors and not external
        record['result']='passed';qa.check(name,'Native row status/identifiers/requests/edit-close/reload and actual output',True)
    except Exception as exc:
        record['result']='failed';record['failure']={'type':type(exc).__name__,'message':str(exc)[:2000]}
        try:page.screenshot(path=str(out/'first-failure.png'))
        except Exception as capture_error:record['capture_error']=str(capture_error)[:500]
        raise
    finally:
        try:record['native_events']=page.evaluate('window.ENFRARowObservation.events')
        except Exception as observation_error:record['observation_error']=str(observation_error)[:500]
        (out/'task.json').write_text(json.dumps(record,indent=2))
        context.close();browser.close()


def main():
    from scripts import qa_monthly_adaptive as qa
    from playwright.sync_api import Browser, BrowserContext
    from scripts.qa_browser_diagnostics import observe
    qa.OUT=qa.ROOT/'test-artifacts'/'report-row-cards'
    qa.REPORT={'synthetic_only':True,'browsers':{},'checks':[],'physical_device':False}
    qa.exercise=browser_task
    with observe(qa.OUT/'diagnostics',Browser,BrowserContext):qa.main()


if __name__=='__main__':main()
