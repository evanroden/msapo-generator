"""Protobuf receipts distinguish defaults, server assignments and sent edits."""
import json

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_widget_delivery import WidgetDelivery, _hash


def test_observer_retains_only_hashes_and_distinguishes_a_sent_empty_value():
    events = []
    observer = WidgetDelivery(lambda kind, item: events.append((kind, item)))
    msg = BackMsg()
    widget = msg.rerun_script.widget_states.widgets.add(id='synthetic-widget')
    widget.string_value = 'synthetic sentence'
    observer.message('sent', msg.SerializeToString(), 1)
    widget.string_value = ''
    observer.message('sent', msg.SerializeToString(), 1)
    assert events[0][1]['widgets'][0]['sha256'] == _hash('synthetic sentence')
    assert events[1][1]['widgets'][0]['length'] == 0
    assert 'synthetic sentence' not in json.dumps(events)
    assert 'synthetic-widget' not in json.dumps(events)


def test_received_default_assignment_and_cached_receipt_are_distinct():
    events = []
    observer = WidgetDelivery(lambda kind, item: events.append(item))
    msg = ForwardMsg(hash='cached')
    widget = msg.delta.new_element.text_area
    widget.id = 'synthetic-widget'
    widget.label = 'Activity summary'
    widget.default = 'earlier'
    widget.value = 'current'
    widget.set_value = True
    observer.message('received', msg.SerializeToString(), 1)
    observer.message('received', ForwardMsg(ref_hash='cached').SerializeToString(), 1)
    assert events[0]['set_value'] is True
    assert events[0]['default']['sha256'] == _hash('earlier')
    assert events[0]['value']['sha256'] == _hash('current')
    assert events[1]['referenced_widget'] == events[0]
    assert 'earlier' not in json.dumps(events) and 'current' not in json.dumps(events)


def test_malformed_or_unrelated_messages_are_not_recorded():
    events = []
    observer = WidgetDelivery(lambda *event: events.append(event))
    for raw in (b'\xff', 'unparsed', ForwardMsg(ref_hash='unknown').SerializeToString()):
        observer.message('received', raw, 1)
    assert not events


def test_external_socket_cannot_be_observed():
    class Page:
        def on(self, event, listener):
            self.listener = listener
    page = Page()
    WidgetDelivery(lambda *_: None).attach(page)
    class Socket:
        url = 'wss://example.invalid/_stcore/stream'
    with pytest.raises(ValueError, match='synthetic localhost'):
        page.listener(Socket())
