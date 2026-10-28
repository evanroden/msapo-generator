"""Synthetic-only reset admission; no browser launch or production namespace."""
import ast
from concurrent.futures import Future
from contextvars import copy_context
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app import monthly_report_testing as qa
from app import monthly_report_testing_ui as ui


@pytest.mark.parametrize("kind", ["ai", "preview"])
def test_readiness_uses_exact_active_future_guard_without_mutation(monkeypatch, tmp_path, kind):
    future = Future()
    key = "report_ai_job" if kind == "ai" else "report_ordered_previews"
    entry = {"future": future} if kind == "ai" else {"running": ("activity", "fingerprint", future)}
    state = {key: entry}
    monkeypatch.setattr(ui.st, "session_state", state)
    with qa.isolated("a" * 32):
        target = qa.data_dir(tmp_path)
        marker = target / qa._SENTINEL
        before = marker.read_bytes(), marker.stat().st_mtime_ns
        assert ui._reset_readiness(tmp_path) == "busy"
        assert ui._active_jobs()
        assert state == {key: entry} and not future.cancelled()
        future.set_result(None)
        assert ui._reset_readiness(tmp_path) == "ready"
        assert not ui._active_jobs()
        assert (marker.read_bytes(), marker.stat().st_mtime_ns) == before


def test_readiness_never_creates_unowned_storage_or_accepts_stale_lease(tmp_path):
    assert not qa.current_generation_matches(tmp_path)
    assert not list(tmp_path.iterdir())
    with qa.isolated("a" * 32):
        assert not qa.current_generation_matches(tmp_path)
        target = qa.data_dir(tmp_path)
        old_context = copy_context()
        old_generation = qa.generation()
        assert qa.current_generation_matches(tmp_path)
        qa.reset(tmp_path)
        assert not qa.current_generation_matches(tmp_path)
    with qa.isolated("a" * 32):
        qa.data_dir(tmp_path)
        assert qa.generation() != old_generation
        assert qa.current_generation_matches(tmp_path)
    assert not old_context.run(qa.current_generation_matches, tmp_path)
    assert target.exists()  # Readiness did not delete the replacement.


def test_ui_busy_guard_still_refuses_and_retains_fixture_then_idle_reset_acknowledges(monkeypatch, tmp_path):
    from test_monthly_report_qa_ui import visit
    app = visit(monkeypatch, tmp_path)
    next(x for x in app.button if x.label == "Load known-value report").click().run()
    prior = next(x.value for x in app.caption if x.value.startswith("QA fixture state:"))
    future = Future()
    app.session_state["report_test_ordered_previews"] = {"running": ("activity", "fp", future)}
    app.run()
    assert any('data-monthly-qa-reset-readiness="busy"' in x.proto.body for x in app.get("html"))
    next(x for x in app.button if x.label == "Reset this test only").click().run()
    assert not app.exception
    assert any("Test reset rejected:" in x.value for x in app.error)
    assert prior in [x.value for x in app.caption]
    assert "monthly_qa_reset_pending" not in app.session_state
    assert not any("QA reset acknowledged:" in x.value for x in app.caption)
    future.set_result(None)
    app.run()
    assert any('data-monthly-qa-reset-readiness="ready"' in x.proto.body for x in app.get("html"))
    next(x for x in app.button if x.label == "Reset this test only").click().run()
    assert not app.exception
    assert any("QA reset acknowledged: empty fixture" in x.value for x in app.caption)


