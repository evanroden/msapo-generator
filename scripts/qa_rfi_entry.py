"""Native RFI Add focus, same-event edits, reload and actual synthetic outputs.

Runs only the existing isolated Monthly fixture. A native Add action must focus
its requested-item field once; no follow-up focus, click replay or rescue edit
can satisfy that assertion. Playwright WebKit is not physical Safari.
"""
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

PAIR = '.st-key-epc_pair_monthly_rfi'
REQUEST = 'Confirm the AHU-TEST-27 control sequence.\nThe response is still pending.'
SECOND = 'Provide the current synthetic pump drawing.'
TEMPORARY = 'Synthetic request deliberately removed.'


OBSERVER = r'''(() => {
  const identities=new WeakMap(),events=[];let next=0;
  const identity=node=>{if(!identities.has(node))identities.set(node,++next);return identities.get(node);};
  const describe=node=>({node:identity(node),connected:node.isConnected,disabled:node.disabled,
    focused:document.activeElement===node,tag:node.tagName,
    caret:[node.selectionStart??null,node.selectionEnd??null],
    rect:node.getBoundingClientRect().toJSON()});
  for(const type of ['pointerdown','pointerup','click','keydown','focusin','focusout'])
    document.addEventListener(type,event=>{
      const node=event.target?.closest?.('input,textarea,button');
      if(!node?.closest('.st-key-epc_pair_monthly_rfi'))return;
      events.push({type,time:performance.now(),trusted:event.isTrusted,key:event.key||'',
        label:node.getAttribute('aria-label')||node.textContent.trim(),...describe(node)});
      if(events.length>256)events.shift();
    },true);
  window.ENFRARfiObservation={events,describe};
})();'''


def request_rows(state):
    block = state['working']['rows']['rfi_matrix']
    return [row for table in block['tables'] for row in table['rows']]


def assert_outputs(word, pdf):
    from docx import Document
    from lxml import etree
    import pymupdf
    with ZipFile(BytesIO(word)) as package:
        root = etree.fromstring(package.read('word/document.xml'))
        ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        tables = [[[cell.text for cell in row.cells] for row in table.rows]
                  for table in Document(BytesIO(word)).tables]
        table, = [table for table in tables if table and table[0] == ['Facility','Requested item','Status']]
        assert table[1:] == [['Demo North',REQUEST,''], ['Demo South',SECOND,'Awaiting response']]
        all_text = '\n'.join(root.xpath('.//w:t/text()', namespaces=ns))
        assert TEMPORARY not in all_text and 'What information is needed?' not in all_text
        assert 'No requests added.' not in all_text
    with pymupdf.open(stream=pdf, filetype='pdf') as document:
        text = ' '.join(' '.join(page.get_text().split()) for page in document)
        for value in (REQUEST, SECOND):
            assert text.count(' '.join(value.split())) == 1
        assert TEMPORARY not in text and 'What information is needed?' not in text
        pages = len(document)
    return {'docx':{'bytes':len(word),'sha256':sha256(word).hexdigest()},
            'pdf':{'bytes':len(pdf),'sha256':sha256(pdf).hexdigest(),'pages':pages},
            'scope':'Actual editable DOCX cells and converted PDF text; not all-page visual or native Microsoft Word acceptance.'}


