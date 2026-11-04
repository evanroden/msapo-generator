"""Synthetic observer controls; these do not establish native gesture acceptance."""
import ast
import inspect
import json
from pathlib import Path
import subprocess

import pytest

from scripts import qa_source_corrections as qa


@pytest.fixture(scope="module")
def observer_source(tmp_path_factory):
    scripts = []

    class Page:
        def evaluate(self, source, *args):
            assert not args
            scripts.append(source)

    qa.observe_correction_navigation(Page())
    assert scripts
    path = tmp_path_factory.mktemp("source-observer") / "installer.json"
    path.write_text(json.dumps(scripts))
    return path


@pytest.mark.parametrize("case", [
    "admission", "input-flags", "intermediate-geometry", "unrelated-pointer", "before-gesture",
    "pointerup", "pointercancel", "wheel", "keydown", "blur", "pagehide",
    "visibilitychange", "identity-changes", "sample-limit", "reinstall",
    "passive-traps", "descendant-blur-outside", "descendant-blur-button",
])
def test_cold_gesture_observer_contract(observer_source, case):
    run = subprocess.run(
        ["node", str(Path(__file__).with_name("source_correction_observations_test.cjs")),
         str(observer_source), case],
        capture_output=True, text=True, timeout=15,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(run.stdout) == {"case": case, "passed": True}


def collector():
    collect = getattr(qa, "_capture_cold_gesture_observations", None)
    assert callable(collect), "The first cold gesture needs a failure-safe evidence collector"
    return collect


def test_collector_keeps_first_result_across_reload():
    collect = collector()
    evidence = {"sampleLimit": 128, "samples": [{"type": "pointerdown"}]}
    calls = []

    class Page:
        def evaluate(self, expression):
            calls.append(expression)
            assert "__sourceColdGestureObservations" in expression
            return evidence

    record = {"stage": "synthetic cold warning"}
    collect(Page(), record)
    assert record["cold_gesture_observations"] == evidence
    assert len(calls) == 1
    collect(Page(), record)
    assert len(calls) == 1
    assert record["cold_gesture_observations"] == evidence


@pytest.mark.parametrize("evidence", [
    None, [], {}, {"sampleLimit": 127, "samples": [{"type": "pointerdown"}]},
    {"sampleLimit": 128, "samples": []}, {"sampleLimit": 128, "samples": {}},
    {"sampleLimit": 128, "samples": [None]},
    {"sampleLimit": 128, "samples": [{"type": "pointerup"}]},
    {"sampleLimit": 128, "samples": [{"type": "pointerdown"}] * 129},
])
def test_missing_or_malformed_evidence_is_an_error_and_is_not_retried(evidence):
    collect = collector()
    calls = []

    class Page:
        def evaluate(self, expression):
            calls.append(expression)
            return evidence

    record = {}
    collect(Page(), record)
    assert "cold_gesture_observations" not in record
    error = record["cold_gesture_observation_failure"]
    assert error.startswith("ValueError:") and len(error) <= 500
    collect(Page(), record)
    assert len(calls) == 1 and record["cold_gesture_observation_failure"] == error


def test_collection_failure_cannot_replace_original_browser_exception():
    collect = collector()
    original = RuntimeError("synthetic native click failed")
    record = {"result": "failed", "failure": {"message": str(original)}}
    calls = []

    class Page:
        def evaluate(self, expression):
            calls.append(expression)
            raise ValueError("synthetic closed page " + "x" * 600)

    with pytest.raises(RuntimeError) as raised:
        try:
            raise original
        finally:
            collect(Page(), record)
    assert raised.value is original
    assert record["failure"] == {"message": str(original)}
    error = record["cold_gesture_observation_failure"]
    assert error.startswith("ValueError: synthetic closed page") and len(error) <= 500
    collect(Page(), record)
    assert len(calls) == 1 and record["cold_gesture_observation_failure"] == error


def test_first_gesture_is_collected_before_reload_and_from_finally():
    """Check integration order without pretending to run the browser journey."""
    function = ast.parse(inspect.getsource(qa.browser_task)).body[0]
    journey = next(node for node in function.body if isinstance(node, ast.Try))

    def call_line(statements, name):
        return [node.lineno for statement in statements for node in ast.walk(statement)
                if isinstance(node, ast.Call) and
                ((isinstance(node.func, ast.Name) and node.func.id == name) or
                 (isinstance(node.func, ast.Attribute) and node.func.attr == name))]

    captures = call_line(journey.body, "_capture_cold_gesture_observations")
    reloads = call_line(journey.body, "reload")
    assert captures and reloads and min(captures) < min(reloads)
    assert call_line(journey.finalbody, "_capture_cold_gesture_observations")


@pytest.mark.parametrize("outcome", [
    "complete", "missing", "descendant-blur", "unfinished", "sample-limit", "different-pointer",
])
def test_success_path_requires_collected_evidence_before_reload(outcome):
    """Execute the real pre-reload collection/assertion statements in isolation."""
    function = ast.parse(inspect.getsource(qa.browser_task)).body[0]
    journey = next(node for node in function.body if isinstance(node, ast.Try))
    selected = []
    for position, statement in enumerate(journey.body):
        if (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == "_capture_cold_gesture_observations"):
            selected.append(statement)
            for following in journey.body[position + 1:]:
                if not isinstance(following, (ast.Assign, ast.Assert)):
                    break
                selected.append(following)
            break
    assert len(selected) >= 2, "Successful native journeys must qualify evidence before reload"

    class Page:
        def evaluate(self, expression):
            if outcome == "missing":
                return None
            samples = [{"type": "pointerdown", "event": {"pointerId": 7}}]
            reason, truncated = "pointerup", False
            if outcome in {"complete", "different-pointer"}:
                samples.append({"type": "pointerup", "event": {
                    "pointerId": 9 if outcome == "different-pointer" else 7}})
            elif outcome == "descendant-blur":
                samples.append({"type": "blur", "event": {"targetTag": "BUTTON", "pointerId": None}})
                reason = "blur"
            elif outcome == "unfinished":
                reason = None
            elif outcome == "sample-limit":
                samples.extend([{"type": "animation-frame", "event": None}] * 127)
                reason, truncated = "sample-limit", True
            return {"sampleLimit": 128, "samples": samples, "stopReason": reason, "truncated": truncated}

    record = {}
    code = compile(ast.Module(body=selected, type_ignores=[]), "source-observation-success-gate", "exec")
    namespace = {"page": Page(), "record": record, "_capture_cold_gesture_observations": collector()}
    if outcome == "complete":
        exec(code, namespace)
        assert record["cold_gesture_observations"]["samples"][0]["type"] == "pointerdown"
    else:
        with pytest.raises(AssertionError):
            exec(code, namespace)
        if outcome == "missing":
            assert "cold_gesture_observation_failure" in record
        else:
            assert "cold_gesture_observations" in record, "Keep incomplete evidence for diagnosis"
