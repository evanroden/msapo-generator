"""Local synthetic site-caption geometry and keyboard document-reading acceptance.

Deliberately delivers a preceding native checkbox rerun while the next native
press is held. It does not alter DOM values, dispatch events, retry actions, or
replace qa_monthly_site_pointer.py. Font scaling is CSS emulation, not device or
browser-zoom certification. Storage is temporary; no report is created.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-artifacts' / 'monthly-site-geometry'
PORT = 8537
BASE = f'http://127.0.0.1:{PORT}'
CONTRACT = 'Rochester Regional Health'
FIRST = 'United Memorial Medical Center'
SECOND = 'Rochester General Hospital'
IDENTITY = '.st-key-monthly_report_identity_sites'
LONG_SITE = ('Synthetic accessibility facility with a deliberately long identity ' * 8).strip()


def local_url(url, *, websocket=False):
    address = urlparse(url)
    schemes = {'ws'} if websocket else {'http'}
    return (address.scheme in schemes and address.hostname == '127.0.0.1'
            and address.port == PORT and not address.username and not address.password)


class DeliveryGate:
    """Observe native wire values, buffer only incoming frames, preserve order."""
    def __init__(self, rejected):
        self.rejected = rejected
        self.holding = False
        self.frames = []
        self.buffered_bytes = 0
        self.finished = False
        self.known = {}
        self.sent = []

    def route(self, socket):
        if not local_url(socket.url, websocket=True):
            self.rejected.append({'kind': 'websocket', 'url': socket.url})
            socket.close(code=1008, reason='Synthetic localhost only')
            return
        server = socket.connect_to_server()

        def received(raw):
            msg = ForwardMsg()
            try:
                msg.ParseFromString(raw)
                if msg.WhichOneof('type') == 'delta':
                    widget = msg.delta.new_element.checkbox
                    if widget.label in {FIRST, SECOND}:
                        self.known[widget.id] = widget.label
                if self.holding and msg.WhichOneof('type') == 'script_finished':
                    self.finished = True
            except (DecodeError, TypeError):
                pass
            if self.holding:
                self.buffered_bytes += len(raw)
                if len(self.frames) >= 4096 or self.buffered_bytes > 32 * 1024 * 1024:
                    raise AssertionError('Synthetic incoming frame budget exceeded')
                self.frames.append((socket, raw))
            else:
                socket.send(raw)

        def sent(raw):
            msg = BackMsg()
            try:
                msg.ParseFromString(raw)
                if msg.WhichOneof('type') == 'rerun_script':
                    widgets = msg.rerun_script.widget_states.widgets
                    self.sent.append({self.known[w.id]: w.bool_value for w in widgets
                                      if w.id in self.known and w.WhichOneof('value') == 'bool_value'})
            except (DecodeError, TypeError):
                pass
            server.send(raw)

        server.on_message(received)
        socket.on_message(sent)

    def hold(self):
        assert not self.frames
        self.finished = False
        self.buffered_bytes = 0
        self.holding = True

    def release(self):
        self.holding = False
        frames, self.frames = self.frames, []
        for socket, raw in frames:
            socket.send(raw)
        return len(frames)


OBSERVER = r"""(() => {
  window.__siteGeometryEvents=[];window.__siteGeometryArmed=false;
  window.__siteGeometryErrors=[];window.__siteGeometryErrorCount=0;
  for(const kind of ['error','unhandledrejection'])addEventListener(kind,e=>{
    window.__siteGeometryErrorCount++;
    if(window.__siteGeometryErrors.length<32)window.__siteGeometryErrors.push({kind,message:String(e.message||e.reason||'Resource error').slice(0,2000)});
  },{capture:true,passive:true});
  for(const type of ['pointerdown','pointerup','click','change']){
    document.addEventListener(type,event=>{
      if(!window.__siteGeometryArmed)return;
      const label=event.target.closest?.('label');
      const input=event.target.matches?.('input[type=checkbox]')?event.target:label?.querySelector('input[type=checkbox]');
      window.__siteGeometryEvents.push({type,trusted:event.isTrusted,
        target:event.target.tagName,label:input?.getAttribute('aria-label')||'',
        checked:input?.checked??null,x:event.clientX??null,y:event.clientY??null});
    },{capture:true,passive:true});
  }
})();"""


def snapshot(label):
    return label.evaluate("""n=>({label:n.getBoundingClientRect().toJSON(),
      identity:document.querySelector('.st-key-monthly_report_identity_sites').getBoundingClientRect().toJSON(),
      text:document.querySelector('.st-key-monthly_report_identity_sites').textContent,
      scroll:document.querySelector('[data-testid="stMain"]').scrollTop,
      checked:n.querySelector('input').checked})""")


def wait_for_buffer(page, gate):
    deadline = time.monotonic() + 45
    while not gate.finished and time.monotonic() < deadline:
        page.wait_for_timeout(25)  # Pump wire delivery, never retry a user action.
    assert gate.finished and gate.frames, 'Preceding rerun never reached the delivery gate'


def held_press(page, gate, record):
    from playwright.sync_api import expect
    first = page.get_by_role('checkbox', name=FIRST, exact=True)
    second = page.get_by_role('checkbox', name=SECOND, exact=True)
    identity = page.locator(IDENTITY)
    first.locator('xpath=ancestor::label[1]').click()
    expect(identity).to_have_text('Site: ' + FIRST, timeout=45000)
    second.locator('xpath=ancestor::label[1]').click()
    expect(identity).to_contain_text('Combined report', timeout=45000)
    expect(page.locator('[data-testid="stApp"]')).to_have_attribute('data-test-script-state', 'notRunning', timeout=45000)
    gate.hold()
    first.locator('xpath=ancestor::label[1]').click()
    expect(first).not_to_be_checked()
    wait_for_buffer(page, gate)
    label = second.locator('xpath=ancestor::label[1]')
    label.scroll_into_view_if_needed()
    record['before'] = snapshot(label)
    rect = record['before']['label']
    x, y = rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2
    page.evaluate('window.__siteGeometryArmed=true')
    page.mouse.move(x, y)
    page.mouse.down()
    sent_before = len(gate.sent)
    record['buffered_frames'] = gate.release()
    expect(identity).to_have_text('Site: ' + SECOND, timeout=45000)
    record['during_press'] = snapshot(label)
    record['release_hit_owned'] = label.evaluate('(n,p)=>n.contains(document.elementFromPoint(p.x,p.y))', {'x': x, 'y': y})
    page.mouse.up()
    record['events'] = page.evaluate('window.__siteGeometryEvents')
    expect(second).not_to_be_checked(timeout=45000)
    expect(identity).to_have_text('Select report sites.', timeout=45000)
    record['wire_after_press'] = gate.sent[sent_before:]
    for key in ('x', 'y', 'width', 'height'):
        assert abs(record['before']['label'][key] - record['during_press']['label'][key]) <= 1, record
    assert record['release_hit_owned'], record
    for kind in ('pointerdown', 'pointerup', 'change'):
        matching = [e for e in record['events'] if e['type'] == kind and e['label'] == SECOND]
        assert len(matching) == 1 and matching[0]['trusted'], record
    assert sum(row.get(SECOND) is False for row in record['wire_after_press']) == 1, record


def keyboard_long_identity(page, gate, record):
    from playwright.sync_api import expect
    page.get_by_text('More report details', exact=True).click()
    field = page.get_by_role('textbox', name='Site name', exact=True)
    field.fill(LONG_SITE)
    field.press('Tab')
    identity = page.locator(IDENTITY)
    expect(identity).to_have_text('Site: ' + LONG_SITE, timeout=45000)
    record['font_before'] = page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)')
    page.add_style_tag(content='html { font-size: 200% !important; }')
    record['font_after'] = page.evaluate('parseFloat(getComputedStyle(document.documentElement).fontSize)')
    assert abs(record['font_after'] / record['font_before'] - 2) < .01, record
    identity.scroll_into_view_if_needed()
    def metrics():
        return identity.evaluate("""n=>({height:n.clientHeight,scrollHeight:n.scrollHeight,
          overflow:getComputedStyle(n).overflowY,text:n.textContent,
          identity:n.getBoundingClientRect().toJSON(),
          main:document.querySelector('[data-testid="stMain"]').getBoundingClientRect().toJSON(),
          mainScroll:document.querySelector('[data-testid="stMain"]').scrollTop})""")
    record['before'] = metrics()
    assert record['before']['scrollHeight'] <= record['before']['height'] + 1, record
    assert record['before']['overflow'] not in ('hidden', 'clip'), record
    assert record['before']['text'] == 'Site: ' + LONG_SITE, record
    # Start at a genuine preceding native control, never focus the caption or
    # inject tabindex. PageDown must reveal all of the full-height identity in
    # ordinary document flow, rather than relying on a tiny nested scrollbox.
    page.get_by_role('combobox', name='Reporting year', exact=True).focus()
    focus_path = []
    for _ in range(40):
        page.keyboard.press('Tab')
        focused = page.evaluate("() => ({tag:document.activeElement.tagName,label:document.activeElement.getAttribute('aria-label')||''})")
        focus_path.append(focused)
        if focused['tag'] == 'INPUT' and focused['label'] == SECOND:
            break
    record['focus_path'] = focus_path
    assert focus_path[-1] == {'tag': 'INPUT', 'label': SECOND}, record
    record['keyboard_start'] = metrics()
    path = []
    for _ in range(40):
        page.keyboard.press('PageDown')
        page.wait_for_timeout(50)  # Let native smooth scroll settle; no action retry.
        current = metrics()
        path.append(current)
        if current['identity']['bottom'] <= current['main']['bottom']:
            break
    record['document_scroll_path'] = path
    assert path[-1]['identity']['bottom'] <= path[-1]['main']['bottom'], record
    assert path[-1]['mainScroll'] > record['keyboard_start']['mainScroll'], record
    assert all(item['scrollHeight'] <= item['height'] + 1 for item in path), record
    assert all(item['text'] == 'Site: ' + LONG_SITE for item in path), record


def visit(browser, engine, scenario, output):
    from playwright.sync_api import expect
    record = {'engine': engine, 'scenario': scenario.__name__, 'physical_device': False}
    context = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True, service_workers='block')
    rejected, errors = [], []
    def http_route(route):
        if local_url(route.request.url):
            route.continue_()
        else:
            rejected.append({'kind': 'http', 'url': route.request.url})
            route.abort()
    context.route('**/*', http_route)
    gate = DeliveryGate(rejected)
    context.route_web_socket('**/*', gate.route)
    context.add_init_script(OBSERVER)
    context.tracing.start(screenshots=True, snapshots=True, sources=False)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(BASE + '/?workflow=monthly', wait_until='domcontentloaded')
        page.get_by_role('button', name=CONTRACT, exact=True).click()
        expect(page.get_by_role('checkbox', name=FIRST, exact=True)).not_to_be_checked()
        scenario(page, gate, record)
        assert not rejected, rejected
        assert not errors, errors
        native = page.evaluate('({count:window.__siteGeometryErrorCount,errors:window.__siteGeometryErrors})')
        record['native_errors'] = native
        assert native == {'count': 0, 'errors': []}, native
        record['result'] = 'pass'
    except Exception as exc:
        record.update(result='fail', error_type=type(exc).__name__, error=str(exc))
        try:
            page.screenshot(path=str(output / 'first-failure.png'))
        except Exception as capture:
            record['screenshot_error'] = str(capture)
    finally:
        record.update(rejected_requests=rejected, browser_errors=errors)
        # Keep the armed event chain even if a held-press assertion failed
        # before its normal receipt. Never replace the first workflow error.
        try:
            record['final_events'] = page.evaluate('window.__siteGeometryEvents')
        except Exception as capture:
            record['event_capture_error'] = str(capture)
            record['result'] = 'fail'
        try:
            record['native_errors'] = page.evaluate('({count:window.__siteGeometryErrorCount,errors:window.__siteGeometryErrors})')
        except Exception as capture:
            record['native_error_capture_error'] = str(capture)
            record['result'] = 'fail'
        try:
            context.tracing.stop(path=str(output / 'trace.zip'))
        except Exception as trace:
            record['trace_error'] = str(trace)
            record['result'] = 'fail'
        try:
            context.close()
        except Exception as close:
            record['context_close_error'] = str(close)
            record['result'] = 'fail'
        (output / 'results.json').write_text(json.dumps(record, indent=2))
    return record


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    with tempfile.TemporaryDirectory(prefix='monthly-site-geometry-') as data, (OUT / 'streamlit.log').open('w') as log:
        env = {**os.environ, 'EPC_DATA_DIR': data, 'SMARTSHEET_API_MODE': 'disabled', 'ANTHROPIC_API_KEY': 'test-key-not-used'}
        process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'run_web.py', '--server.address', '127.0.0.1', '--server.port', str(PORT), '--server.headless', 'true', '--browser.gatherUsageStats', 'false'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError('Synthetic server stopped before readiness')
                try:
                    with urlopen(BASE + '/_stcore/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError('Synthetic server did not become ready')
            with sync_playwright() as playwright:
                for name, kind in (('chromium', playwright.chromium), ('playwright-webkit', playwright.webkit)):
                    browser = kind.launch(headless=True)
                    try:
                        for scenario in (held_press, keyboard_long_identity):
                            output = OUT / (name + '-' + scenario.__name__)
                            output.mkdir(exist_ok=True)
                            results.append(visit(browser, name, scenario, output))
                    finally:
                        browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
            (OUT / 'results.json').write_text(json.dumps(results, indent=2))
    assert len(results) == 4 and all(row['result'] == 'pass' for row in results), results
    print('PASS four synthetic caption geometry / keyboard document-reading cases; no physical-device claim')


if __name__ == '__main__':
    main()