@pytest.fixture
def harness(monkeypatch):
    # Compile the actual helper bodies without optional Playwright import or
    # launching browsers. All production logic below is tested, not copied.
    path = Path(__file__).parents[1] / "scripts/qa_monthly_live.py"
    tree = ast.parse(path.read_text())
    names = {"await_reset_admissible", "await_reset_transition", "reset_fixture"}
    module = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
    class Timeout(Exception):
        pass
    original = {"mode": "known-value prefill", "generation": "a" * 12, "revision": 1}
    current = dict(original)
    actions = []
    class Locator:
        first = property(lambda self: self)
        def __init__(self, text=""):
            self.text = text
        def click(self, **kwargs):
            actions.append("probe click" if self.text == "probe" else "reset click")
        def wait_for(self, **kwargs):
            pass
        def text_content(self):
            return self.text or "QA reset acknowledged: empty fixture · generation bbbbbbbbbbbb · action cccccccccccc"
        def count(self):
            return 0
    readiness = Locator("QA reset readiness: ready · generation " + original["generation"] + " · observation 111111111111")
    class Page:
        url = "https://example.test/?workflow=monthly&monthly_qa=isolated"
        def get_by_text(self, text, **kwargs):
            return readiness if isinstance(text, re.Pattern) and "readiness" in text.pattern else Locator()
        def get_by_role(self, *args, **kwargs):
            return Locator("probe" if kwargs.get("name") == "Check reset readiness" else "")
        def wait_for_timeout(self, delay):
            clock[0] += delay / 1000
            if busy_then_ready[0]:
                readiness.text = readiness.text.replace(": busy", ": ready")
        def wait_for_function(self, source, **kwargs):
            if "notRunning" in source:
                actions.append("observe script idle")
                return SimpleNamespace(json_value=lambda: True)
            if "receipts.length" in source:
                actions.append("observe readiness")
                args = kwargs["arg"]
                if copies[0] != 1 or stale[0]:
                    raise Timeout("ambiguous or stale receipt")
                if args["prior"] is not None:
                    if not fresh[0]:
                        raise Timeout("not fresh")
                    if replace_generation[0]:
                        current["generation"] = "f" * 12
                if args["prior"] is None and "probe click" in actions:
                    actions.append("confirm idle receipt")
                    if replace_observation[0]:
                        replace_observation[0] = False
                        return SimpleNamespace(json_value=lambda: {
                            "observation": "333333333333", "status": "ready"})
                return SimpleNamespace(json_value=lambda: {
                    "observation": "222222222222", "status": "busy" if ": busy" in readiness.text
                    else "unavailable" if ": unavailable" in readiness.text else "ready"})
            actions.append("observe transition")
            assert kwargs["timeout"] == 40000
            return SimpleNamespace(json_value=lambda: outcome[0])
    def expect(locator):
        def check(expected, **kwargs):
            actions.append("observe readiness" if locator is readiness else "observe build")
            assert kwargs["timeout"] <= 40000
            if locator is readiness and fresh[0]:
                locator.text = locator.text.replace("111111111111", "222222222222")
            if locator is readiness and replace_generation[0]:
                current["generation"] = "f" * 12
            if not (expected.fullmatch(locator.text) if isinstance(expected, re.Pattern) else locator.text == expected):
                raise Timeout("not ready")
        return SimpleNamespace(to_have_text=check)
    from scripts import qa_public_build
    monkeypatch.setattr(qa_public_build, "running_code_marker", lambda *args, **kwargs: Locator("Running code: " + "d" * 40))
    outcome = ["empty"]
    fresh = [True]
    clock = [1]
    busy_then_ready = [False]
    replace_observation = [False]
    copies = [1]
    stale = [False]
    replace_generation = [False]
    def state(page, mode, **kwargs):
        actions.append("observe state:" + mode)
        return ({"mode": "empty", "generation": "b" * 12, "revision": 0}
                if mode == "empty" else dict(current))
    env = dict(re=re, parse_qs=parse_qs, urlparse=urlparse, time=SimpleNamespace(monotonic=lambda: clock[0]),
               EXPECTED="d" * 40, URL="https://example.test", expect=expect, BrowserTimeout=Timeout,
               await_fixture_state=state, event=lambda *a, **k: None,
               state_diagnostics=lambda *a, **k: actions.append("diagnostics"))
    exec(compile(module, str(path), "exec"), env)
    return SimpleNamespace(env=env, page=Page(), original=original, current=current,
                           readiness=readiness, actions=actions, outcome=outcome, timeout=Timeout,
                           fresh=fresh, replace_generation=replace_generation, copies=copies, stale=stale, busy_then_ready=busy_then_ready, replace_observation=replace_observation)


def test_harness_never_clicks_reset_before_idle(harness):
    h = harness
    h.readiness.text = h.readiness.text.replace(": ready", ": busy")
    with pytest.raises(h.timeout):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


def test_harness_stale_idle_caption_cannot_authorize_reset(harness):
    h = harness
    h.fresh[0] = False
    with pytest.raises(h.timeout):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


def test_harness_generation_changed_during_idle_wait_cannot_reset(harness):
    h = harness
    h.replace_generation[0] = True
    with pytest.raises(AssertionError, match="changed while waiting"):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


def test_harness_matching_query_on_foreign_origin_cannot_reset(harness):
    h = harness
    h.page.url = "https://other.example/?workflow=monthly&monthly_qa=isolated"
    with pytest.raises(AssertionError, match="isolated synthetic route"):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


def test_harness_one_native_reset_after_idle_keeps_strict_ack(harness):
    h = harness
    result = h.env["reset_fixture"](h.page, h.original, "test")
    assert result["generation"] == "b" * 12
    assert h.actions.count("reset click") == 1
    assert h.actions.index("observe readiness") < h.actions.index("reset click")


