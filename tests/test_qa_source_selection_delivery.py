"""Passive synthetic receipts separate client clearing from server assignment."""
import ast
import json
from pathlib import Path

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.qa_source_selection_delivery import (
    CLIENT, LABELS, MAX_CACHE, MAX_VALUES, MAX_WIDGETS, SourceSelectionDelivery,
)
from scripts.qa_widget_delivery import _hash


def observer():
    events = []
    obj = SourceSelectionDelivery(lambda kind, item: events.append((kind, item)))
    return obj, events


def delta(kind="multiselect", key="synthetic-private-id", label=None, cache=""):
    msg = ForwardMsg(hash=cache)
    widget = getattr(msg.delta.new_element, kind)
    widget.id = key
    widget.label = LABELS[kind] if label is None else label
    if kind == "multiselect":
        widget.options.extend(["synthetic-private-source-label", "synthetic-second-label"])
    msg.metadata.delta_path.extend([0, 23, 11, 4])
    return msg, widget


def source_events(events):
    return [item for kind, item in events if kind == "source-selection-wire"]


def test_selected_empty_and_absent_client_states_are_distinct_without_raw_values():
    obj, events = observer()
    msg, widget = delta()
    obj.message("received", msg.SerializeToString(), 1)
    sent = BackMsg()
    state = sent.rerun_script.widget_states.widgets.add(id=widget.id)
    state.string_array_value.data.append(widget.options[0])
    obj.message("sent", sent.SerializeToString(), 1)
    state.string_array_value.ClearField("data")
    obj.message("sent", sent.SerializeToString(), 1)
    sent.rerun_script.widget_states.ClearField("widgets")
    obj.message("sent", sent.SerializeToString(), 1)
    before, selected, empty, absent = source_events(events)
    assert selected["widgets"][0]["selection"] == {
        "count": 1, "hashes": [_hash(widget.options[0])], "truncated": False}
    assert empty["widgets"][0]["selection"]["count"] == 0
    assert absent["widgets"][0]["present"] is False
    assert before["id_hash"] == selected["widgets"][0]["id_hash"]
    assert "synthetic-private" not in json.dumps(events)


def test_server_assignment_cache_and_checkbox_change_remain_distinct():
    obj, events = observer()
    msg, widget = delta(cache="synthetic-cache")
    widget.default.append(1)
    widget.raw_values.append(widget.options[0])
    widget.set_value = True
    obj.message("received", msg.SerializeToString(), 1)
    obj.message("received", ForwardMsg(ref_hash="synthetic-cache").SerializeToString(), 1)
    checkbox, check = delta("checkbox", "synthetic-checkbox")
    check.default = False
    check.value = True
    check.set_value = True
    obj.message("received", checkbox.SerializeToString(), 1)
    sent = BackMsg()
    state = sent.rerun_script.widget_states.widgets.add(id=check.id)
    state.bool_value = True
    obj.message("sent", sent.SerializeToString(), 1)
    state.bool_value = False
    obj.message("sent", sent.SerializeToString(), 1)
    received, cached, checked, send_true, send_false = source_events(events)
    assert received["default_indices"] == [1]
    assert received["raw_values"]["hashes"] == [_hash(widget.options[0])]
    assert received["set_value"] is True
    assert cached["referenced_widget"] == received
    assert checked["value"] is True and checked["default"] is False
    assert send_true["widgets"][1]["checked"] is True
    assert send_false["widgets"][1]["checked"] is False


def test_changed_identity_and_legacy_index_arrays_are_observed():
    obj, events = observer()
    for key in ["old-synthetic-id", "new-synthetic-id"]:
        msg, _ = delta(key=key)
        obj.message("received", msg.SerializeToString(), 1)
    sent = BackMsg()
    state = sent.rerun_script.widget_states.widgets.add(id="new-synthetic-id")
    state.int_array_value.data.append(1)
    obj.message("sent", sent.SerializeToString(), 1)
    rows = source_events(events)[-1]["widgets"]
    assert rows[0]["present"] is False
    assert rows[1]["indices"] == [1] and rows[1]["count"] == 1
    assert rows[0]["id_hash"] != rows[1]["id_hash"]


@pytest.mark.parametrize("kind,label", [("multiselect", "Source sites"),
    ("multiselect", "Supporting source pages (optional)"), ("checkbox", "Unrelated private label")])
def test_other_controls_and_unknown_client_ids_are_not_recorded(kind, label):
    obj, events = observer()
    msg, _ = delta(kind, label=label)
    obj.message("received", msg.SerializeToString(), 1)
    sent = BackMsg()
    state = sent.rerun_script.widget_states.widgets.add(id="unknown-private-id")
    state.string_array_value.data.append("private-value")
    obj.message("sent", sent.SerializeToString(), 1)
    assert source_events(events) == [{"direction": "sent", "kind": "rerun_script",
        "socket": 1, "fragment": "", "automatic": False, "widgets": []}]
    assert "private" not in json.dumps(events)


def test_values_widget_history_and_reference_cache_are_bounded():
    obj, events = observer()
    for n in range(MAX_CACHE + 5):
        msg, widget = delta(key=f"widget-{n}", cache=f"cache-{n}")
        widget.options.extend(["sensitive-label"] * (MAX_VALUES + 5))
        obj.message("received", msg.SerializeToString(), 1)
    assert len(obj.source_widgets) == MAX_WIDGETS
    assert len(obj.source_cache) == MAX_CACHE
    receipt = source_events(events)[-1]
    assert len(receipt["options"]["hashes"]) == MAX_VALUES
    assert receipt["options"]["count"] == MAX_VALUES + 7
    assert receipt["options"]["truncated"] is True
    assert "sensitive-label" not in json.dumps(events)


def test_malformed_and_unrecognized_references_add_no_source_receipts():
    obj, events = observer()
    for raw in [b"\xff", "raw-text", ForwardMsg(ref_hash="unknown").SerializeToString()]:
        obj.message("received", raw, 1)
    assert not source_events(events)


@pytest.mark.parametrize("url", ["ws://127.0.0.1:8521/_stcore/stream",
    "wss://example.invalid:8520/_stcore/stream", "ws://localhost:8520/_stcore/stream"])
def test_only_the_existing_exact_localhost_source_fixture_is_allowed(url):
    obj, _ = observer()
    class Page:
        def on(self, event, listener):
            self.listener = listener
    class Socket:
        def on(self, *_):
            pytest.fail("Rejected socket must not receive frame listeners")
    page, socket = Page(), Socket()
    socket.url = url
    obj.attach(page)
    with pytest.raises(ValueError, match="synthetic localhost"):
        page.listener(socket)


def test_native_listener_is_passive_bounded_and_never_records_text_or_changes_input():
    assert "location.port !== '8520'" in CLIENT
    assert "count >= 120" in CLIENT and "capture:true,passive:true" in CLIENT
    for forbidden in ["preventDefault", "stopPropagation", ".click(", ".focus(",
                      "textContent", "innerText", ".value", "dispatchEvent", "setTimeout"]:
        assert forbidden not in CLIENT
    assert "selectedTags:" in CLIENT and "checked:" in CLIENT


def test_source_journey_is_the_only_explicit_observer_opt_in():
    root = Path(__file__).resolve().parents[1]
    paths = [p for p in (root / "scripts").glob("*.py")
             if "source_selection=True" in p.read_text()]
    assert paths == [root / "scripts/qa_source_corrections.py"]
    module = ast.parse(paths[0].read_text())
    task = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == "browser_task")
    assert "source_selection" not in ast.unparse(task)
