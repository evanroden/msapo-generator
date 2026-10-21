"""Read-only hashed widget delivery receipts for marked localhost browser QA.

No raw values, filenames, query strings, cookies or protobuf bodies are retained.
This observes the wire; it never submits a widget, changes input or retries work.
"""
from collections import OrderedDict
from hashlib import sha256
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_wire_totals import WireTotals

DEFAULT_PORTS = (8520, 8521, 8528)


def _hash(value):
    return sha256(value.encode('utf-8')).hexdigest()


def _text(value):
    return {'sha256': _hash(value), 'length': len(value)}


class WidgetDelivery:
    def __init__(self, record, *, ports=DEFAULT_PORTS):
        self.record = record
        # New fixture servers opt in to their exact port; existing diagnostic
        # callers retain their previous localhost-only scope.
        self.ports = tuple(ports)
        self.cache = OrderedDict()
        self.socket_sequence = 0
        self.wire_totals = WireTotals()

    def message(self, direction, raw, socket_id):
        self.wire_totals.frame(direction, raw)
        if not isinstance(raw, bytes):
            return
        msg = ForwardMsg() if direction == 'received' else BackMsg()
        try:
            msg.ParseFromString(raw)
        except DecodeError:
            return
        kind = msg.WhichOneof('type')
        self.wire_totals.kind(direction, kind)
        result = {'direction': direction, 'kind': kind, 'socket': socket_id}
        if direction == 'sent' and kind == 'rerun_script':
            run = msg.rerun_script
            result.update(fragment=run.fragment_id, automatic=run.is_auto_rerun,
                          widgets=[{'id_hash': _hash(w.id), **_text(w.string_value)}
                                   for w in list(run.widget_states.widgets)[:256]
                                   if w.WhichOneof('value') == 'string_value'])
        elif direction == 'received' and kind == 'delta':
            element = msg.delta.new_element.WhichOneof('type')
            if element not in {'text_area', 'text_input'}:
                return
            widget = getattr(msg.delta.new_element, element)
            if ((element == 'text_area' and widget.label not in {
                    'Activity summary', 'Training notes', 'Issue description'}) or
                    (element == 'text_input' and widget.label != 'Prepared by')):
                return
            result.update(widget=widget.label, id_hash=_hash(widget.id),
                          default=_text(widget.default), value=_text(widget.value),
                          set_value=widget.set_value, fragment=msg.delta.fragment_id,
                          path=list(msg.metadata.delta_path), cache_hash=msg.hash)
            if msg.hash:
                self.cache[msg.hash] = dict(result)
                self.cache.move_to_end(msg.hash)
                while len(self.cache) > 256:
                    self.cache.popitem(last=False)
        elif direction == 'received' and kind == 'ref_hash':
            previous = self.cache.get(msg.ref_hash)
            if previous is None:
                return
            result.update(referenced_widget=previous, path=list(msg.metadata.delta_path))
        elif direction == 'received' and kind == 'new_session':
            result.update(run=msg.new_session.script_run_id,
                          fragments=list(msg.new_session.fragment_ids_this_run))
        elif direction == 'received' and kind == 'script_finished':
            result['finish'] = msg.script_finished
            result['wire_totals'] = self.wire_totals.snapshot()
        else:
            return
        self.record('widget-wire', result)

    def attach(self, page):
        def connected(socket):
            parsed = urlparse(socket.url)
            if parsed.hostname != '127.0.0.1' or parsed.port not in self.ports:
                raise ValueError('Widget diagnostics require the synthetic localhost fixture')
            self.socket_sequence += 1
            socket_id = self.socket_sequence
            socket.on('framereceived', lambda raw: self.message('received', raw, socket_id))
            socket.on('framesent', lambda raw: self.message('sent', raw, socket_id))
        page.on('websocket', connected)