def browser_task(browser_type, name):
    from playwright.sync_api import expect
    from scripts import qa_monthly_adaptive as qa, qa_monthly_live as live
    from scripts.qa_report_row_cards import receipt
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={'width':1365,'height':900})
    context.add_init_script(qa.CLIENT_INIT)
    context.add_init_script(OBSERVER)
    context.add_cookies([{'name':'epc_device_id','value':secrets.token_hex(16),'url':qa.URL}])
    errors, external = [], []
    def route(request):
        url = urlparse(request.request.url)
        if url.scheme in {'data','blob'} or (url.hostname=='127.0.0.1' and url.port==8520):
            request.continue_()
        else:
            external.append(url.hostname)
            request.abort()
    context.route('**/*', route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    out = qa.OUT/name
    out.mkdir(parents=True, exist_ok=True)
    record = {'synthetic_only':True,'steps':[],'errors':errors,'external':external}
    def capture(stage, *, rows=None):
        state = receipt(page)
        assert state['working']['unrelated'] == baseline['working']['unrelated']
        assert state['directory'] == baseline['directory']
        assert (state['scope'],state['generation'],state['saved_revision']) == (
            baseline['scope'],baseline['generation'],baseline['saved_revision'])
        if rows is not None:
            assert request_rows(state) == rows
        assert not errors and not external
        record['steps'].append({'stage':stage,'receipt':state})
        return state
    def add_once(*, keyboard=False):
        pair = page.locator(PAIR)
        start = page.evaluate('window.ENFRARfiObservation.events.length')
        add = pair.get_by_role('button', name='Add request', exact=True)
        if keyboard:
            add.press('Enter')
        else:
            add.click()
        requested = pair.get_by_role('textbox', name='Requested item', exact=True)
        expect(requested).to_be_focused(timeout=5000)
        expect(requested).to_have_value('')
        expect(pair.get_by_text('No requests added.', exact=True)).to_have_count(0)
        expect(requested).to_have_attribute('placeholder','What information is needed?')
        actions = page.evaluate('start=>window.ENFRARfiObservation.events.slice(start)', start)
        activated = [event for event in actions if event['label']=='Add request' and event['type']=='click']
        assert len(activated)==1 and activated[0]['trusted']
        if not keyboard:
            pointer = [event for event in actions if event['label']=='Add request' and event['type'] in {'pointerdown','pointerup','click'}]
            assert [event['type'] for event in pointer] == ['pointerdown','pointerup','click']
            assert len({event['node'] for event in pointer})==1
        record['steps'].append({'stage':'keyboard-add-focus' if keyboard else 'pointer-add-focus',
                                'events':actions,'field':requested.evaluate('node=>window.ENFRARfiObservation.describe(node)')})
        return pair, requested
    try:
        page.goto(qa.URL, wait_until='domcontentloaded')
        live.load_fixture(page,'prefill')
        baseline = receipt(page)
        assert request_rows(baseline)==[]
        expect(page.locator(PAIR).get_by_text('No requests added.', exact=True)).to_be_visible()

        pair, requested = add_once()
        capture('fresh-add-is-not-report-content', rows=[])
        pair.get_by_role('textbox', name='Facility', exact=True).fill('Demo North')
        requested.fill(REQUEST)
        typed = requested.evaluate('node=>window.ENFRARfiObservation.describe(node)')
        page.set_viewport_size({'width':545,'height':757})
        expect(requested).to_be_focused()
        resized = requested.evaluate('node=>window.ENFRARfiObservation.describe(node)')
        assert typed['node']==resized['node'] and typed['caret']==resized['caret']
        record['native_continuity']={'typed':typed,'resized':resized}
        pair.get_by_role('button', name='Close editing', exact=True).click()
        first = [['Demo North',REQUEST,'']]
        capture('unblurred-request-delivered-with-close', rows=first)

        pair, requested = add_once(keyboard=True)
        requested.fill('   ')
        pair.get_by_role('button', name='Close editing', exact=True).click()
        capture('blank-entry-canceled', rows=first)
        expect(pair.get_by_role('button',name='Edit request',exact=True)).to_have_count(1)

        pair, requested = add_once(keyboard=True)
        pair.get_by_role('textbox',name='Facility',exact=True).fill('Demo South')
        pair.get_by_role('textbox',name='Status',exact=True).fill('Awaiting response')
        requested.press_sequentially(SECOND, delay=2)
        pair.get_by_role('button',name='Close editing',exact=True).click()
        final_rows = [*first,['Demo South',SECOND,'Awaiting response']]
        capture('keyboard-request-delivered-with-close',rows=final_rows)

        pair, requested = add_once()
        requested.fill(TEMPORARY)
        pair.get_by_role('button',name='Close editing',exact=True).click()
        capture('temporary-request-saved',rows=[*final_rows,['',TEMPORARY,'']])
        pair.get_by_role('button',name='Remove request',exact=True).nth(2).click()
        before_reload = capture('remove-request-keeps-independent-rows',rows=final_rows)
        page.reload(wait_until='domcontentloaded')
        assert capture('reload-exact-requests',rows=final_rows)==before_reload
        pair = page.locator(PAIR)
        pair.get_by_role('button',name='Edit request',exact=True).nth(0).click()
        requested = pair.get_by_role('textbox',name='Requested item',exact=True)
        expect(requested).to_have_value(REQUEST)
        expect(pair.get_by_role('textbox',name='Status',exact=True)).to_have_value('')
        requested.press('End')
        native = requested.evaluate('node=>window.ENFRARfiObservation.describe(node)')
        page.set_viewport_size({'width':1365,'height':900})
        expect(requested).to_be_focused()
        same = requested.evaluate('node=>window.ENFRARfiObservation.describe(node)')
        assert same['node']==native['node'] and same['caret']==native['caret']
        pair.get_by_role('button',name='Close editing',exact=True).click()
        capture('reentry-preserves-newlines-and-unknown-status',rows=final_rows)
        qa.capture(page,name,'rfi-requests-before-generation')
        live.ROOT=out
        live.EVIDENCE={'checks':{},'events':[],'artifacts':{},'synthetic_only':True}
        live.request_qa_generation(page,'rfi-entry-journey')
        word=live.download(page,'Download isolated QA DOCX','rfi-requests.docx')
        pdf=live.download(page,'Download isolated QA PDF','rfi-requests.pdf')
        record['outputs']=assert_outputs(word,pdf)
        record['generation']=live.EVIDENCE
        assert not errors and not external
        record['result']='passed'
        qa.check(name,'RFI first-action focus, native rows, durable reload and actual output',True)
    except Exception as exc:
        record['result']='failed'
        record['failure']={'type':type(exc).__name__,'message':str(exc)[:2000]}
        try:
            page.screenshot(path=str(out/'first-failure.png'))
        except Exception as capture_error:
            record['capture_error']=str(capture_error)[:500]
        raise
    finally:
        try:
            record['native_events']=page.evaluate('window.ENFRARfiObservation.events')
        except Exception as observation_error:
            record['observation_error']=str(observation_error)[:500]
        (out/'task.json').write_text(json.dumps(record,indent=2))
        context.close()
        browser.close()


def main():
    from scripts import qa_monthly_adaptive as qa
    from playwright.sync_api import Browser, BrowserContext
    from scripts.qa_browser_diagnostics import observe
    qa.OUT=ROOT/'test-artifacts'/'rfi-entry'
    qa.REPORT={'synthetic_only':True,'browsers':{},'checks':[],'physical_device':False}
    qa.exercise=browser_task
    with observe(qa.OUT/'diagnostics',Browser,BrowserContext):
        qa.main()


if __name__=='__main__':
    main()
