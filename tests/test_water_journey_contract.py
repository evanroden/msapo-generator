"""The browser receipt predicate must not depend on optional/null serialization."""
import json
import subprocess
from pathlib import Path


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
