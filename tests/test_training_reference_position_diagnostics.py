"""Read-only original-control geometry must not change strict native positioning."""
import ast
from pathlib import Path
import types

SOURCE = Path(__file__).parents[1] / "scripts/qa_monthly_training_date.py"


def helper():
    tree = ast.parse(SOURCE.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "reference_position_observation")
    scope = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope[node.name]


def test_exact_original_handle_read_only_bounded_observation():
    calls = []
    observation = {"rect": {"y": 772}, "rootScrollTop": 0}
    def evaluate(script):
        calls.append(script)
        return observation
    assert helper()(types.SimpleNamespace(evaluate=evaluate)) is observation
    script = calls[0]
    assert "ancestors.length<12" in script
    assert "getBoundingClientRect" in script and "document.fonts?.status" in script
    for forbidden in ("scrollTo(", "scrollIntoView(", ".click(", ".focus(", ".style.", "input.value", "innerText"):
        assert forbidden not in script


def test_detached_handle_is_evidence_not_refind_or_exception_mask():
    error = RuntimeError("detached")
    def evaluate(script):
        raise error
    assert helper()(types.SimpleNamespace(evaluate=evaluate)) == {"observation_error": "RuntimeError"}


def test_same_single_wheel_and_strict_one_pixel_5000ms_original_handle_contract():
    tree = ast.parse(SOURCE.read_text())
    journey = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                   and n.name == "exercise_participant_reference")
    wheels = [n for n in ast.walk(journey) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "wheel"]
    assert len(wheels) == 1
    assert ast.unparse(wheels[0]) == "page.mouse.wheel(0, plan['wheel_delta'])"
    waits = [n for n in ast.walk(journey) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "wait_for_function"
             and isinstance(n.args[0], ast.Constant)]
    positioning = [n for n in waits if "getBoundingClientRect().top" in str(n.args[0].value)]
    assert len(positioning) == 1
    assert positioning[0].args[0].value == "({input,target})=>input.isConnected&&Math.abs(input.getBoundingClientRect().top-target)<=1"
    assert ast.unparse(positioning[0]) == "page.wait_for_function('({input,target})=>input.isConnected&&Math.abs(input.getBoundingClientRect().top-target)<=1', arg={'input': original_input, 'target': plan['target_top']}, timeout=5000)"
    assert any(isinstance(n, ast.Try) and n.finalbody for n in ast.walk(journey))
