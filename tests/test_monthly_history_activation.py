"""Cold native History still acts once; mounted previews retain the commit gate."""
import ast
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "scripts/qa_monthly_history.py"


def functions(namespace):
    tree = ast.parse(SOURCE.read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in {"set_history", "assert_history_coverage"}]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
    return SimpleNamespace(**namespace)


def activation(*, viewers=0, installed=False, pending=None, block_all=None, trusted=True):
    # Deliberately disagree with click: only the actual event decides whether
    # viewers/gate were present, not an earlier diagnostic installation sample.
    return {"before": {"viewers": 1 if viewers == 0 else 0, "installed": not installed},
            "click": {"viewers": viewers, "installed": installed, "pending": pending,
                      "blockAll": block_all, "trusted": trusted}}


def exercise(observation, *, opened=True, blocked=None):
    calls, activations = [], []
    page, panel, summary, control = (Mock() for _ in range(4))
    panel.evaluate.side_effect = lambda _: not opened
    panel.locator.return_value.first = summary
    panel.get_by_role.side_effect = lambda role, name, exact: control
    summary.evaluate.side_effect = lambda _: calls.append("observe")
    summary.click.side_effect = lambda: calls.append("click")
    page.evaluate.side_effect = lambda _: observation

    def receipt(actual_page):
        assert actual_page is page
        calls.append("read receipt")
        return {"sequence": 7}

    def await_state(actual_page, identity, *, after):
        assert actual_page is page and identity == "isolated-history" and after == 7
        calls.append("fresh durable receipt")
        if blocked == "receipt":
            raise AssertionError("fresh receipt failed")

    class Expect:
        def to_have_count(self, count):
            assert count == (1 if opened else 0)
            calls.append("Inspect count")
            if blocked == "count":
                raise AssertionError("Inspect count failed")
        def to_be_visible(self):
            calls.append("Inspect visible")
            if blocked == "visible":
                raise AssertionError("Inspect visible failed")

    def expect(locator):
        assert locator is control
        return Expect()

    helpers = functions({"history": lambda _: panel, "receipt": receipt,
                         "await_state": await_state, "expect": expect})
    error = None
    try:
        assert helpers.set_history(page, opened, "isolated-history", activations) is panel
    except AssertionError as exc:
        error = exc
    assert summary.click.call_count == 1
    assert calls[:3] == ["read receipt", "observe", "click"]
    assert activations == [{"opening": opened, "sequence_before": 7, **observation}]
    return calls, error


@pytest.mark.parametrize("opened", [True, False])
def test_cold_native_click_without_viewer_or_gate_reaches_existing_outcome_assertions(opened):
    calls, error = exercise(activation(), opened=opened)
    assert error is None
    assert calls == ["read receipt", "observe", "click", "fresh durable receipt", "Inspect count"] + (
        ["Inspect visible"] if opened else [])


@pytest.mark.parametrize("viewers", [0, 2])
def test_existing_gate_must_protect_even_when_preview_dom_has_unmounted(viewers):
    calls, error = exercise(activation(viewers=viewers, installed=True, pending=True, block_all=True))
    assert error is None and calls[-1] == "Inspect visible"


@pytest.mark.parametrize("values", [
    {"viewers": 2},
    {"viewers": 2, "installed": True, "pending": False, "block_all": True},
    {"viewers": 2, "installed": True, "pending": True, "block_all": False},
    {"viewers": 0, "installed": True, "pending": False, "block_all": True},
    {"viewers": 0, "installed": True, "pending": True, "block_all": False},
])
def test_missing_or_unprotected_live_gate_still_fails_first_action(values):
    calls, error = exercise(activation(**values))
    assert error is not None and "protect its actual native full rerun" in str(error)
    assert calls == ["read receipt", "observe", "click"]


def test_untrusted_cold_click_still_fails():
    calls, error = exercise(activation(trusted=False))
    assert error is not None and calls == ["read receipt", "observe", "click"]


@pytest.mark.parametrize("blocked", ["receipt", "count", "visible"])
def test_cold_exemption_does_not_hide_failed_native_outcome_or_retry(blocked):
    calls, error = exercise(activation(), blocked=blocked)
    assert error is not None and "failed" in str(error)
    assert calls.count("click") == 1


@pytest.mark.parametrize("viewer_open,viewer_close", [(False, False), (True, False), (False, True)])
def test_full_journey_cannot_pass_without_viewer_present_opening_and_closing(viewer_open, viewer_close):
    records = [{"opening": opened, "click": {"viewers": int(present)}}
               for opened, present in [(True, viewer_open), (False, viewer_close)]]
    with pytest.raises(AssertionError, match="both opening and closing with mounted previews"):
        functions({}).assert_history_coverage(records)


def test_full_journey_accepts_both_viewer_directions_plus_cold_reload():
    records = [{"opening": opened, "click": {"viewers": count}}
               for opened, count in [(True, 13), (False, 13), (True, 0)]]
    functions({}).assert_history_coverage(records)


def test_observation_counts_viewers_again_at_actual_native_click_without_writing_state():
    tree = ast.parse(SOURCE.read_text())
    observe = next(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                   and isinstance(node.value, str) and "const observation={before:snapshot(),click:null}" in node.value)
    script = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const source=JSON.parse(require('node:fs').readFileSync(0,'utf8'));
let viewers=0,click;
// Real v2 viewer markup is in an open shadow root, not the app light DOM.
const surface={querySelectorAll:selector=>selector==='.report-preview'?Array(viewers).fill({}):[]};
const innerHost={shadowRoot:surface};
const outerShadow={querySelectorAll:selector=>selector==='*'?[innerHost]:[]};
const host={shadowRoot:outerShadow};
const app={querySelectorAll:selector=>selector==='*'?[host]:[]};
const node={parentElement:app,classList:['st-key-synthetic_history_open'],closest:selector=>{
 assert.equal(selector,'[data-testid="stApp"]');return app;},
 addEventListener:(type,listener,options)=>{assert.equal(type,'click');assert.equal(options.capture,true);
 assert.equal(options.once,true);click=listener;}};
const window={__enfraPreviewNativeEditGates:new WeakMap()};
const observe=vm.runInNewContext('('+source+')',{window});
observe(node);
assert.equal(window.__enfraHistoryDisclosureObservation.before.viewers,0);
assert.equal(window.__enfraHistoryDisclosureObservation.before.installed,false);
viewers=2;
const gate={pending:true,blockAll:true,before:'one',workspace:{dataset:{epcFullRender:'one'}}};
window.__enfraPreviewNativeEditGates.set(app,gate);
click({isTrusted:true});
const observed=window.__enfraHistoryDisclosureObservation.click;
assert.equal(observed.viewers,2);assert.equal(observed.installed,true);
assert.equal(observed.trusted,true);assert.equal(observed.pending,true);assert.equal(observed.blockAll,true);
assert.deepEqual(gate,{pending:true,blockAll:true,before:'one',workspace:{dataset:{epcFullRender:'one'}}});
// Missing DOM does not hide an existing gate in the actual-click snapshot.
observe(node);viewers=0;click({isTrusted:true});
assert.equal(window.__enfraHistoryDisclosureObservation.click.viewers,0);
assert.equal(window.__enfraHistoryDisclosureObservation.click.installed,true);
'''
    import json
    subprocess.run(["node", "-e", script], input=json.dumps(observe), text=True,
                   capture_output=True, timeout=10, check=True)
