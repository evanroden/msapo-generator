"""Passive, bounded button/caption delivery evidence for the localhost Water task."""
from collections import OrderedDict
from hashlib import sha256
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg


LABELS = frozenset({"Include page", "Exclude page",
                   "Page to review", "Page caption", "Report pages", "Close report pages",
                   "Move page earlier", "Move page later"})


def digest(text):
    return sha256(text.encode()).hexdigest()


class WaterWidgetDelivery:
    """Never submit events, change inputs, swallow test errors or retain raw values."""
    def __init__(self, record, *, ports=(8520,), labels=LABELS,
                 widget_types=frozenset({"button", "selectbox", "text_input"})):
        self.record = record
        self.ports, self.labels, self.widget_types = tuple(ports), frozenset(labels), frozenset(widget_types)
        self.cache = OrderedDict()
        self.known = OrderedDict()
        self.count = 0

    def message(self, direction, raw):
        if not isinstance(raw, bytes) or len(raw) > 4 * 1024 * 1024 or self.count >= 5000:
            return
        msg = ForwardMsg() if direction == "received" else BackMsg()
        try:
            msg.ParseFromString(raw)
        except DecodeError:
            return
        kind = msg.WhichOneof("type")
        row = {"direction": direction, "kind": kind}
        if direction == "received" and kind == "delta":
            element = msg.delta.new_element
            element_kind = element.WhichOneof("type")
            if element_kind not in self.widget_types:
                return
            widget = getattr(element, element_kind)
            if widget.label not in self.labels:
                return
            row.update(label=widget.label, type=element_kind, id_hash=digest(widget.id),
                       path=list(msg.metadata.delta_path), fragment=msg.delta.fragment_id)
            self.known[widget.id] = widget.label
            self.known.move_to_end(widget.id)
            while len(self.known) > 128:
                self.known.popitem(last=False)
            if msg.hash:
                self.cache[msg.hash] = dict(row)
                self.cache.move_to_end(msg.hash)
                while len(self.cache) > 128:
                    self.cache.popitem(last=False)
        elif direction == "received" and kind == "ref_hash":
            if msg.ref_hash not in self.cache:
                return
            row.update(reference=self.cache[msg.ref_hash], path=list(msg.metadata.delta_path))
        elif direction == "sent" and kind == "rerun_script":
            run = msg.rerun_script
            values = []
            for widget in list(run.widget_states.widgets)[:1024]:
                value_type = widget.WhichOneof("value")
                item = {"id_hash": digest(widget.id), "type": value_type}
                if value_type == "trigger_value" and widget.trigger_value:
                    item["pressed"] = True
                elif widget.id in self.known and value_type == "string_value":
                    item.update(sha256=digest(widget.string_value), length=len(widget.string_value))
                elif widget.id in self.known and value_type == "int_value":
                    item["index"] = widget.int_value
                else:
                    continue
                values.append(item)
            row.update(fragment=run.fragment_id, automatic=run.is_auto_rerun, widgets=values)
        elif direction == "received" and kind == "new_session":
            row.update(run=msg.new_session.script_run_id,
                       fragments=list(msg.new_session.fragment_ids_this_run))
        elif direction == "received" and kind == "script_finished":
            row["finish"] = msg.script_finished
        else:
            return
        self.count += 1
        self.record(row)

    def attach(self, page):
        def connected(socket):
            address = urlparse(socket.url)
            if address.hostname != "127.0.0.1" or address.port not in self.ports:
                raise ValueError("Water observations require the existing synthetic localhost server")
            socket.on("framereceived", lambda raw: self.message("received", raw))
            socket.on("framesent", lambda raw: self.message("sent", raw))
        page.on("websocket", connected)