def test_harness_rejected_click_fails_before_waiting_for_an_accepted_state(harness):
    h = harness
    h.outcome[0] = "rejected"
    with pytest.raises(AssertionError, match="explicitly refused"):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert h.actions.count("reset click") == 1
    assert "observe state:empty" not in h.actions
    assert "diagnostics" in h.actions


def test_harness_changed_owner_generation_or_route_cannot_reset(harness):
    h = harness
    h.current["generation"] = "e" * 12
    with pytest.raises(AssertionError, match="another fixture generation"):
        h.env["reset_fixture"](h.page, h.original, "test")
    h.page.url = "https://example.test/?workflow=monthly"
    with pytest.raises(AssertionError, match="isolated synthetic route"):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


@pytest.mark.parametrize("copies,stale", [(2, False), (1, True), (3, True)])
def test_harness_duplicate_or_stale_receipts_never_reset(harness, copies, stale):
    h = harness
    h.copies[0], h.stale[0] = copies, stale
    with pytest.raises(h.timeout):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert "reset click" not in h.actions


def test_metadata_has_no_visible_nonce_or_layout_footprint():
    import inspect
    source = inspect.getsource(ui._render_reset_readiness)
    assert "st.caption" not in source
    assert 'hidden aria-hidden="true"' in source
    assert "{display:none!important}" in source
    assert '[data-testid="stElementContainer"]:has(' in source


def test_actual_browser_predicate_rejects_duplicates_stale_busy_and_old_observations():
    import json
    import subprocess
    source = ast.parse((Path(__file__).parents[1] / "scripts/qa_monthly_live.py").read_text())
    fn = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "await_reset_admissible")
    assignment = next(n for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id == "receipt_predicate" for t in n.targets))
    predicate = ast.literal_eval(assignment.value)
    script = """
    const assert = require('node:assert/strict');
    const test = PREDICATE;
    let nodes = [];
    global.document = {querySelectorAll: () => nodes};
    const node = (status='ready', stale=false, generation='aaaaaaaaaaaa', observation='222222222222') =>
      ({dataset: {monthlyQaResetReadiness:status,generation,observation},
        closest: () => stale ? {} : null});
    const args = {generation:'aaaaaaaaaaaa',prior:'111111111111'};
    nodes=[node('ready',true),node('busy')]; assert.equal(test(args),false);
    nodes=[node(),node()]; for(let i=0;i<100;i++) assert.equal(test(args),false);
    nodes=[node('ready',true)]; assert.equal(test(args),false);
    nodes=[node('busy')]; assert.equal(test(args).status,'busy');
    nodes=[node('ready',false,'bbbbbbbbbbbb')]; assert.equal(test(args),false);
    nodes=[node('ready',false,'aaaaaaaaaaaa','111111111111')]; assert.equal(test(args),false);
    nodes=[node()]; assert.deepEqual(test(args),{observation:'222222222222',status:'ready'});
    nodes=[node('busy')]; assert.equal(test({...args,prior:null}).observation,'222222222222');
    """
    subprocess.run(["node", "-e", script.replace("PREDICATE", predicate)], check=True)


def test_readiness_diagnostics_allowlist_invalid_values_and_bounded_duplicates():
    import subprocess
    path = Path(__file__).parents[1] / "scripts/qa_monthly_live.py"
    tree = ast.parse(path.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "reset_readiness_diagnostics")
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call) and
                isinstance(n.func, ast.Attribute) and n.func.attr == "evaluate")
    predicate = ast.literal_eval(call.args[0])
    script = """
    const assert = require('node:assert/strict');
    const snapshot = PREDICATE;
    const secret = 'private-cookie-and-full-lease-0123456789abcdef';
    const node = (status, stale, generation, observation) => ({
      dataset:{monthlyQaResetReadiness:status,generation,observation,cookie:secret},
      innerHTML:secret, textContent:secret, closest:()=>stale?{}:null
    });
    let nodes=[node('ready',true,'aaaaaaaaaaaa','bbbbbbbbbbbb'),
               node('busy',false,'cccccccccccc','dddddddddddd'),
               node(secret,false,secret,secret),node('unavailable',false,'aaaaaaaaaaaa','eeeeeeeeeeee')];
    global.document={querySelectorAll:()=>nodes};
    let result=snapshot();
    assert.equal(result.receipt_count,4);
    assert.deepEqual(result.receipts[0],{stale:true,status:'ready',generation:'aaaaaaaaaaaa',observation:'bbbbbbbbbbbb'});
    assert.equal(result.receipts[1].status,'busy');
    assert.deepEqual(result.receipts[2],{stale:false,status:'invalid',generation:null,observation:null});
    assert.equal(result.receipts[3].status,'unavailable');
    assert.equal(JSON.stringify(result).includes(secret),false);
    const invalid=nodes[2];
    nodes=[node('ready',false,'aaaaaaaaaaaa' + String.fromCharCode(10),'b'.repeat(32))];
    result=snapshot(); assert.equal(result.receipts[0].generation,null);assert.equal(result.receipts[0].observation,null);
    nodes=Array(100).fill(invalid);
    result=snapshot();assert.equal(result.receipt_count,100);assert.equal(result.receipts.length,8);
    """
    subprocess.run(["node", "-e", script.replace("PREDICATE", predicate)], check=True)
    env = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), env)
    class BrokenPage:
        def evaluate(self, source):
            raise RuntimeError("private-cookie-should-never-escape")
    assert env["reset_readiness_diagnostics"](BrokenPage()) == {"unavailable": True}
    diagnostics = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "state_diagnostics")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and
               n.func.id == "reset_readiness_diagnostics" for n in ast.walk(diagnostics))


