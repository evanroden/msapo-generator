"""Reachable native reference positioning, never a tolerance/product change."""
import ast
from pathlib import Path

import pytest

SOURCE=Path(__file__).parents[1]/"scripts/qa_monthly_training_date.py"


def plan(before, observed):
    tree=ast.parse(SOURCE.read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="reference_scroll_plan"]
    assert len(nodes)==1,"Native reference needs an explicit reachable-position plan"
    scope={}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),"exec"),scope)
    return scope["reference_scroll_plan"](before,observed)


def observation(y,scroll=0,extent=1070):
    before={"x":419,"y":y,"width":363.59375,"height":28}
    observed={"connected":True,"rect":dict(before),"windowHeight":900,
              "ancestors":[{"testid":"stMain","scrollTop":scroll,"scrollHeight":900+extent,
                            "clientHeight":900,"overflowY":"auto"}]}
    return before,observed


@pytest.mark.parametrize("y,scroll,extent,target,wheel,reason",[
    (797.96875,0,1070,780,17.96875,"desired-reachable"),
    (771.59375,0,1070,771.59375,0,"native-top-boundary"),
    (771.59375,20,1070,780,-8.40625,"desired-reachable"),
    (850,1050,1070,830,20,"native-bottom-boundary"),
    (780,0,1070,780,0,"desired-reachable"),
])
def test_exact_normal_top_bottom_and_noop_bounds(y,scroll,extent,target,wheel,reason):
    result=plan(*observation(y,scroll,extent))
    assert result["target_top"]==target and result["wheel_delta"]==wheel
    assert result["reason"]==reason and result["desired_top"]==780
    assert result["tolerance"]==1


def test_native_webkit_captured_geometry_no_longer_requests_impossible_negative_scroll():
    before,observed=observation(771.59375)
    result=plan(before,observed)
    assert result["requested_delta"]==-8.40625
    assert result["wheel_delta"]==0
    assert result["target_top"]!=780
    assert result["target_top"]==observed["rect"]["y"]


@pytest.mark.parametrize("bad",["detached","drift","unknown-owner","negative-scroll","invalid-height","offscreen"])
def test_invalid_or_changed_original_geometry_fails_closed(bad):
    before,observed=observation(797.96875)
    if bad=="detached":observed["connected"]=False
    elif bad=="drift":observed["rect"]["y"]+=2
    elif bad=="unknown-owner":observed["ancestors"][0]["testid"]="other"
    elif bad=="negative-scroll":observed["ancestors"][0]["scrollTop"]=-5
    elif bad=="invalid-height":observed["ancestors"][0]["scrollHeight"]=0
    else:observed["windowHeight"]=700
    with pytest.raises(AssertionError):plan(before,observed)


@pytest.mark.parametrize("y,scroll,extent,target,wheel",[
    (797.96875,0,1070,780,17.96875),
    (771.59375,0,1070,771.59375,0),
    (850,1050,1070,830,20),
])
def test_actual_driver_position_block_keeps_original_handle_and_one_native_gesture(y,scroll,extent,target,wheel):
    from types import SimpleNamespace
    tree=ast.parse(SOURCE.read_text())
    helper=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="reference_scroll_plan")
    journey=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="exercise_participant_reference")
    body=next(n for n in journey.body if isinstance(n,ast.Try)).body
    start=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign)
               and '["reference_position_before_wheel"]' in ast.get_source_segment(SOURCE.read_text(),n))
    stop=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign)
              and ast.unparse(n.targets[0])=="positioned")
    original=object();before,observed=observation(y,scroll,extent);events=[]
    def wait(predicate,*,arg,timeout):
        assert predicate=="({input,target})=>input.isConnected&&Math.abs(input.getBoundingClientRect().top-target)<=1"
        assert arg["input"] is original and arg["target"]==target and timeout==5000
        events.append("strict original-handle wait")
    def observe(handle):
        assert handle is original
        events.append("read")
        return observed
    page=SimpleNamespace(mouse=SimpleNamespace(move=lambda *a:events.append("move"),
             wheel=lambda x,delta:events.append(("wheel",x,delta))),wait_for_function=wait)
    scope={"before":before,"original_input":original,"page":page,
           "live":SimpleNamespace(EVIDENCE={}),"reference_position_observation":observe}
    exec(compile(ast.Module(body=[helper]+body[start:stop],type_ignores=[]),str(SOURCE),"exec"),scope)
    assert events==["read","move",("wheel",0,wheel),"strict original-handle wait","read"]
    assert scope["live"].EVIDENCE["reference_scroll_plan"]["target_top"]==target
