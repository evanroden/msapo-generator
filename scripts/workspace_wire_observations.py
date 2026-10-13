"""Bounded protocol metadata for localhost synthetic browser tests only.

Never retain message bodies, widget values, source bytes, query strings or URLs.
This observes Streamlit's cache protocol without changing its behavior.
"""
from collections import deque
from urllib.parse import urlparse

from google.protobuf.message import DecodeError
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg


class WireObservations:
    def __init__(self, port):
        self.port = port
        self.events = deque(maxlen=2000)
        self.sequence = 0

    def record(self, direction, payload):
        if not isinstance(payload, bytes):
            return
        message = ForwardMsg() if direction == "received" else BackMsg()
        try:
            message.ParseFromString(payload)
        except DecodeError:
            return
        kind = message.WhichOneof("type")
        item = {"direction": direction, "kind": kind, "bytes": len(payload)}
        if direction == "received":
            if kind == "delta" and message.metadata.cacheable:
                item.update(hash=message.hash, element=message.delta.new_element.WhichOneof("type"),
                            fragment=message.delta.fragment_id, path=list(message.metadata.delta_path))
            elif kind == "ref_hash":
                item.update(hash=message.ref_hash, path=list(message.metadata.delta_path))
            elif kind == "new_session":
                item.update(run=message.new_session.script_run_id,
                            fragments=list(message.new_session.fragment_ids_this_run),
                            max_cache_age=message.new_session.config.max_cached_message_age)
            elif kind == "script_finished":
                item["finish"] = message.script_finished
            else:
                return
        elif kind == "rerun_script":
            item.update(fragment=message.rerun_script.fragment_id,
                        auto=message.rerun_script.is_auto_rerun,
                        cached=list(message.rerun_script.cached_message_hashes)[:200])
        else:
            return
        self.sequence += 1
        self.events.append({"sequence": self.sequence, **item})

    def attach(self, page):
        def connected(socket):
            parsed = urlparse(socket.url)
            if parsed.hostname != "127.0.0.1" or parsed.port != self.port:
                raise ValueError("Wire observations require the isolated localhost fixture")
            socket.on("framereceived", lambda payload: self.record("received", payload))
            socket.on("framesent", lambda payload: self.record("sent", payload))
        page.on("websocket", connected)

    def snapshot(self):
        return {"total_events": self.sequence, "events": list(self.events)}
