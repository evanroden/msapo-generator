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
