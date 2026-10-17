"""The browser receipt predicate must not depend on optional/null serialization."""
import json
import re
import subprocess
from pathlib import Path

import pytest


def expression():
    import ast
    source = Path(__file__).resolve().parents[1] / "scripts/qa_water_page_journey.py"
    tree = ast.parse(source.read_text())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "wait_pages")
    call = fn.body[0].value
    return ast.literal_eval(call.args[0])


def run_predicate(state, wanted, running="notRunning"):
    js = """const state = JSON.parse(process.argv[1]);
const wanted = JSON.parse(process.argv[2]);
const document = {querySelectorAll:()=>[{dataset:{enfraWaterReceipt:JSON.stringify(state)}}],
querySelector:()=>({getAttribute:()=>process.argv[3]})};
const predicate = eval('(' + process.argv[4] + ')');
console.log(JSON.stringify(predicate(wanted)));"""
    result = subprocess.run(["node", "-e", js, json.dumps(state), json.dumps(wanted), running, expression()],
        capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def state():
    part={"pages": [], "pending": [], "sources": []}
    return {"working":part,"durable":part,"working_fingerprint":"current","durable_fingerprint":"current"}


def test_initial_receipt_matches_with_an_explicit_optional_check_flag():
    assert run_predicate(state(), {"order":[], "check_pending":False, "pending":[]})


def test_pending_review_requires_the_exact_indexes():
    data=state()
    data["working"]["pending"]=[0]
    assert run_predicate(data, {"order":[], "check_pending":True, "pending":[0]})
    assert not run_predicate(data, {"order":[], "check_pending":True, "pending":[]})


def test_wrong_durable_version_or_running_app_cannot_acknowledge_pages():
    data=state()
    wanted={"order":[], "check_pending":False, "pending":[]}
    assert not run_predicate(data,wanted,"running")
    data["durable_fingerprint"]="older"
    assert not run_predicate(data,wanted)


def test_order_and_page_identity_are_exact():
    data=state()
    data["working"]["pages"]=[{"source_pages":[["source",2]]},{"source_pages":[["source",1]]}]
    assert run_predicate(data,{"order":[2,1],"check_pending":True,"pending":[]})
    assert not run_predicate(data,{"order":[1,2],"check_pending":True,"pending":[]})
    data["working"]["pages"][0]["source_pages"].append(["other",2])
    assert not run_predicate(data,{"order":[2,1],"check_pending":True,"pending":[]})


def test_first_page_decision_requires_its_own_durable_acknowledgment():
    data=state()
    wanted={"order":[],"check_pending":False,"check_reviewed":True,"reviewed":[1]}
    assert not run_predicate(data,wanted)
    data["working"]["sources"]=[{"reviewed":[]}]
    assert not run_predicate(data,wanted)
    data["working"]["sources"][0]["reviewed"]=[1]
    assert run_predicate(data,wanted)
    data["durable"]={**data["working"],"sources":[{"reviewed":[]}]}
    assert not run_predicate(data,wanted)


def cold_open():
    import ast
    source = Path(__file__).resolve().parents[1] / "scripts/qa_water_page_journey.py"
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "open_water_with_cold_tables")

    def saved_pages(page, order, *, pending):
        assert order == [2, 1] and pending == []
        assert page.navigations == 1
        return page.saved

    namespace = {"re": re, "WATER": ".water", "wait_pages": saved_pages}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[function.name]


class ColdPage:
    """Model only the harness contract; real browser coverage remains in CI."""
    def __init__(self, *, prior_url="about:blank", shift=0, count=3, no_request=False,
                 scroll_shift=0, render_changed=False, initial_button_y=298):
        from types import SimpleNamespace
        self.url, self.shift, self.count = prior_url, shift, count
        self.scroll_shift, self.render_changed = scroll_shift, render_changed
        self.initial_button_y = initial_button_y
        self.no_request = no_request
        self.saved = {"working_fingerprint": "from UI", "durable_fingerprint": "from UI"}
        self.navigations = self.releases = 0
        self.handler = None
        self.waiting = False
        self.request = SimpleNamespace(url="http://127.0.0.1:8520/static/js/DataFrame.real.js")

    def route(self, pattern, handler):
        assert pattern.fullmatch(self.request.url)
        self.handler = handler

    def unroute(self, pattern, handler):
        assert self.handler is handler
        self.handler = None

    def expect_request(self, pattern, *, timeout):
        from contextlib import contextmanager
        assert timeout == 20000 and pattern.fullmatch(self.request.url)

        @contextmanager
        def expected():
            self.waiting = True
            yield
            if self.no_request:
                raise TimeoutError("Real module request never arrived")
        return expected()

    def goto(self, url, *, wait_until):
        assert self.waiting and url == "http://127.0.0.1:8520"
        assert wait_until == "domcontentloaded" and self.url == "about:blank"
        self.navigations += 1
        self.url = url
        if not self.no_request:
            self.handler(self)

    def continue_(self):
        self.releases += 1

    def evaluate(self, sample, wanted):
        assert wanted["water"] == ".water"
        mounted = self.releases > 0
        return {"button": {"x": 16, "y": self.initial_button_y + (self.shift if mounted else 0),
                           "width": 114, "height": 44},
                "viewport": {"width": 545, "height": 757},
                "scrollTop": 6484 + (self.scroll_shift if mounted else 0),
                "fullRender": "changed" if mounted and self.render_changed else "same render",
                "grids": [{"key": "st-key-grid" + str(i), "height": 184 - 35 * i,
                           "loading": not mounted, "mounted": mounted} for i in range(self.count)]}

    def wait_for_function(self, script, *, arg, timeout):
        assert self.releases == 1 and timeout == 20000
        assert arg == ["st-key-grid" + str(i) for i in range(3)]


