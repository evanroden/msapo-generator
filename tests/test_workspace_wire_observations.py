import json

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.workspace_wire_observations import WireObservations


def test_wire_observer_keeps_cache_order_without_widget_or_report_content():
    observer = WireObservations(8520)
    message = ForwardMsg()
    message.hash = 'a' * 32
    message.metadata.cacheable = True
    message.delta.new_element.markdown.body = 'PRIVATE REPORT'
    observer.record('received', message.SerializeToString())
    rerun = BackMsg()
    rerun.rerun_script.query_string = 'PRIVATE TOKEN'
    rerun.rerun_script.widget_states.widgets.add().string_value = 'PRIVATE INPUT'
    rerun.rerun_script.cached_message_hashes.append('a' * 32)
    observer.record('sent', rerun.SerializeToString())
    reference = ForwardMsg(ref_hash='a' * 32)
    observer.record('received', reference.SerializeToString())
    result = observer.snapshot()
    assert result['total_events'] == 3
    assert result['events'][0]['element'] == 'markdown'
    assert result['events'][1]['cached'] == ['a' * 32]
    assert result['events'][2]['kind'] == 'ref_hash'
    assert 'PRIVATE' not in json.dumps(result)


def test_wire_observer_is_bounded_and_ignores_non_protocol_messages():
    observer = WireObservations(8520)
    observer.record('received', 'PRIVATE TEXT')
    observer.record('received', b'\xff')
    assert not observer.events
    payload = ForwardMsg(script_finished=0).SerializeToString()
    for _ in range(2100):
        observer.record('received', payload)
    assert len(observer.events) == 2000
    assert observer.snapshot()['total_events'] == 2100
