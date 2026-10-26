"""Offline safety/order checks; these do not certify browser geometry."""
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_monthly_site_geometry import DeliveryGate, FIRST, SECOND, PORT, local_url


class Socket:
    def __init__(self, url):
        self.url = url
        self.messages = []
        self.closed = None
        self.connected = False
        self.server = None

    def connect_to_server(self):
        self.connected = True
        self.server = Socket(self.url)
        return self.server

    def on_message(self, callback):
        self.callback = callback

    def send(self, message):
        self.messages.append(message)

    def close(self, **kwargs):
        self.closed = kwargs


def test_only_exact_loopback_origin_is_allowed():
    assert local_url(f'http://127.0.0.1:{PORT}/media/synthetic')
    assert local_url(f'ws://127.0.0.1:{PORT}/_stcore/stream', websocket=True)
    for url in ('https://example.com/', f'http://127.0.0.1:{PORT + 1}/',
                f'http://user@127.0.0.1:{PORT}/', f'http://127.0.0.1.evil:{PORT}/',
                f'ws://127.0.0.1:{PORT}/', 'data:text/plain,test', 'file:///tmp/x'):
        assert not local_url(url)


def test_external_websocket_rejected_before_connect():
    rejected = []
    gate = DeliveryGate(rejected)
    socket = Socket('wss://example.com/socket')
    gate.route(socket)
    assert rejected and socket.closed['code'] == 1008
    assert not socket.connected


def test_delivery_gate_preserves_bytes_order_and_outgoing_native_values():
    gate = DeliveryGate([])
    socket = Socket(f'ws://127.0.0.1:{PORT}/_stcore/stream')
    gate.route(socket)
    for label, key in ((FIRST, 'one'), (SECOND, 'two')):
        message = ForwardMsg()
        message.delta.new_element.checkbox.id = key
        message.delta.new_element.checkbox.label = label
        socket.server.callback(message.SerializeToString())
    assert gate.known == {'one': FIRST, 'two': SECOND}
    gate.hold()
    finish = ForwardMsg(script_finished=0).SerializeToString()
    socket.server.callback(b'not-protobuf')
    socket.server.callback(finish)
    assert gate.finished and len(gate.frames) == 2
    assert len(socket.messages) == 2
    native = BackMsg()
    native.rerun_script.widget_states.widgets.add(id='two', bool_value=False)
    raw = native.SerializeToString()
    socket.callback(raw)
    assert socket.server.messages == [raw]
    assert gate.sent == [{SECOND: False}]
    assert gate.release() == 2
    assert socket.messages[-2:] == [b'not-protobuf', finish]
    assert not gate.frames and not gate.holding


def test_geometry_job_is_separate_mandatory_and_bounded():
    from pathlib import Path
    workflow = Path('.github/workflows/adaptive-workspaces.yml').read_text()
    job = workflow.split('\n  monthly-site-geometry:\n', 1)[1]
    assert 'timeout-minutes: 40\n' in job
    assert 'timeout-minutes: 20\n' in job
    assert 'timeout-minutes: 11\n' in job
    assert "ci_native_test_budget.py --minutes 10 <<'NATIVE_TEST'" in job
    assert 'python scripts/qa_monthly_site_geometry.py' in job
    assert 'continue-on-error' not in job
    assert 'if:' not in job.split('      - name: Retain site-caption', 1)[0]
    assert 'if: always()' in job
    assert 'timeout-minutes: 3\n' in job
    assert 'path: test-artifacts/monthly-site-geometry/' in job
    old_job = workflow.split('\n  synthetic-dom:', 1)[1].split('\n  training-date:', 1)[0]
    assert 'qa_monthly_site_geometry.py' not in old_job
    assert workflow.count("      - 'scripts/qa_monthly_site_geometry.py'") == 2


def held_receipt():
    return {
        'before': {'label': {'x': 33, 'y': 220, 'width': 324, 'height': 44}},
        'during_press': {'label': {'x': 33, 'y': 220, 'width': 324, 'height': 44}},
        'release_hit_owned': True, 'after_release_checked': False,
        'events': [{'type': kind, 'label': SECOND, 'trusted': True}
                   for kind in ('pointerdown', 'pointerup', 'click')],
        'wire_after_press': [{SECOND: False, FIRST: False}],
    }


def test_react_aria_press_delivery_does_not_require_dom_change():
    from scripts.qa_monthly_site_geometry import validate_held_press
    validate_held_press(held_receipt())


