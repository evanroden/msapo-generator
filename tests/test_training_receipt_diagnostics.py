"""Diagnostic-only Training poll observation must not change native acceptance."""
import ast
import json
from pathlib import Path
import subprocess
import types
import tempfile

import pytest

SOURCE = Path(__file__).parents[1] / "scripts/qa_training_source_review.py"


def functions():
    tree = ast.parse(SOURCE.read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name in {"observed_receipt_predicate", "stop_initial_trace"}]
    scope = {"tempfile": tempfile, "Path": Path}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), scope)
    return scope


def node(code):
    result = subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_predicate_results_errors_and_diagnostic_failure_are_preserved():
    wrapper = functions()["observed_receipt_predicate"]
    for value in ("true", "false", "0", "null", "'unchanged'"):
        script = "const f=" + wrapper("payload => " + value) + ";"
        assert node(script + "console.log(JSON.stringify(f({})));") == node(
            "console.log(JSON.stringify(" + value + "));")
    for thrown in ("new Error('original')", "null", "false"):
        script = "const sentinel=" + thrown + ";const f=" + wrapper("() => {throw sentinel}") + ";"
        assert node(script + "try{f({});}catch(e){console.log(JSON.stringify(e===sentinel));}") is True


def test_poll_records_have_bounded_transitions_no_content_and_no_timers():
    wrapper = functions()["observed_receipt_predicate"]("payload => false")
    script = """
    let ms=0, state='running';
    globalThis.performance={now:()=>++ms};
    globalThis.document={body:{innerText:'QA ' + JSON.stringify({reviews:0,tables:[],saved_revision:0,review_revision:'same',secret:'NEVER_CAPTURE'})},
      visibilityState:'visible', readyState:'complete',
      querySelector:()=>({getAttribute:()=>state})};
    const payload={prefix:'QA ',wanted:{reviews:0,included:false,saved:null,previous:null}};
    """ + "const f=" + wrapper + """;
    for(let i=0;i<200;i++){state=i%2?'notRunning':'running';f(payload);}
    const o=globalThis.__qaTrainingReceiptObservation;
    console.log(JSON.stringify({count:o.count, length:o.transitions.length, dropped:o.dropped,
      last:o.last, serialized:JSON.stringify({transitions:o.transitions,last:o.last})}));
    """
    result = node(script)
    assert result["count"] == 200 and result["length"] == 64 and result["dropped"] == 136
    assert result["last"]["includedMatch"] is True
    assert "NEVER_CAPTURE" not in result["serialized"]
    for forbidden in ("setTimeout", "requestAnimationFrame", "MutationObserver", ".click(", ".scroll"):
        assert forbidden not in wrapper


def test_original_predicate_and_budgets_remain_strict():
    tree = ast.parse(SOURCE.read_text())
    receipt = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "receipt")
    predicate = next(n.value.value for n in receipt.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "predicate" for t in n.targets))
    assert "body?.innerText" in predicate
    assert "wanted.included" in predicate and "wanted.previous" in predicate
    assert "==='notRunning'" in predicate
    waits = [n for n in ast.walk(receipt) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "wait_for_function"]
    assert len(waits) == 1
    assert {k.arg: ast.literal_eval(k.value) for k in waits[0].keywords if k.arg == "timeout"} == {"timeout": 30000}
    assert not any(k.arg == "polling" for k in waits[0].keywords)


@pytest.mark.parametrize("failed", [True, False])
def test_trace_failure_does_not_mask_native_failure(tmp_path, failed):
    def stop(**kwargs):
        raise OSError("trace unavailable")
    context = types.SimpleNamespace(tracing=types.SimpleNamespace(stop=stop))
    evidence = {}
    stop_trace = functions()["stop_initial_trace"]
    if failed:
        stop_trace(context, tmp_path, evidence, failed=True)
    else:
        with pytest.raises(OSError):
            stop_trace(context, tmp_path, evidence, failed=False)
    assert evidence["initial_trace"] == {"retained": False, "error_type": "OSError"}


@pytest.mark.parametrize("size,retained", [(100, True), (16 * 1024 * 1024 + 1, False)])
def test_retained_trace_size_cap(tmp_path, size, retained):
    def stop(*, path):
        with open(path, "wb") as handle:
            handle.truncate(size)
    context = types.SimpleNamespace(tracing=types.SimpleNamespace(stop=stop))
    evidence = {}
    functions()["stop_initial_trace"](context, tmp_path, evidence, failed=False)
    assert evidence["initial_trace"]["retained"] is retained
    assert (tmp_path / "initial-receipt-trace.zip").exists() is retained


def test_partial_failed_trace_never_enters_artifact_directory(tmp_path):
    exported = []
    def stop(*, path):
        exported.append(Path(path))
        with open(path, "wb") as handle:
            handle.truncate(16 * 1024 * 1024 + 1)
        raise OSError("partial export")
    context = types.SimpleNamespace(tracing=types.SimpleNamespace(stop=stop))
    evidence = {}
    functions()["stop_initial_trace"](context, tmp_path, evidence, failed=True)
    assert list(tmp_path.iterdir()) == []
    assert not exported[0].exists()
    assert evidence["initial_trace"] == {"retained": False, "error_type": "OSError"}
