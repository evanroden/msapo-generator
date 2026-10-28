"""Read-only wire evidence for dirty-note blur plus native Close; no browser replay."""
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_widget_delivery import WidgetDelivery, _hash


def test_blur_and_close_envelopes_remain_distinguishable_without_raw_ids_or_values():
    events = []
    observer = WidgetDelivery(lambda kind, row: events.append(row))
    rendered = ForwardMsg()
    rendered.delta.new_element.button.id = 'synthetic-close-widget'
    rendered.delta.new_element.button.label = 'Close editing'
    observer.message('received', rendered.SerializeToString(), 1)
    blur = BackMsg()
    blur.rerun_script.widget_states.widgets.add(id='synthetic-note').string_value = 'Synthetic changed note'
    blur.rerun_script.widget_states.widgets.add(id='synthetic-close-widget').trigger_value = False
    close = BackMsg()
    close.CopyFrom(blur)
    close.rerun_script.widget_states.widgets[-1].trigger_value = True
    observer.message('sent', blur.SerializeToString(), 1)
    observer.message('sent', close.SerializeToString(), 1)
    assert events[0]['widget'] == 'Close editing'
    assert events[0]['id_hash'] == _hash('synthetic-close-widget')
    assert events[1]['actions'] == [{'id_hash': events[0]['id_hash'], 'pressed': False}]
    assert events[2]['actions'] == [{'id_hash': events[0]['id_hash'], 'pressed': True}]
    assert events[1]['widgets'] == events[2]['widgets']
    import json
    result = json.dumps(events)
    assert 'synthetic-close-widget' not in result
    assert 'Synthetic changed note' not in result


def test_callback_trace_preserves_arguments_return_and_state_changes():
    from scripts.qa_row_callback_delivery import trace_callback
    state = {'row': {'pending': None}}
    events, calls = [], []
    sentinel = object()
    def native(*args, **kwargs):
        calls.append((args, kwargs))
        state['row']['pending'] = {'active': None}
        return sentinel
    traced = trace_callback(native, lambda: state, events.append)
    args = ('row', (), (), 'token', (), 'close')
    assert traced(*args, preserve_empty=True) is sentinel
    assert calls == [(args, {'preserve_empty': True})]
    assert [event['phase'] for event in events] == ['before', 'after']
    assert all(event['action'] == 'close' for event in events)
    assert events[0]['pending_hash'] != events[1]['pending_hash']
    assert 'token' not in str(events)


def test_callback_exception_and_broken_diagnostics_do_not_change_native_behavior():
    import pytest
    from scripts.qa_row_callback_delivery import trace_callback
    failure = ValueError('native callback failure')
    def native(*args, **kwargs):
        raise failure
    def broken(*args):
        raise RuntimeError('diagnostic sink failure')
    traced = trace_callback(native, lambda: {}, broken)
    with pytest.raises(ValueError) as caught:
        traced('row', (), (), None, ())
    assert caught.value is failure


def test_importing_diagnostics_does_not_patch_product_and_fixture_guard_precedes_install():
    from app import monthly_report_row_cards_ui as row_ui
    original = row_ui._queue
    import importlib
    from scripts import qa_row_callback_delivery
    importlib.reload(qa_row_callback_delivery)
    assert row_ui._queue is original
    from pathlib import Path
    source = Path('tests/fixtures/workspaces/monthly_app.py').read_text()
    assert source.index('st.stop()') < source.index('install(monthly_report_row_cards_ui')
    assert 'if os.environ.get("EPC_MONTHLY_ROW_TASK") == "1":' in source


def test_install_is_idempotent_and_calls_native_once(capsys):
    from types import SimpleNamespace
    from scripts.qa_row_callback_delivery import install
    calls = []
    native = lambda *args, **kwargs: calls.append((args, kwargs))
    row_ui = SimpleNamespace(_queue=native)
    install(row_ui, lambda: {})
    first = row_ui._queue
    install(row_ui, lambda: {})
    assert row_ui._queue is first
    row_ui._queue('row', (), (), None, (), 'close')
    assert len(calls) == 1
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all(line.startswith('ENFRA_QA_ROW_CALLBACK ') for line in lines)
