"""The date diagnostic observes only the marked synthetic date/form controls."""
import json
from hashlib import sha256

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

from scripts.qa_training_date_delivery import TrainingDateDelivery


def learn(observer, widget_type, label, identity):
    message = ForwardMsg()
    widget = getattr(message.delta.new_element, widget_type)
    widget.id, widget.label = identity, label
    observer.message("received", message.SerializeToString())


def test_records_actual_date_submission_and_button_without_unrelated_values():
    rows = []
    observer = TrainingDateDelivery(rows.append)
    learn(observer, "date_input", "Training date", "synthetic-date-id")
    learn(observer, "button", "Add completed training", "synthetic-submit-id")
    learn(observer, "text_input", "Prepared by", "unrelated-name")
    message = BackMsg()
    message.rerun_script.widget_states.widgets.add(id="synthetic-date-id").string_array_value.data.extend(["2026/08/31"])
    message.rerun_script.widget_states.widgets.add(id="synthetic-submit-id", trigger_value=True)
    message.rerun_script.widget_states.widgets.add(id="unrelated-name", string_value="Private unrelated text")
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [
        {"widget": "date_input", "dates": ["2026/08/31"], "redacted_values": 0},
        {"widget": "button", "pressed": True}]
    assert "Private unrelated text" not in json.dumps(rows)
    assert "synthetic-date-id" not in json.dumps(rows)


def test_empty_date_is_distinct_from_unknown_or_unrelated_wire_value():
    rows = []
    observer = TrainingDateDelivery(rows.append)
    learn(observer, "date_input", "Training date", "date")
    message = BackMsg()
    message.rerun_script.widget_states.widgets.add(id="date").string_array_value.SetInParent()
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [{"widget": "date_input", "dates": [], "redacted_values": 0}]
    message.rerun_script.widget_states.widgets[0].string_array_value.data.append("not a date or permitted text")
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [{"widget": "date_input", "dates": [], "redacted_values": 1}]
    assert "not a date" not in json.dumps(rows)


def test_participant_wire_records_selection_and_later_clear_without_names():
    rows = []
    observer = TrainingDateDelivery(rows.append)
    learn(observer, "multiselect", "Participants", "participant-id")
    learn(observer, "multiselect", "Unrelated staff", "other-id")
    message = BackMsg()
    selected = message.rerun_script.widget_states.widgets.add(id="participant-id")
    selected.string_array_value.data.append("Synthetic Person North")
    message.rerun_script.widget_states.widgets.add(id="other-id").string_array_value.data.append("Private unrelated name")
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [{"widget": "multiselect", "count": 1,
        "value_hashes": [sha256(b"Synthetic Person North").hexdigest()]}]
    selected.string_array_value.ClearField("data")
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [{"widget": "multiselect", "count": 0, "value_hashes": []}]
    assert "Synthetic Person North" not in json.dumps(rows)
    assert "Private unrelated name" not in json.dumps(rows)


def test_unknown_date_widgets_and_malformed_frames_are_ignored_and_capture_is_bounded():
    rows = []
    observer = TrainingDateDelivery(rows.append)
    learn(observer, "date_input", "Unrelated date", "unknown")
    observer.message("received", b"not protobuf")
    assert rows == []
    for _ in range(250):
        learn(observer, "date_input", "Training date", "date")
    assert len(rows) == observer.count == 200


def test_wire_diagnostics_refuse_a_live_or_different_local_server():
    observer = TrainingDateDelivery(lambda row: None)
    class Page:
        def on(self, event, callback):
            self.callback = callback
    class Socket:
        url = "https://msapo-generator.onrender.com/_stcore/stream"
    page = Page()
    observer.attach(page)
    import pytest
    with pytest.raises(ValueError, match="existing synthetic localhost server"):
        page.callback(Socket())