def test_probe_busy_then_idle_uses_native_actions_and_one_reset(harness):
    h = harness
    h.readiness.text = h.readiness.text.replace(": ready", ": busy")
    h.busy_then_ready[0] = True
    h.env["reset_fixture"](h.page, h.original, "test")
    assert h.actions.count("probe click") == 2
    assert h.actions.count("reset click") == 1
    assert h.actions.index("observe script idle") < h.actions.index("probe click")


def test_unavailable_probe_never_resets(harness):
    h = harness
    h.readiness.text = h.readiness.text.replace(": ready", ": unavailable")
    with pytest.raises(AssertionError, match="unavailable"):
        h.env["reset_fixture"](h.page, h.original, "test")
    assert h.actions.count("probe click") == 1
    assert "reset click" not in h.actions


def test_ordinary_readiness_render_never_schedules_automatic_reruns():
    import inspect
    source = inspect.getsource(ui._render_reset_readiness)
    assert "@st.fragment" in source
    assert "run_every" not in source
    assert "st.rerun" not in source
    assert 'st.button("Check reset readiness", key="monthly_qa_reset_probe")' in source


def test_real_probe_protocol_never_emits_auto_rerun_and_preserves_namespace(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from streamlit.runtime.scriptrunner_utils.script_run_context import ScriptRunContext
    messages = []
    enqueue = ScriptRunContext.enqueue
    def capture(self, message):
        messages.append(message.WhichOneof("type"))
        return enqueue(self, message)
    monkeypatch.setattr(ScriptRunContext, "enqueue", capture)
    source = """from pathlib import Path
import streamlit as st
from app import monthly_report_testing as qa
from app.monthly_report_testing_ui import _render_reset_readiness
with qa.isolated("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"):
    base = Path(st.session_state["_base"])
    qa.data_dir(base)
    _render_reset_readiness(base)
"""
    app = AppTest.from_string(source, default_timeout=10)
    app.session_state["_base"] = str(tmp_path)
    app.run()
    assert not app.exception
    def receipt():
        return next(x.proto.body for x in app.get("html") if "data-monthly-qa-reset-readiness" in x.proto.body)
    before = receipt()
    files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    next(x for x in app.button if x.label == "Check reset readiness").click().run()
    assert not app.exception
    after = receipt()
    assert re.search('data-generation="([^"]+)"', before)[1] == re.search('data-generation="([^"]+)"', after)[1]
    assert re.search('data-observation="([^"]+)"', before)[1] != re.search('data-observation="([^"]+)"', after)[1]
    assert files == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert "auto_rerun" not in messages


def test_ready_probe_finishes_before_reset_and_exact_observation_is_rechecked(harness):
    h = harness
    h.env["reset_fixture"](h.page, h.original, "test")
    probe = h.actions.index("probe click")
    confirm = h.actions.index("confirm idle receipt")
    reset = h.actions.index("reset click")
    assert "observe script idle" in h.actions[probe + 1:confirm]
    assert probe < confirm < reset
    assert h.actions.count("reset click") == 1


def test_replaced_ready_observation_requires_another_native_probe(harness):
    h = harness
    h.replace_observation[0] = True
    h.env["reset_fixture"](h.page, h.original, "test")
    assert h.actions.count("probe click") == 2
    assert h.actions.count("confirm idle receipt") == 2
    assert h.actions.count("reset click") == 1
    assert h.actions.index("reset click") > max(i for i, x in enumerate(h.actions) if x == "confirm idle receipt")
