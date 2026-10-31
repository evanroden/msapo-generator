"""Actual native action -> run cleanup -> queued wire, plus immutable delivery.

No local browser, network, customer data, or installed frontend mutation. The
Node harness executes shipped bodies against deterministic hook/timer slots;
AppTest separately covers server callback identity and durable row behavior.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat
from scripts import streamlit_dataframe_action_owners as repair
from test_streamlit_frontend_compat import bundle, files

DATAFRAME_BUNDLE = "DataFrame.v-5GXvjU.js"
DATAFRAME_SHA256 = "9e7ad369664508a9614cc23408b3e93f47489263ee4ef39f4ff0849535efc2e3"


def between(source, start, end):
    offset = source.index(start)
    return source[offset:source.index(end, offset)]


def lifecycle_sources(before, after, dataframe, installed):
    """Extract actual code, not reimplementations of the behavior under test."""
    utils = (installed / "utils.KTqwHXHU.js").read_text()
    return {
        "hook": between(dataframe, "function Oh(", "var kh="),
        "menu": between(dataframe, "function E_(", "var D_="),
        "stateClass": between(before, "Yg=class", "},Xg=class")[3:] + "}",
        "treeNodes": between(before, "Bs=class", "},Gs=class") + "}",
        "appRoot": between(before, "Ys=class e", ";oe(),Se(),xe();"),
        "managerMethods": ",".join(between(before, start, end) for start, end in (
            ("setStringTriggerValue(e,t,n,r){", "setTriggerValue("),
            ("setStringValue(e,t,n,r){", "setStringArrayValue("),
            ("onWidgetValueChanged(e,t,n){", "syncFormsWithPendingChanges(){"),
            ("sendUpdateWidgetsMessage(e,t=void 0){", "getActiveWidgetStates("),
            ("removeInactive(e){this.widgetStates.removeInactive(e)", "createWidgetState("),
            ("createWidgetState(e,t){", "getWidgetState("),
            ("deleteWidgetState(e){", "getOrCreateFormState("),
            ("scheduleFlush(e){", "registerQueryParamBinding("))),
        "getWidgetId": between(utils, "function Ut(e){", "function Gt(e){"),
        "scriptFinished": between(before, "handleScriptFinished(e){", "clearAppState("),
        "cleanup": between(before, "removeInactiveWidgetState(){", "openDialog("),
        "fixedCleanup": between(after, "removeInactiveWidgetState(){", "openDialog("),
        "protobuf": str(installed / "protobuf.CBn3jIav.js"),
    }


def test_actual_menu_acceptance_survives_finished_run_cleanup_until_one_native_flush(bundle):
    _, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    before = compat._publication(sources, members, False, dataframe_action_owners=False)
    after = compat._publication(sources, members, False)
    dataframe = sources[DATAFRAME_BUNDLE]
    assert sha256(dataframe).hexdigest() == DATAFRAME_SHA256
    assert before.names[compat.INDEX_BUNDLE] == "index.enfra-frontend-6591a5e7450a.js"
    data = lifecycle_sources(before.payloads[compat.INDEX_BUNDLE].decode(),
        after.payloads[compat.INDEX_BUNDLE].decode(), dataframe.decode(),
        Path(streamlit.__file__).parent / "static/static/js")
    run = subprocess.run(["node", "tests/dataframe_action_owners_test.cjs", json.dumps(data)],
                         capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stdout + run.stderr
    result = json.loads(run.stdout)
    assert result["pass"] and len(result["cases"]) >= 38
    baseline, repaired = result["cases"][:2]
    assert baseline["assigned"] == repaired["assigned"] == 1  # Both accepted the native menu action.
    assert baseline["packets"] == repaired["packets"] == 2  # Not a wait, retry, or additional event.
    assert baseline["actionPackets"] == 0 and repaired["actionPackets"] == 1
    assert baseline["menuClosed"] and repaired["menuClosed"]


def test_exact_cleanup_only_changes_and_native_guards_batcher_and_consumption_are_identical(bundle):
    _, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    raw = sources[compat.INDEX_BUNDLE]
    repaired = repair.repair_dataframe_action_owners(raw)
    assert repaired.replace(repair.REPAIRED, repair.ORIGINAL, 1) == raw
    for unknown in (raw + b" ", raw + repair.ORIGINAL, repaired, raw.replace(repair.ORIGINAL, b"")):
        with pytest.raises(RuntimeError, match="Unexpected locked DataFrame action-owner"):
            repair.repair_dataframe_action_owners(unknown)
    for scalar_date in (False, True):
        old = compat._publication(sources, members, scalar_date, dataframe_action_owners=False)
        new = compat._publication(sources, members, scalar_date)
        # Compare normalized import edges to prove no other behavior changed.
        def normalized(publication, name):
            raw = publication.payloads[name]
            for native, selected in publication.names.items():
                raw = raw.replace(selected.encode(), native.encode())
            return raw
        for name in sources:
            new_raw = normalized(new, name)
            if name == compat.INDEX_BUNDLE:
                new_raw = new_raw.replace(repair.REPAIRED, repair.ORIGINAL, 1)
            assert new_raw == normalized(old, name)


@pytest.mark.parametrize("scalar_date", [False, True])
def test_current_cached_generation_upgrades_atomically_and_reloads_new_immutable_graph(bundle, scalar_date):
    root, scripts = bundle
    sources, members = compat._locked_sources(scripts)
    old = compat._publication(sources, members, scalar_date, dataframe_action_owners=False)
    assert old.names[compat.INDEX_BUNDLE] == {
        False: "index.enfra-frontend-6591a5e7450a.js",
        True: "index.enfra-frontend-070dc53f4c76.js",
    }[scalar_date]
    for name, raw in old.payloads.items():
        (scripts / old.names[name]).write_bytes(raw)
    (root / "index.html").write_bytes(compat._publication_html(
        (root / "index.html").read_bytes(), compat.INDEX_BUNDLE, old, (old,)))
    before = files(root)
    assert not compat.selected_frontend(root)["dataframe_action_owners"]
    new = compat.patch_bundle(root, installed_version="1.61.1")
    assert new["dataframe_action_owners"] and new["closure_count"] == 83
    assert new["scalar_date"] is scalar_date and new["entry"] != old.names[compat.INDEX_BUNDLE]
    assert compat.selected_frontend(root)["dataframe_action_owners"]
    assert compat._SCRIPT.findall((root / "index.html").read_bytes()) == [new["entry"].encode()]
    assert sha256((scripts / new["entry"]).read_bytes()).hexdigest() == new["patched_entry_sha256"]
    assert repair.REPAIRED in (scripts / new["entry"]).read_bytes()
    # The old cached URL stays byte-identical and remains honestly unrepaired.
    # An already loaded tab needs a reload; no live-client monkeypatch is used.
    assert repair.ORIGINAL in (scripts / old.names[compat.INDEX_BUNDLE]).read_bytes()
    for name, raw in before.items():
        if name != "index.html":
            assert (root / name).read_bytes() == raw
    after = files(root)
    assert compat.patch_bundle(root, installed_version="1.61.1")["already_patched"]
    assert files(root) == after


@pytest.mark.parametrize("fault", ["version", "original", "selected"])
def test_unknown_version_or_source_or_selected_payload_fails_closed_without_writes(bundle, fault):
    root, scripts = bundle
    if fault == "selected":
        receipt = compat.patch_bundle(root, installed_version="1.61.1")
        path = scripts / receipt["entry"]
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "original":
        path = scripts / compat.INDEX_BUNDLE
        path.write_bytes(path.read_bytes() + b" ")
    before = files(root)
    with pytest.raises(RuntimeError):
        compat.patch_bundle(root, installed_version="1.61.2" if fault == "version" else "1.61.1")
    assert files(root) == before


def test_actual_installer_entrypoint_repairs_only_disposable_application_copy(bundle):
    root, _ = bundle
    run = subprocess.run([sys.executable, "scripts/patch_streamlit_frontend.py", "--static-dir", str(root)],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    receipt = json.loads(run.stdout)
    assert receipt["dataframe_action_owners"] and not receipt["already_patched"]
    assert "native_trigger_runtime" not in receipt  # No installed runtime mutation.
    assert compat.selected_frontend(root)["dataframe_action_owners"]
    repeated = subprocess.run([sys.executable, "scripts/patch_streamlit_frontend.py", "--static-dir", str(root)],
                              capture_output=True, text=True, timeout=30)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert json.loads(repeated.stdout)["already_patched"]
    # Existing image build and CI bootstrap run the same publisher. A bare
    # Streamlit app rerun is not an installer and does not repair a loaded tab.
    for path in ("Dockerfile", ".github/workflows/adaptive-workspaces.yml"):
        assert "patch_streamlit_frontend" in Path(path).read_text()
    assert "patch_streamlit_frontend" not in Path("run_web.py").read_text()


def test_action_owner_only_changes_trigger_unchanged_native_row_gate():
    workflow = Path(".github/workflows/adaptive-workspaces.yml").read_text()
    sections = re.split(r"^  (pull_request|push):\n", workflow.split("\npermissions:", 1)[0], flags=re.MULTILINE)
    events = dict(zip(sections[1::2], sections[2::2]))
    for event in ("push", "pull_request"):
        assert {"scripts/streamlit_dataframe_action_owners.py",
                "tests/test_streamlit_dataframe_action_owners.py",
                "tests/dataframe_action_owners_test.cjs"} <= set(
            re.findall(r"^      - '([^']+)'$", events[event], flags=re.MULTILINE))
    from test_ci_native_test_budget import parse_jobs
    row_job = "".join(parse_jobs(workflow)["synthetic-work-order-rows"])
    assert "python scripts/patch_streamlit_frontend.py" in row_job
    assert "python scripts/qa_work_order_rows.py" in row_job
