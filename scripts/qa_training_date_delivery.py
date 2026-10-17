"""Bounded passive date/form wire observations for the synthetic Training task."""
from hashlib import sha256
import re
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg

DATE = re.compile(r"\d{4}(?:/\d{2}/\d{2}|-\d{2}-\d{2})\Z")


def _dates(values):
    selected = list(values)[:2]
    return {"dates": [value for value in selected if DATE.fullmatch(value)],
            "redacted_values": sum(not DATE.fullmatch(value) for value in selected)}


class TrainingDateDelivery:
    def __init__(self, record):
        self.record = record
        self.known = {}
        self.count = 0

    def message(self, direction, raw):
        if not isinstance(raw, bytes) or len(raw) > 4 * 1024 * 1024 or self.count >= 200:
            return
        message = ForwardMsg() if direction == "received" else BackMsg()
        try:
            message.ParseFromString(raw)
        except DecodeError:
            return
        kind = message.WhichOneof("type")
        row = {"direction": direction, "kind": kind}
        if direction == "received" and kind == "delta":
            element = message.delta.new_element
            widget_type = element.WhichOneof("type")
            if widget_type not in {"date_input", "button"}:
                return
            widget = getattr(element, widget_type)
            if ((widget_type == "date_input" and widget.label != "Training date") or
                    (widget_type == "button" and widget.label != "Add training session")):
                return
            if len(self.known) >= 16 and widget.id not in self.known:
                return
            self.known[widget.id] = widget_type
            row.update(widget=widget_type, id_hash=sha256(widget.id.encode()).hexdigest())
            if widget_type == "date_input":
                row.update(default=_dates(widget.default), value=_dates(widget.value),
                           set_value=widget.set_value, is_range=widget.is_range)
        elif direction == "sent" and kind == "rerun_script":
            values = []
            for widget in list(message.rerun_script.widget_states.widgets)[:1024]:
                widget_type = self.known.get(widget.id)
                if widget_type == "date_input" and widget.WhichOneof("value") == "string_array_value":
                    values.append({"widget": widget_type, **_dates(widget.string_array_value.data)})
                elif widget_type == "button" and widget.WhichOneof("value") == "trigger_value":
                    values.append({"widget": widget_type, "pressed": widget.trigger_value})
            if not values:
                return
            row.update(fragment=message.rerun_script.fragment_id, widgets=values)
        else:
            return
        self.count += 1
        self.record(row)

    def attach(self, page):
        def connected(socket):
            address = urlparse(socket.url)
            if address.hostname != "127.0.0.1" or address.port != 8535:
                raise ValueError("Training date observations require the existing synthetic localhost server")
            socket.on("framereceived", lambda raw: self.message("received", raw))
            socket.on("framesent", lambda raw: self.message("sent", raw))
        page.on("websocket", connected)
