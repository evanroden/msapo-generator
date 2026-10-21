"""Metadata-only observation retains noncacheable root deltas without text."""
import json

from scripts.qa_preparer_reload_observations import ReloadObservations
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from streamlit.proto.BackMsg_pb2 import BackMsg


def test_uncacheable_root_messages_are_counted_without_private_bodies():
    observer = ReloadObservations()
    message = ForwardMsg()
    message.delta.new_element.text.body = 'SENSITIVE SENTINEL'
    message.metadata.delta_path.extend([0, 0])
    observer.message('received', message.SerializeToString(), 2)
    result = observer.snapshot()
    assert result['counts'] == {'received:delta': 1}
    assert result['events'][0]['path'] == [0, 0]
    assert result['events'][0]['element'] == 'text'
    assert result['events'][0]['cacheable'] is False
    assert 'SENSITIVE' not in json.dumps(result)


def test_complete_message_type_count_and_reload_request_metadata():
    observer = ReloadObservations()
    message = ForwardMsg(); message.page_config_changed.title = 'PRIVATE TITLE'
    observer.message('received', message.SerializeToString(), 2)
    message = ForwardMsg(); message.script_finished = 0
    observer.message('received', message.SerializeToString(), 2)
    message = BackMsg(); message.rerun_script.is_auto_rerun = False
    message.rerun_script.query_string = 'private=SECRET'
    observer.message('sent', message.SerializeToString(), 2)
    result = observer.snapshot()
    assert result['counts'] == {'received:page_config_changed': 1,
                                'received:script_finished': 1, 'sent:rerun_script': 1}
    assert result['events'][-1] == dict(direction='sent', kind='rerun_script', socket=2,
        bytes=len(message.SerializeToString()), fragment=False, automatic=False, widgets=0, cached=0)
    assert 'SECRET' not in json.dumps(result) and 'PRIVATE' not in json.dumps(result)


def test_bounded_events_keep_total_counts_and_invalid_messages():
    observer = ReloadObservations()
    message = ForwardMsg(); message.script_finished = 0
    for _ in range(2005): observer.message('received', message.SerializeToString(), 1)
    observer.message('received', 'not binary', 1)
    observer.message('received', b'\xff', 1)
    result = observer.snapshot()
    assert len(result['events']) == 2000
    assert result['counts']['received:script_finished'] == 2005
    assert result['counts']['received:nonbinary'] == 1
    assert result['counts']['received:decode_error'] == 1