def test_press_contract_rejects_moved_target_wrong_wire_and_untrusted_click():
    import pytest
    from scripts.qa_monthly_site_geometry import validate_held_press
    for mutate in (
        lambda r: r['during_press']['label'].update(y=242),
        lambda r: r.update(release_hit_owned=False),
        lambda r: r.update(after_release_checked=True),
        lambda r: r['events'][-1].update(trusted=False),
        lambda r: r['events'].pop(),
        lambda r: r['wire_after_press'][0].update({SECOND: True}),
        lambda r: r['wire_after_press'].append({SECOND: False}),
    ):
        receipt = held_receipt()
        mutate(receipt)
        with pytest.raises(AssertionError):
            validate_held_press(receipt)


def text_receipt():
    from scripts.qa_monthly_site_geometry import LONG_SITE
    return {'text': 'Site: ' + LONG_SITE, 'range_text': 'Site: ' + LONG_SITE,
            'height': 896, 'scrollHeight': 928, 'overflow': 'visible',
            'text_rects': [{}, {}, {}], 'glyph_bounds': {'left': 32, 'right': 358},
            'clipping': [], 'invisible': [], 'nested_scroll': [],
            'main': {'left': 0, 'right': 390}, 'mainScroll': 0,
            'visible_line_indices': [0]}


def test_text_geometry_accepts_visible_margin_overflow_but_not_clipping():
    import pytest
    from scripts.qa_monthly_site_geometry import validate_text_metrics
    validate_text_metrics(text_receipt())  # Same 32px scalar difference as hosted evidence.
    for change in ({'clipping': [{'height': 72}]}, {'nested_scroll': [{'top': 0}]},
                   {'invisible': [{'opacity': 0}]}, {'text_rects': []},
                   {'glyph_bounds': {'left': 32, 'right': 450}}, {'range_text': 'truncated'}):
        value = text_receipt()
        value.update(change)
        with pytest.raises(AssertionError):
            validate_text_metrics(value)


def test_keyboard_reading_requires_every_line_not_only_final_bottom():
    import pytest
    from scripts.qa_monthly_site_geometry import validate_reading_coverage
    start = text_receipt()
    middle, end = text_receipt(), text_receipt()
    middle.update(visible_line_indices=[1], mainScroll=100)
    end.update(visible_line_indices=[2], mainScroll=200)
    assert validate_reading_coverage(start, [middle, end]) == [0, 1, 2]
    with pytest.raises(AssertionError):
        validate_reading_coverage(start, [end])  # A missed middle line is not readable proof.


def test_text_range_probe_detects_clipped_ancestor_without_margin_false_positive():
    import json
    import subprocess
    from scripts.qa_monthly_site_geometry import TEXT_METRICS
    script = r"""
const probe = PROBE;
global.NodeFilter={SHOW_TEXT:4};global.innerHeight=844;
const rect=(top,bottom)=>({top,bottom,left:32,right:358,width:326,height:bottom-top,
 toJSON(){return {top:this.top,bottom:this.bottom,left:this.left,right:this.right,width:this.width,height:this.height}}});
function run(clipped,hidden=false){
 const main={getBoundingClientRect:()=>({top:0,bottom:844,left:0,right:390,toJSON(){return {top:0,bottom:844,left:0,right:390}}}),scrollTop:200};
 const n={tagName:'DIV',className:'identity',parentElement:main,clientLeft:0,clientTop:0,
 clientWidth:326,clientHeight:100,scrollHeight:132,scrollWidth:326,scrollTop:0,scrollLeft:0,
 textContent:'Site: test',getBoundingClientRect:()=>rect(0,100),contains:()=>true,
 style:{overflowX:'visible',overflowY:clipped?'hidden':'visible',display:'block',visibility:'visible',opacity:'1'}};
 const p={...n,tagName:'P',parentElement:n,style:{...n.style,overflowY:'visible',marginBottom:'32px'}};
 const text={textContent:'Site: test',parentElement:p};n.querySelector=()=>p;
 global.getComputedStyle=a=>a.style;
 global.document={querySelector:()=>main,elementFromPoint:()=>p,
 createTreeWalker:()=>({done:false,currentNode:null,nextNode(){if(this.done)return false;this.done=true;this.currentNode=text;return true}}),
 createRange:()=>({selectNodeContents(){},getClientRects:()=>hidden?[]:[rect(80,120)]})};
 return probe(n);
}
console.log(JSON.stringify([run(false),run(true),run(false,true)]));
""".replace('PROBE', TEXT_METRICS)
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    visible, clipped, hidden = json.loads(result.stdout)
    assert visible['scrollHeight'] - visible['height'] == 32
    assert visible['range_text'] == 'Site: test' and not visible['clipping']
    assert clipped['clipping'] and clipped['clipping'][0]['overflowY'] == 'hidden'

    assert hidden['range_text'] == 'Site: test' and not hidden['text_rects']
    assert hidden['invisible'] == [{'reason': 'non-whitespace text has no nonempty range rectangles'}]
