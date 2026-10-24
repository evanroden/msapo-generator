"""Hosted Chromium/WebKit compact-contact lifecycle, invented isolated data only.

No JS state mutation, force clicks, rescue clicks or live fixtures. First failed
activation stops its engine and retains native events/screenshot/trace evidence.
"""
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import sys
from urllib.parse import urlparse
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CONTACTS = '.st-key-epc_pair_monthly_organization'
VENDORS = '.st-key-epc_pair_monthly_subcontractors'
SELECTOR = '[data-enfra-contact-receipt]'
OBSERVER = r'''(() => {
 const ids=new WeakMap();let next=0;const events=[];
 const describe=n=>{if(!ids.has(n))ids.set(n,++next);const r=n.getBoundingClientRect();
 return {node:ids.get(n),connected:n.isConnected,focused:document.activeElement===n,
 visible:!!n.getClientRects().length,disabled:n.disabled,caret:[n.selectionStart??null,n.selectionEnd??null],
 rect:{x:r.x,y:r.y,width:r.width,height:r.height}};};
 for(const type of ['pointerdown','pointerup','click','dblclick'])document.addEventListener(type,e=>{
 const b=e.target?.closest?.('button');if(b)events.push({type,trusted:e.isTrusted,label:b.textContent.trim(),...describe(b)});
 if(events.length>256)events.shift();},true);
 window.ENFRAContactObservation={describe,events};
})();'''


def receipt(page, *, after=0, expected_contact=None, expected_write=None):
    page.wait_for_function('''({after,expected,write}) => {
      const n=[...document.querySelectorAll('[data-enfra-contact-receipt]')].at(-1);
      if(!n)return false;const s=JSON.parse(n.dataset.enfraContactReceipt);
      const root=document.querySelector('.st-key-epc_pair_monthly_organization');
      if(expected && (!s.working.contacts.rows.some(row => row.length===expected.length && expected.every((v,i) => row[i]===v)) ||
        root?.querySelectorAll('input[aria-label="Phone"]').length!==1))return false;
      if(write && (s.attempts.length!==write.attempts || s.directory.revision!==write.revision ||
        s.working.contacts.rows[0][3]!==write.phone || root?.querySelectorAll('input[aria-label="Phone"]').length!==0))return false;
      return s.sequence>after && JSON.stringify(s.working)===JSON.stringify(s.durable) &&
        document.querySelector('[data-testid="stApp"]')?.getAttribute('data-test-script-state')==='notRunning';
    }''', arg={'after':after,'expected':expected_contact,'write':expected_write}, timeout=30000)
    return json.loads(page.locator(SELECTOR).last.get_attribute('data-enfra-contact-receipt'))


def validate_outputs(word, pdf, rows):
    from docx import Document
    import pymupdf
    expected = (('Facility','Role','Name','Phone','Email'), *tuple(tuple(row) for row in rows))
    doc = Document(BytesIO(word))
    tables = [tuple(tuple(cell.text for cell in row.cells) for row in table.rows) for table in doc.tables]
    assert expected in tables, 'Native Word must retain the exact canonical contact table.'
    with pymupdf.open(stream=pdf, filetype='pdf') as document:
        text = ' '.join(' '.join(page.get_text().split()) for page in document)
        for row in rows:
            for value in row[2:]:
                if value:
                    assert ' '.join(value.split()) in text
        assert 'OLD SYNTHETIC CONTACT' not in text
        pages = len(document)
    with ZipFile(BytesIO(word)) as package:
        xml = package.read('word/document.xml')
    return {'word_sha256':sha256(word).hexdigest(), 'pdf_sha256':sha256(pdf).hexdigest(),
            'document_xml_sha256':sha256(xml).hexdigest(), 'pdf_pages':pages,
            'scope':'Actual native Word table and PDF text; not genuine-report, physical device or Microsoft Word acceptance.'}


