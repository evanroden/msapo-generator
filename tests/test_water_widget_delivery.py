"""Synthetic protocol observation does not submit or retain arbitrary input."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from scripts.qa_water_widget_delivery import WaterWidgetDelivery, digest


def test_caption_and_button_receipts_are_correlated_without_raw_values():
    rows = []
    observer = WaterWidgetDelivery(rows.append)
    for kind, label, identifier in (("button", "Include page", "page-2-action"),
                                    ("text_input", "Page caption", "caption-2")):
        message = ForwardMsg()
        widget = getattr(message.delta.new_element, kind)
        widget.id, widget.label = identifier, label
        observer.message("received", message.SerializeToString())
    message = BackMsg()
    button = message.rerun_script.widget_states.widgets.add(id="page-2-action", trigger_value=True)
    message.rerun_script.widget_states.widgets.add(id="caption-2", string_value="Synthetic pending caption")
    message.rerun_script.widget_states.widgets.add(id="unrelated", string_value="Do not record unrelated input")
    observer.message("sent", message.SerializeToString())
    assert rows[-1]["widgets"] == [
        {"id_hash": digest(button.id), "type": "trigger_value", "pressed": True},
        {"id_hash": digest("caption-2"), "type": "string_value",
         "sha256": digest("Synthetic pending caption"), "length": len("Synthetic pending caption")},
    ]
    assert "Synthetic pending caption" not in json.dumps(rows)
    assert "Do not record unrelated input" not in json.dumps(rows)


def test_cached_action_identity_and_completion_are_observed():
    rows=[]
    observer=WaterWidgetDelivery(rows.append)
    message=ForwardMsg(hash="entry")
    message.delta.new_element.button.id="action"
    message.delta.new_element.button.label="Exclude page"
    message.metadata.delta_path.extend([1,2])
    observer.message("received",message.SerializeToString())
    reference=ForwardMsg(ref_hash="entry")
    observer.message("received",reference.SerializeToString())
    assert rows[-1]["reference"]["id_hash"]==digest("action")
    observer.message("received",ForwardMsg(script_finished=0).SerializeToString())
    assert rows[-1]["kind"]=="script_finished"


def test_observation_is_bounded_and_ignores_malformed_frames():
    rows=[]
    observer=WaterWidgetDelivery(rows.append)
    for raw in ("not bytes", b"\xff", b"x"*(4*1024*1024+1)):
        observer.message("received",raw)
    assert not rows
    observer.count=5000
    observer.message("received",ForwardMsg(script_finished=0).SerializeToString())
    assert not rows


def test_socket_scope_is_not_a_route_or_policy_workaround():
    handlers={}
    observer=WaterWidgetDelivery(lambda row: None)
    observer.attach(SimpleNamespace(on=lambda name,fn:handlers.update({name:fn})))
    calls=[]
    handlers["websocket"](SimpleNamespace(url="ws://127.0.0.1:8520/_stcore/stream",on=lambda *v:calls.append(v)))
    assert [name for name, _ in calls]==["framereceived","framesent"]
    for url in ("wss://msapo-generator.onrender.com/_stcore/stream", "ws://127.0.0.1:8521/stream"):
        with pytest.raises(ValueError,match="synthetic localhost"):
            handlers["websocket"](SimpleNamespace(url=url))


def test_water_preview_positions_its_actual_surface_before_demanding_current_output():
    path=Path(__file__).resolve().parents[1]/"scripts/qa_water_page_journey.py"
    tree=ast.parse(path.read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="current_water_preview")
    scope={"WATER":"actual-water-pair"}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(path),"exec"),scope)
    calls=[]
    qa=SimpleNamespace(scroll_pair=lambda *a,**kw:calls.append(("scroll",a,kw)),
                       current_image=lambda *a:calls.append(("current",a)))
    scope["current_water_preview"]("page",qa,inset=90)
    assert calls==[("scroll",("page","actual-water-pair"),{"inset":90,"preview":True}),
                   ("current",("page","actual-water-pair"))]
