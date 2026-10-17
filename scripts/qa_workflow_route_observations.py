"""Bounded, read-only workflow messages in the isolated first-site journey.

Retain only the three public workflow choices, their widget identity and the
public route. Never retain arbitrary widget values, URLs or query parameters.
"""
from collections import deque
from urllib.parse import parse_qs, urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

CHOICES = ("Purchase order", "Expense reimbursement", "Monthly report")


def workflow_route(url):
    values = parse_qs(urlparse(url).query).get("workflow", [])
    return values[0] if len(values) == 1 and values[0] in {"purchase", "expense", "monthly"} else None


class WorkflowRouteObservations:
    def __init__(self):
        self.events = deque(maxlen=128)
        self.widget_ids = set()
        self.total = 0

    def record(self, direction, payload):
        if not isinstance(payload, bytes):
            return
        message = ForwardMsg() if direction == "received" else BackMsg()
        try:
            message.ParseFromString(payload)
        except DecodeError:
            return
        kind = message.WhichOneof("type")
        item = None
        if direction == "received" and kind == "delta":
            element = message.delta.new_element
            if element.WhichOneof("type") == "button_group":
                group = element.button_group
                if group.label == "Choose workflow" and tuple(o.content for o in group.options) == CHOICES:
                    self.widget_ids.add(group.id)
                    item = {"direction": direction, "kind": "workflow", "id": group.id,
                            "default": list(group.default), "set_value": group.set_value,
                            "values": [v for v in group.raw_values if v in CHOICES]}
        elif direction == "sent" and kind == "rerun_script":
            rerun = message.rerun_script
            values = [list(w.string_array_value.data) for w in rerun.widget_states.widgets
                      if w.id in self.widget_ids and w.WhichOneof("value") == "string_array_value"]
            item = {"direction": direction, "kind": kind,
                    "route": workflow_route("http://127.0.0.1:8526/?" + rerun.query_string),
                    "values": [[v for v in row if v in CHOICES] for row in values]}
        if item is not None:
            self.total += 1
            self.events.append({"sequence": self.total, **item})

    def attach(self, page):
        def connected(socket):
            parsed = urlparse(socket.url)
            if parsed.hostname != "127.0.0.1" or parsed.port != 8526:
                raise ValueError("Workflow observations require the isolated first-site server")
            socket.on("framereceived", lambda payload: self.record("received", payload))
            socket.on("framesent", lambda payload: self.record("sent", payload))
        page.on("websocket", connected)

    def snapshot(self):
        return {"total": self.total, "events": list(self.events)}