def browser_task(browser_type, name):
    from playwright.sync_api import expect
    from scripts import qa_monthly_adaptive as qa
    browser = browser_type.launch(headless=True)
    context = browser.new_context(viewport={'width':1365,'height':900}, accept_downloads=True)
    context.add_init_script(qa.CLIENT_INIT)
    context.add_init_script(OBSERVER)
    context.add_cookies([{'name':'epc_device_id','value':secrets.token_hex(16),'url':qa.URL}])
    out = qa.OUT / name
    out.mkdir(parents=True, exist_ok=True)
    errors, external = [], []
    def route(request):
        url = urlparse(request.request.url)
        if url.scheme in {'data','blob'} or (url.hostname == '127.0.0.1' and url.port == 8520):
            request.continue_()
        else:
            external.append(url.hostname)
            request.abort()
    context.route('**/*', route)
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on('pageerror', lambda error: errors.append(str(error)))
    record = {'synthetic_only':True, 'steps':[], 'errors':errors, 'external':external}
    def capture(stage, previous=None, expected_contact=None, expected_write=None):
        state = receipt(page, after=previous['sequence'] if previous else 0, expected_contact=expected_contact, expected_write=expected_write)
        assert state['saved_unchanged'] and state['original_unchanged']
        assert state['working']['vendors'] == baseline['working']['vendors']
        assert state['working']['unrelated'] == baseline['working']['unrelated']
        assert (state['scope'],state['generation'],state['saved_revision']) == (baseline['scope'],baseline['generation'],baseline['saved_revision'])
        assert not errors and not external
        record['steps'].append({'stage':stage,'receipt':state})
        return state
    def outputs(stage, state):
        page.get_by_role('button',name='Render synthetic native contact outputs',exact=True).click()
        rendered = capture(stage + '-render', state)
        values = []
        for label,suffix in [('Download synthetic contact Word','docx'),('Download synthetic contact PDF','pdf')]:
            with page.expect_download(timeout=30000) as download:
                page.get_by_role('button',name=label,exact=True).click()
            path = out / (stage + '.' + suffix)
            download.value.save_as(path)
            values.append(path.read_bytes())
        return rendered, validate_outputs(*values, rendered['working']['contacts']['rows'])
    try:
        page.goto(qa.URL, wait_until='domcontentloaded')
        page.get_by_role('button',name='Create synthetic compact contact report',exact=True).click()
        baseline = receipt(page)
        record['baseline'] = baseline
        assert len(baseline['working']['vendors']['extra_tables'][0]['rows']) == 3
        state, before_output = outputs('before', baseline)
        vendors = page.locator(VENDORS)
        expect(vendors.get_by_role('textbox')).to_have_count(0)
        expect(vendors.get_by_role('button',name='Edit vendor contact',exact=True)).to_have_count(3)
        # Existing blank row and custom columns are editable without adding,
        # deleting or replacing any source occurrence, including duplicates.
        for index in (1,0,2,0):
            vendors.get_by_role('button',name='Edit vendor contact',exact=True).nth(index).click()
            expect(vendors.get_by_role('textbox')).to_have_count(3)
            if index == 1:
                expect(vendors.get_by_role('textbox',name='Name',exact=True)).to_have_value('')
            else:
                expect(vendors.get_by_role('textbox',name='Detail 2',exact=True)).to_have_value('Retain blank-heading value')
            vendors.get_by_role('button',name='Close editing',exact=True).click()
            state = capture('vendor-no-edit-close-' + str(index), state)
            expect(vendors.get_by_role('textbox')).to_have_count(0)
        state, after_no_edit = outputs('after-no-edit', state)
        assert after_no_edit['document_xml_sha256'] == before_output['document_xml_sha256']
        contacts = page.locator(CONTACTS)
        contacts.get_by_role('button',name='Edit contacts',exact=True).click()
        expect(contacts.get_by_role('textbox',name='Name',exact=True)).to_have_count(0)
        state = capture('contacts-open',state)
        contacts.get_by_role('button',name='Add contact',exact=True).click()
        expect(contacts.get_by_role('textbox',name='Phone',exact=True)).to_have_count(1)
        state = capture('add-open',state)
        native = contacts.get_by_role('textbox',name='Phone',exact=True).evaluate('n=>window.ENFRAContactObservation.describe(n)')
        expected_contact = ['', '', '', '', '']
        for index,(label,value) in enumerate([('Facility','Demo North'),('Role','Engineer'),('Name','Synthetic Added North'),('Phone','202-555-0174')]):
            field = contacts.get_by_role('textbox',name=label,exact=True)
            field.fill(value)
            field.press('Tab')
            expected_contact[index] = value
            state = capture('add-' + label.lower(), state, expected_contact)
            current = contacts.get_by_role('textbox',name='Phone',exact=True).evaluate('n=>window.ENFRAContactObservation.describe(n)')
            assert current['node'] == native['node'] and current['visible'] and not current['disabled']
        assert state['directory']['sites'][0]['contacts'][-1]['phone'] == '202-555-0174'
        page.get_by_role('button',name='Observe synthetic passive rerun',exact=True).click()
        passive = capture('populated-contact-passive-rerun',state)
        assert passive['working'] == state['working'] and passive['directory'] == state['directory']
        expect(contacts.get_by_role('textbox',name='Phone',exact=True)).to_have_value('202-555-0174')
        contacts.get_by_role('button',name='Done',exact=True).click()
        state = capture('hide-populated-contact',passive)
        contacts.get_by_role('button',name='Edit contacts',exact=True).click()
        state = capture('reopen-populated-contact',state)
        expect(contacts.get_by_role('textbox',name='Phone',exact=True)).to_have_value('202-555-0174')
        contacts.get_by_role('button',name='Close editing',exact=True).click()
        state = capture('add-close',state)
        for fault,phone in [('before','202-555-0175'),('after','202-555-0176')]:
            controls = page.get_by_test_id('stExpander').filter(has=page.locator('summary').get_by_text('Synthetic fault controls',exact=True))
            if not controls.evaluate("n => (n.matches('details') ? n : n.querySelector('details')).open"):
                controls.locator('summary').click()
            page.get_by_role('button',name=f'Fail next synthetic shared save {fault} commit',exact=True).click()
            contacts.get_by_role('button',name='Edit contact',exact=True).first.click()
            contacts.get_by_role('textbox',name='Phone',exact=True).fill(phone)
            prior = state
            contacts.get_by_role('button',name='Remove contact',exact=True).click()
            expected_write = {'attempts':len(prior['attempts']) + 1,
                              'revision':prior['directory']['revision'] + (fault == 'after'), 'phone':phone}
            state = capture('fault-' + fault,prior, expected_write=expected_write)
            assert len(state['working']['contacts']['rows']) == len(prior['working']['contacts']['rows'])
            assert len(state['attempts']) == len(prior['attempts']) + 1
            if fault == 'before':
                assert state['directory']['revision'] == prior['directory']['revision']
                assert any(ref.startswith('directory-pending-correction:') for ref in state['working']['contacts']['references'])
                # Native repeated pointer activation, not a script callback replay.
                contacts.get_by_role('button',name='Retry shared contact correction',exact=True).dblclick()
                expected_write.update(attempts=len(prior['attempts']) + 2, revision=prior['directory']['revision'] + 1)
                state = capture('explicit-retry-double-click',state, expected_write=expected_write)
                assert len(state['attempts']) == len(prior['attempts']) + 2
            assert state['directory']['revision'] == prior['directory']['revision'] + 1
            assert state['directory']['sites'][0]['contacts'][0]['phone'] == phone
            assert state['working']['contacts']['source'] == 'Library'
        # Deliver a native contact edit and parent Done in the same browser
        # action. The canonical report/directory must update before any re-entry.
        contacts.get_by_role('button', name='Edit contact', exact=True).first.click()
        contacts.get_by_role('textbox', name='Phone', exact=True).fill('202-555-0199')
        prior = state
        contacts.get_by_role('button', name='Done', exact=True).click()
        state = capture('native-unblurred-phone-parent-done', prior, expected_write={
            'attempts': len(prior['attempts']) + 1,
            'revision': prior['directory']['revision'] + 1,
            'phone': '202-555-0199',
        })
        assert contacts.get_by_role('textbox', name='Phone', exact=True).count() == 0
        assert state['directory']['sites'][0]['contacts'][0]['phone'] == '202-555-0199'
        native_events = page.evaluate('window.ENFRAContactObservation.events')
        for label in ('Add contact', 'Edit vendor contact', 'Edit contact',
                      'Retry shared contact correction'):
            for event_type in ('pointerdown', 'click'):
                assert any(event['label'] == label and event['type'] == event_type
                           and event['trusted'] is True for event in native_events), (label, event_type)
        record['pre_reload_native_events'] = native_events
        before_reload = state
        page.set_viewport_size({'width':545,'height':757})
        page.reload(wait_until='domcontentloaded')
        state = capture('narrow-reload')
        assert state['working'] == before_reload['working'] and state['directory'] == before_reload['directory']
        state, final_output = outputs('after-edits',state)
        record['outputs'] = {'before':before_output,'after_no_edit':after_no_edit,'final':final_output}
        assert page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+2')
        qa.capture(page,name,'compact-contacts-narrow')
        record['result'] = 'passed'
        qa.check(name,'Compact contact native lifecycle, standing normalization/recovery and real outputs',True)
    except Exception as exc:
        record['result'] = 'failed'
        record['failure'] = {'type':type(exc).__name__,'message':str(exc)[:2000]}
        try:
            page.screenshot(path=str(out/'first-failure.png'))
        except Exception as capture_error:
            record['capture_error'] = str(capture_error)[:500]
        raise
    finally:
        try:
            record['native_events'] = page.evaluate('window.ENFRAContactObservation.events')
        except Exception as observer_error:
            record['observer_error'] = str(observer_error)[:500]
        (out/'task.json').write_text(json.dumps(record,indent=2))
        context.close()
        browser.close()


def main():
    from playwright.sync_api import Browser, BrowserContext
    from scripts import qa_monthly_adaptive as qa
    from scripts.qa_browser_diagnostics import observe
    os.environ['EPC_MONTHLY_CONTACT_TASK'] = '1'
    qa.OUT = ROOT / 'test-artifacts/compact-contact-journey'
    qa.REPORT = {'synthetic_only':True,'browsers':{},'checks':[],'physical_device':False}
    qa.exercise = browser_task
    with observe(qa.OUT/'diagnostics',Browser,BrowserContext):
        qa.main()


if __name__ == '__main__':
    main()
