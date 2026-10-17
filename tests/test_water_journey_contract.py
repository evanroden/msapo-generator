"""The browser receipt predicate must not depend on optional/null serialization."""
import json
import hashlib
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


def cold_module_handler():
    import ast
    source = Path(__file__).resolve().parents[1] / "scripts/qa_water_page_journey.py"
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == "keep_table_module_uncached")
    namespace = {"re": re, "sha256": hashlib.sha256}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[function.name]


class ModuleRoute:
    def __init__(self, url, status=200, response_url=None):
        from types import SimpleNamespace
        self.request = SimpleNamespace(url=url)
        self.raw = b'/* unchanged native module */ export const identity = "native";'
        self.response = SimpleNamespace(status=status, url=response_url or url,
            headers={"cache-control": "public, immutable, max-age=31536000",
                     "content-type": "application/javascript", "etag": '"original"'},
            body=lambda: self.raw)
        self.fetched, self.fulfilled = [], []

    def fetch(self, **options):
        self.fetched.append(options)
        return self.response

    def fulfill(self, **options):
        self.fulfilled.append(options)


def test_cold_reload_keeps_original_module_bytes_and_limits_only_its_test_cache():
    origin = "http://127.0.0.1:8520"
    name = "DataFrame.v-5GXvjU.enfra-overlay-732bfc01d57053d1e52f.js"
    route = ModuleRoute(origin + "/static/js/" + name)
    receipts = []
    assert cold_module_handler()(route, origin, receipts)
    assert route.fetched == [{"max_redirects": 0, "timeout": 20000}]
    assert len(route.fulfilled) == 1
    delivered = route.fulfilled[0]
    assert delivered["response"] is route.response
    assert delivered["body"] is route.raw
    assert delivered["headers"] == {**route.response.headers, "cache-control": "no-store"}
    assert route.response.headers["cache-control"] == "public, immutable, max-age=31536000"
    assert receipts == [{"module": name, "bytes": len(route.raw),
        "sha256": hashlib.sha256(route.raw).hexdigest(),
        "original_cache_control": "public, immutable, max-age=31536000",
        "synthetic_cache_control": "no-store"}]


@pytest.mark.parametrize("url", [
    "https://msapo-generator.onrender.com/static/js/DataFrame.test.js",
    "http://127.0.0.1:8521/static/js/DataFrame.test.js",
    "http://127.0.0.1:8520/static/js/index.test.js",
    "http://127.0.0.1:8520/static/css/DataFrame.test.css",
    "http://127.0.0.1:8520/static/js/DataFrame.test.js?other=1",
    "data:text/javascript,unchanged",
])
def test_cold_reload_does_not_fetch_or_change_other_routes(url):
    route = ModuleRoute(url)
    receipts = []
    assert not cold_module_handler()(route, "http://127.0.0.1:8520", receipts)
    assert route.fetched == route.fulfilled == receipts == []


@pytest.mark.parametrize("status,response_url", [(302, None), (500, None),
    (200, "https://example.invalid/redirected.js")])
def test_cold_reload_rejects_redirects_and_failed_responses(status, response_url):
    route = ModuleRoute("http://127.0.0.1:8520/static/js/DataFrame.test.js", status, response_url)
    receipts = []
    with pytest.raises(AssertionError, match="Unexpected local DataFrame response"):
        cold_module_handler()(route, "http://127.0.0.1:8520", receipts)
    assert route.fetched == [{"max_redirects": 0, "timeout": 20000}]
    assert route.fulfilled == receipts == []