def cold_qa():
    from types import SimpleNamespace
    return SimpleNamespace(URL="http://127.0.0.1:8520", scroll_pair=lambda *a, **k: None,
                           frames=lambda page: None)


def test_cold_check_starts_unused_and_requires_the_actual_module_before_release():
    page, observations = ColdPage(), {}
    assert cold_open()(page, cold_qa(), observations) == page.saved
    assert page.navigations == page.releases == 1 and page.handler is None
    proof = observations["cold_table_layout"]
    assert proof["held_module_requests"] == 1
    assert len(proof["before"]["grids"]) == len(proof["after"]["grids"]) == 3
    assert all(g["loading"] for g in proof["before"]["grids"])
    assert all(g["mounted"] for g in proof["after"]["grids"])
    assert proof["before"]["button"] == proof["after"]["button"]


def test_a_previously_loaded_page_cannot_be_called_cold():
    page = ColdPage(prior_url="http://127.0.0.1:8520")
    with pytest.raises(AssertionError, match="unused browser page"):
        cold_open()(page, cold_qa(), {})
    assert page.navigations == page.releases == 0 and page.handler is None


def test_missing_request_is_not_replaced_with_a_warm_mount_or_timeout_extension():
    page = ColdPage(no_request=True)
    with pytest.raises(TimeoutError, match="Real module request"):
        cold_open()(page, cold_qa(), {})
    assert page.navigations == 1 and page.releases == 0 and page.handler is None


def test_cold_check_rejects_recorded_offscreen_precondition_before_measuring_module_release():
    page = ColdPage(initial_button_y=-3862.96875)
    observations = {}
    with pytest.raises(AssertionError, match="must be in view before releasing"):
        cold_open()(page, cold_qa(), observations)
    assert "after" not in observations["cold_table_layout"]
    assert page.releases == 1 and page.handler is None, "Failure cleanup releases the original response once."


@pytest.mark.parametrize("options", [
    {"shift": 327}, {"count": 2}, {"scroll_shift": 327}, {"render_changed": True},
])
def test_cold_check_rejects_recorded_shift_missing_grid_scroll_rescue_and_remount(options):
    page = ColdPage(**options)
    with pytest.raises(AssertionError):
        cold_open()(page, cold_qa(), {})
    assert page.releases == 1 and page.handler is None


def test_cold_sampler_identifies_tables_among_other_lazy_native_inputs():
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / "scripts/qa_water_page_journey.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "open_water_with_cold_tables")
    sample = next(ast.literal_eval(n.value) for n in fn.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "sample" for t in n.targets))
    # First-failure Chromium evidence had five unrelated native text skeletons
    # plus these three actual held DataFrame editors. Do not wait those away.
    keys = ["activity_summary_text", "ai_read_pages", "copilot_prompt", "copilot_paste",
            "work_orders_imported_0", "utility_analysis_text", "thermal_capacity_imported_0",
            "service_calls_imported_0"]
    script = r"""
const names=JSON.parse(process.argv[1]);
const boxes=names.map(name=>({classList:['st-key-report_guided_scope_edit_'+name+'_stamp'],
 querySelector:sel=>sel.includes('stSkeleton')?{}:null,
 compareDocumentPosition:()=>4,getBoundingClientRect:()=>({height:149})}));
const root={querySelectorAll:()=>boxes,dataset:{epcFullRender:'same'}};
const button={getBoundingClientRect:()=>({x:16,y:298,width:115,height:44})};
const pair={closest:()=>root,querySelector:()=>button};
const document={querySelector:sel=>sel==='.water'?pair:{scrollTop:6357},documentElement:{clientWidth:545}};
const window={innerHeight:757};
const Node={DOCUMENT_POSITION_FOLLOWING:4};
const sample=eval('('+process.argv[2]+')');
console.log(JSON.stringify(sample({water:'.water',keys:null})));
"""
    result = subprocess.run(["node", "-e", script, json.dumps(keys), sample],
                            capture_output=True, text=True, check=True, timeout=5)
    observed = json.loads(result.stdout)
    assert [g["key"] for g in observed["grids"]] == [
        "st-key-report_guided_scope_edit_" + key + "_stamp" for key in
        ("work_orders_imported_0", "thermal_capacity_imported_0", "service_calls_imported_0")]
    assert all(g["loading"] and not g["mounted"] for g in observed["grids"])
