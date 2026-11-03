"""PO evidence is bounded/passive and cannot replace the native gate outcome."""
import ast
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace

import pytest

from scripts import qa_po_diagnostics as diagnostics


class Trace:
    def __init__(self, raw=b"synthetic trace", fail=None):
        self.raw, self.fail = raw, fail
        self.calls = []

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        if self.fail == "start":
            raise RuntimeError("synthetic trace start failure")

    def stop(self, *, path):
        self.calls.append(("stop", path))
        if self.fail == "stop":
            raise RuntimeError("synthetic trace stop failure")
        Path(path).write_bytes(self.raw)
        if self.fail == "stop_after_write":
            raise RuntimeError("synthetic trace stop failure after partial ZIP export")


class Page:
    def __init__(self, trace=None):
        self.context = SimpleNamespace(tracing=trace or Trace())
        self.handlers = {}
        self.evaluations = []

    def on(self, kind, handler):
        self.handlers[kind] = handler

    def evaluate(self, script):
        self.evaluations.append(script)
        return {"scriptState": "notRunning", "panels": [{"state": {"requestFailed": True}}]}


def test_passive_events_keep_module_url_status_and_errors_without_payloads(tmp_path):
    page = Page()
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    observer.start(page)
    assert page.context.tracing.calls[0] == ("start", {
        "screenshots": False, "snapshots": False, "sources": False})
    page.handlers["console"](SimpleNamespace(type="error", text="Import failed", location={
        "url": "http://127.0.0.1:8519/static/js/DownloadButton.hash.js?secret=omit#fragment", "lineNumber": 7}))
    page.handlers["pageerror"](ValueError("synthetic module failure"))
    page.handlers["requestfailed"](SimpleNamespace(url="blob:synthetic-local-bytes", resource_type="script", failure="cancelled"))
    page.handlers["response"](SimpleNamespace(url="http://127.0.0.1:8519/static/js/DownloadButton.hash.js?token=omit",
        request=SimpleNamespace(resource_type="script"), status=404, headers={"content-type": "text/html"}))
    observer.close()
    rows = [json.loads(line) for line in (tmp_path / "webkit-events.jsonl").read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["console", "pageerror", "requestfailed", "response"]
    assert rows[0]["detail"]["url"] == "http://127.0.0.1:8519/static/js/DownloadButton.hash.js"
    assert rows[2]["detail"]["url"] == "blob:[local bytes omitted]"
    assert rows[3]["detail"]["status"] == 404 and rows[3]["detail"]["content_type"] == "text/html"
    assert not page.evaluations


def test_event_count_and_bytes_are_bounded_and_failure_snapshot_has_own_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_EVENTS", 2)
    monkeypatch.setattr(diagnostics, "MAX_EVENT_BYTES", 200)
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    page = Page()
    observer.start(page)
    for _ in range(10):
        observer.record("synthetic", "x" * 20)
    observer.failure_snapshot(page)
    observer.close()
    summary = json.loads((tmp_path / "webkit-summary.json").read_text())
    assert summary["events"] <= 2 and summary["event_bytes"] <= 200 and summary["dropped"] >= 8
    assert (tmp_path / "webkit-events.jsonl").stat().st_size <= 200
    assert summary["snapshot"]["staged"] is True
    assert json.loads((tmp_path / "webkit-first-failure.json").read_text())["panels"][0]["state"]["requestFailed"]


@pytest.mark.parametrize("size,staged", [(8, True), (9, False)])
def test_trace_is_exported_outside_artifacts_and_only_staged_under_cap(tmp_path, monkeypatch, size, staged):
    monkeypatch.setattr(diagnostics, "MAX_TRACE_BYTES", 8)
    trace = Trace(b"x" * size)
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    observer.start(Page(trace))
    temp = Path(observer.temp.name)
    assert not temp.is_relative_to(tmp_path)
    observer.close()
    assert not temp.exists()
    summary = json.loads((tmp_path / "webkit-summary.json").read_text())
    assert summary["trace"]["staged"] is staged
    assert (tmp_path / "webkit-trace.zip").exists() is staged


@pytest.mark.parametrize("failure", ["start", "stop"])
def test_trace_failure_does_not_raise_or_prevent_evidence_cleanup(tmp_path, failure):
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    observer.start(Page(Trace(fail=failure)))
    temp = Path(observer.temp.name)
    observer.close()
    assert not temp.exists()
    summary = json.loads((tmp_path / "webkit-summary.json").read_text())
    assert summary["diagnostic_errors"] and summary["trace"]["staged"] is False


def test_partial_trace_export_then_failure_never_stages_a_zip(tmp_path):
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    observer.start(Page(Trace(fail="stop_after_write")))
    temp = Path(observer.temp.name)
    observer.close()
    assert not temp.exists() and not (tmp_path / "webkit-trace.zip").exists()
    summary = json.loads((tmp_path / "webkit-summary.json").read_text())
    assert summary["trace"]["staged"] is False
    assert summary["diagnostic_errors"][0]["stage"] == "trace-stop"


def test_failed_temp_cleanup_still_closes_event_log_and_writes_summary(tmp_path, monkeypatch):
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    observer.start(Page())
    cleanup = observer.temp.cleanup
    def fail_cleanup():
        raise OSError("synthetic temporary-file cleanup failure")
    monkeypatch.setattr(observer.temp, "cleanup", fail_cleanup)
    try:
        observer.close()
        assert observer.log.closed
        summary = json.loads((tmp_path / "webkit-summary.json").read_text())
        assert summary["diagnostic_errors"][0]["stage"] == "trace-cleanup"
    finally:
        cleanup()


def test_malformed_callback_and_failed_snapshot_are_diagnostic_only(tmp_path):
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    page = Page()
    observer.start(page)
    page.handlers["response"](object())
    observer.failure_snapshot(object())
    observer.close()
    summary = json.loads((tmp_path / "webkit-summary.json").read_text())
    assert {item["stage"] for item in summary["diagnostic_errors"]} == {"response", "first-failure"}


def test_oversized_snapshot_is_not_staged_or_truncated(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_SNAPSHOT_BYTES", 1)
    observer = diagnostics.PODiagnostics(tmp_path, "webkit")
    page = Page()
    observer.start(page)
    observer.failure_snapshot(page)
    observer.close()
    assert not (tmp_path / "webkit-first-failure.json").exists()
    assert json.loads((tmp_path / "webkit-summary.json").read_text())["snapshot"]["staged"] is False


def test_failure_retains_original_exception_screenshot_and_browser_close(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "scripts/qa_po_adaptive.py"
    tree = ast.parse(source.read_text())
    exercise = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "exercise")
    events = []
    original = RuntimeError("native gate failure remains authoritative")
    class Observer:
        def __init__(self, *args): pass
        def start(self, page): events.append("start")
        def failure_snapshot(self, page): events.append("snapshot")
        def close(self): events.append("diagnostics-close")
    monkeypatch.setitem(sys.modules, "qa_po_diagnostics", SimpleNamespace(PODiagnostics=Observer))
    page = SimpleNamespace(on=lambda *args: None, screenshot=lambda **kwargs: events.append("screenshot"))
    browser = SimpleNamespace(new_page=lambda **kwargs: page, close=lambda: events.append("browser-close"))
    engine = SimpleNamespace(launch=lambda **kwargs: browser)
    def fail(*args): raise original
    namespace = {"OUT": tmp_path, "exercise_page": fail}
    exec(compile(ast.Module(body=[exercise], type_ignores=[]), str(source), "exec"), namespace)
    with pytest.raises(RuntimeError) as caught:
        namespace["exercise"](engine, "webkit")
    assert caught.value is original
    assert events == ["start", "snapshot", "screenshot", "diagnostics-close", "browser-close"]


def test_snapshot_is_observational_and_existing_image_wait_has_no_extension():
    assert all(token not in diagnostics.SNAPSHOT for token in (
        "scrollIntoView", "dispatchEvent", "setStateValue", ".click(", ".focus(", "setTimeout", "requestAnimationFrame"))
    source = (Path(__file__).resolve().parents[1] / "scripts/qa_po_adaptive.py").read_text()
    assert "package.locator('img[alt^=\"Generated MSAPO — page \"]').first.wait_for()" in source
    exercise = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "exercise_page")
    assert not any(isinstance(node, ast.Name) and node.id == "diagnostics" for node in ast.walk(exercise))


def test_first_failure_observer_reads_the_real_shadow_root_preview_state():
    script = r"""
const box={toJSON:()=>({x:16,y:560,width:640,height:780})};
const root={dataset:{epcMode:'wide',epcFullRender:'same-render'}};
const panel={matches:s=>s==='.report-preview',getBoundingClientRect:()=>box,
  _previewState:{requestFailed:true,requestAttempts:3,sent:'native-view-request'},
  querySelector:s=>({textContent:s.includes('status')?'Preview request interrupted — retry.':'—'}),
  querySelectorAll:()=>[]};
const host={matches:()=>false,shadowRoot:{querySelectorAll:()=>[panel]}};
const pair={matches:()=>false,dataset:{},closest:()=>root,getBoundingClientRect:()=>box,
  querySelectorAll:()=>[host],querySelector:()=>({getBoundingClientRect:()=>box})};
global.document={querySelector:s=>s.includes('purchase_package')?pair:{getAttribute:()=> 'notRunning'},
  querySelectorAll:()=>[pair,host]};
global.getComputedStyle=()=>({display:'flex',visibility:'visible'});
console.log(JSON.stringify(eval('('+process.argv[1]+')')()));
"""
    result = subprocess.run(["node", "-e", script, diagnostics.SNAPSHOT], capture_output=True,
                            text=True, check=True, timeout=5)
    observed = json.loads(result.stdout)
    panel, = observed["panels"]
    assert panel["state"]["requestFailed"] is True and panel["state"]["requestAttempts"] == 3
    assert observed["scriptState"] == "notRunning" and panel["display"] == "flex"
