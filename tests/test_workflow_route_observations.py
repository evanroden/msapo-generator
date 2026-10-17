"""The first-site recorder is bounded metadata, never arbitrary form contents."""
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.qa_workflow_route_observations import CHOICES, WorkflowRouteObservations, workflow_route


def test_workflow_wire_retains_native_default_and_selection_but_no_other_fields():
    recorder = WorkflowRouteObservations()
    message = ForwardMsg()
    group = message.delta.new_element.button_group
    group.id = "native-workflow"
    group.label = "Choose workflow"
    for name in CHOICES:
        group.options.add(content=name)
    group.default.append(2)
    group.raw_values.append("Monthly report")
    group.set_value = True
    raw = message.SerializeToString()
    recorder.record("received", raw)
    assert message.SerializeToString() == raw

    back = BackMsg()
    back.rerun_script.query_string = "workflow=monthly&person=PRIVATE-CANARY"
    back.rerun_script.widget_states.widgets.add(id=group.id).string_array_value.data.append("Monthly report")
    back.rerun_script.widget_states.widgets.add(id="unrelated").string_array_value.data.append("PRIVATE-CANARY")
    recorder.record("sent", back.SerializeToString())
    result = recorder.snapshot()
    assert result["events"][0]["default"] == [2]
    assert result["events"][0]["set_value"] is True
    assert result["events"][1]["values"] == [["Monthly report"]]
    assert result["events"][1]["route"] == "monthly"
    assert "PRIVATE-CANARY" not in str(result)


def test_workflow_wire_rejects_unrelated_group_and_malformed_inputs_and_bounds_history():
    recorder = WorkflowRouteObservations()
    message = ForwardMsg()
    message.delta.new_element.button_group.label = "Unrelated private field"
    recorder.record("received", message.SerializeToString())
    recorder.record("received", b"\xff")
    recorder.record("received", "not binary")
    assert recorder.snapshot() == {"total": 0, "events": []}
    back = BackMsg()
    back.rerun_script.query_string = "workflow=unknown-private-value"
    for _ in range(140):
        recorder.record("sent", back.SerializeToString())
    result = recorder.snapshot()
    assert result["total"] == 140 and len(result["events"]) == 128
    assert result["events"][0]["sequence"] == 13
    assert all(item["route"] is None for item in result["events"])
    assert "unknown-private" not in str(result)


def test_workflow_route_is_a_single_allowlisted_navigation_hint():
    assert workflow_route("http://127.0.0.1:8526/?workflow=monthly&ignored=private") == "monthly"
    assert workflow_route("http://127.0.0.1:8526/?workflow=monthly&workflow=purchase") is None
    assert workflow_route("http://127.0.0.1:8526/?workflow=unknown") is None
