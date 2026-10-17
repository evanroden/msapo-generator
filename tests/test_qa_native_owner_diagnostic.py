"""Private static-copy ownership, exact delivery and failure preservation."""
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import streamlit

from scripts import patch_streamlit_frontend as compat
from scripts import qa_native_owner_assets as assets
from scripts import qa_native_owner_server as server
from scripts import qa_fresh_native_owner_diagnostic as diagnostic
from test_streamlit_frontend_compat import bundle, files


def historical_client(root, scripts):
    sources, members = compat._locked_sources(scripts)
    # This fixture represents the already-consumed historical diagnostic.
    # Reconstruct its original generation, without either later repair.
    previous = compat._publication(sources, members, False,
                                   floating_resize=False, queued_scroll=False)
    for native, raw in previous.payloads.items():
        (scripts / previous.names[native]).write_bytes(raw)
    html = (root / "index.html").read_bytes()
    (root / "index.html").write_bytes(compat._publication_html(html, compat.INDEX_BUNDLE, previous, (previous,)))


@pytest.fixture
def client(bundle, tmp_path_factory):
    root, scripts = bundle
    native = Path(streamlit.__file__).parent / "static/static/js" / assets.FLOATING
    shutil.copyfile(native, scripts / assets.FLOATING)
    historical_client(root, scripts)
    owner = tmp_path_factory.mktemp("native-owner")
    copy = owner / "static"
    before = files(root)
    manifest = assets.build_copy(root, copy)
    assert files(root) == before
    return root, owner, copy, manifest


def test_exact_copy_changes_only_three_observed_sources_and_retains_native_import_graph(client):
    source, owner, copy, manifest = client
    original = files(source)
    intended, output = assets.expected_assets(source)
    assert manifest == intended
    changed = {str(path.relative_to(copy)) for path in copy.rglob("*") if path.is_file()
               and path.read_bytes() != original[str(path.relative_to(copy))]}
    assert changed == {"static/js/" + name for name, row in manifest["assets"].items() if row["annotated"]}
    assert len(changed) == 3
    for name, raw in output.items():
        actual = (copy / "static/js" / name).read_bytes()
        assert actual == raw and sha256(actual).hexdigest() == manifest["assets"][name]["sha256"]
        original_raw = (source / "static/js" / name).read_bytes()
        assert compat._references(actual) == compat._references(original_raw)
    assert files(source) == original
    assert (copy / "index.html").read_bytes() == (source / "index.html").read_bytes()
    assert assets.SINK.encode() not in (copy / "static/js" / manifest["selected_production"]["entry"]).read_bytes()
    with pytest.raises(RuntimeError, match="integrity|asset"):
        compat.selected_frontend(copy)  # It can never masquerade as acceptance.


def test_mutated_native_source_refuses_before_creating_copy(bundle, tmp_path_factory):
    root, scripts = bundle
    historical_client(root, scripts)
    (scripts / assets.FLOATING).write_bytes(b"unexpected native dependency")
    destination = tmp_path_factory.mktemp("refused") / "static"
    with pytest.raises(RuntimeError, match="locked Floating"):
        assets.build_copy(root, destination)
    assert not destination.exists()


def test_archived_diagnostic_refuses_new_repair_generation(bundle, tmp_path_factory):
    root, _ = bundle
    compat.patch_bundle(root, installed_version="1.61.1")
    destination = tmp_path_factory.mktemp("new-generation") / "static"
    with pytest.raises(RuntimeError, match="archived one-shot"):
        assets.build_copy(root, destination)
    assert not destination.exists()


def test_missing_annotation_site_or_changed_derivative_is_never_guessed(client):
    source, owner, copy, manifest = client
    with pytest.raises(RuntimeError, match="annotation boundary"):
        assets.annotate(b"not the selected client", [(assets.XT, assets.XT_OBSERVED)])
    changed = next(name for name, row in manifest["assets"].items() if row["annotated"])
    path = copy / "static/js" / changed
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="exact intended derivative"):
        assets.verify_copy(copy, manifest)


def test_static_redirection_is_owned_only_during_explicit_guarded_server_and_restored_on_throw(client, monkeypatch):
    from streamlit import file_util
    source, owner, copy, manifest = client
    data = owner / "data"
    data.mkdir()
    (data / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    manifest_path = owner / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    original = lambda: str(source)
    monkeypatch.setattr(file_util, "get_static_dir", original)
    for key, value in {"EPC_DATA_DIR": str(data), "EPC_MONTHLY_DOM_FIXTURE": "1",
                       "EPC_MONTHLY_FRESH_TASK": "1", "SMARTSHEET_API_MODE": "disabled"}.items():
        monkeypatch.setenv(key, value)
    calls = []
    def cli(**kwargs):
        assert file_util.get_static_dir() == str(copy)
        assert kwargs["args"][0] == "run" and kwargs["args"][1].endswith("monthly_fresh_app.py")
        assert kwargs["standalone_mode"] is False
        calls.append(kwargs)
        raise ValueError("original CLI failure")
    with pytest.raises(ValueError, match="original CLI failure"):
        server.main(["--static-dir", str(copy), "--manifest", str(manifest_path)], cli=cli)
    assert calls and file_util.get_static_dir is original
    monkeypatch.setenv("EPC_MONTHLY_FRESH_TASK", "0")
    with pytest.raises(RuntimeError, match="fixture guards"):
        server.main(["--static-dir", str(copy), "--manifest", str(manifest_path)], cli=cli)
    assert len(calls) == 1 and file_util.get_static_dir is original


def test_forged_manifest_cannot_redirect_static_even_if_it_matches_changed_copy(client, monkeypatch):
    from streamlit import file_util
    source, owner, copy, manifest = client
    data = owner / "data"
    data.mkdir()
    (data / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    monkeypatch.setattr(file_util, "get_static_dir", lambda: str(source))
    forged = json.loads(json.dumps(manifest))
    name = next(iter(forged["assets"]))
    raw = b"forged diagnostic payload"
    (copy / "static/js" / name).write_bytes(raw)
    forged["assets"][name].update(sha256=sha256(raw).hexdigest(), bytes=len(raw))
    with pytest.raises(RuntimeError, match="pinned installed client"):
        with assets.owned_static(copy, forged, data):
            pytest.fail("Forged source must not acquire server scope")
    assert file_util.get_static_dir() == str(source)


@pytest.mark.parametrize("failure", ["wrong-body", "body-error", "wrong-status"])
def test_first_wrong_natural_response_and_body_failure_are_not_replaced(client, failure):
    _, _, copy, manifest = client
    delivery = diagnostic.DerivativeDelivery(manifest)
    reads = []
    for name in manifest["assets"]:
        raw = (copy / "static/js" / name).read_bytes()
        def body():
            reads.append(name)
            if failure == "body-error":
                raise OSError("original body failure")
            return raw + b"corrupt" if failure == "wrong-body" else raw
        delivery.observe(SimpleNamespace(url="http://127.0.0.1:8529/static/js/" + name,
            status=503 if failure == "wrong-status" else 200, body=body))
        delivery.observe(SimpleNamespace(url="http://127.0.0.1:8529/static/js/" + name,
            status=200, body=lambda: reads.append(name) or raw))
    with pytest.raises(AssertionError, match="first diagnostic derivative"):
        delivery.require()
    assert len(reads) == 4


def test_delivery_reads_only_expected_origin_and_records_exact_derivative(client):
    _, _, copy, manifest = client
    delivery = diagnostic.DerivativeDelivery(manifest)
    for name in manifest["assets"]:
        raw = (copy / "static/js" / name).read_bytes()
        delivery.observe(SimpleNamespace(url="http://outside.invalid/static/js/" + name,
            body=lambda: pytest.fail("No external body read")))
        delivery.observe(SimpleNamespace(url="http://127.0.0.1:8529/static/js/" + name,
            status=200, body=lambda: raw))
    delivery.require()
    assert all(row[0]["matches"] for row in delivery.receipts.values())


def test_unchanged_fresh_adapter_restores_every_dependency_and_preserves_original_capture_failure(client, monkeypatch):
    from scripts import qa_water_fresh_page_journey as fresh
    _, _, _, manifest = client
    original = (fresh.OUT, fresh.observe_frontend_delivery, fresh.require_frontend_delivery,
                fresh.capture_native_window_errors, fresh.require_no_native_window_errors, fresh.exercise)
    with diagnostic.diagnostic_journey(manifest, Path("diagnostic-only")):
        assert fresh.require_no_native_window_errors is original[4] and fresh.exercise is original[5]
        page = SimpleNamespace(evaluate=lambda value: {"schema": "owner-copy"})
        record = {}
        fresh.capture_native_window_errors(page, record, "final")
        assert record["native_window_errors"][0]["evidence"] == {"schema": "owner-copy"}
        assert record["native_owner_observations"][0]["evidence"] == {"schema": "owner-copy"}
    assert (fresh.OUT, fresh.observe_frontend_delivery, fresh.require_frontend_delivery,
            fresh.capture_native_window_errors, fresh.require_no_native_window_errors, fresh.exercise) == original


@pytest.mark.parametrize("event_name,attempt,number,message,expected", [
    ("pull_request", "1", 249, "Coherent application repair\n\n[native-owner-diagnostic-once]\n", True),
    ("pull_request", "1", 249, "No one-shot request", False),
    ("pull_request", "2", 249, "[native-owner-diagnostic-once]", False),
    ("push", "1", 249, "[native-owner-diagnostic-once]", False),
    ("pull_request", "1", 252, "[native-owner-diagnostic-once]", False),
    ("pull_request", "1", 249, "Mention [native-owner-diagnostic-once] in prose only", False),
])
def test_workflow_diagnostic_is_deliberate_pr_head_only_once(event_name, attempt, number, message, expected):
    event = {"number": number, "pull_request": {"head": {"sha": "a" * 40}}}
    assert diagnostic.requested_once(event_name, attempt, event, message) is expected
    event["pull_request"]["head"]["sha"] = "not a commit object"
    assert not diagnostic.requested_once(event_name, attempt, event, message)


def test_missing_exact_head_commit_fails_gate_visibly_without_invoking_browser(tmp_path, monkeypatch):
    event_path, output = tmp_path / "event.json", tmp_path / "output"
    event_path.write_text(json.dumps({"number": 249, "pull_request": {"head": {"sha": "a" * 40}}}))
    for key, value in {"GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output),
                       "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ATTEMPT": "1"}.items():
        monkeypatch.setenv(key, value)
    def read(args, **kwargs):
        assert args == ["git", "show", "--no-patch", "--format=%B", "a" * 40]
        assert not kwargs.get("shell")
        raise subprocess.CalledProcessError(128, args)
    monkeypatch.setattr(diagnostic.subprocess, "check_output", read)
    with pytest.raises(subprocess.CalledProcessError):
        diagnostic.emit_gate()
    assert not output.exists()


@pytest.mark.parametrize("problem", ["missing", "capture", "limit", "sink-error", "missing-owner", "no-delivery"])
def test_missing_or_incomplete_owner_evidence_cannot_claim_attribution(problem):
    value = {"schema": "enfra-native-owner-observation-v1", "installed": True,
             "origin": "http://127.0.0.1:8529", "registrationLimit": 64, "callbackLimit": 512,
             "registrations": [{"observer": n, "owner": name} for n, name in enumerate(
                 ["aria-combobox-input-width", "floating-auto-update"], 1)],
             "callbacks": [{"observer": n, "phase": "start"} for n in [1, 2]],
             "diagnosticErrors": 0, "droppedRegistrations": 0, "droppedTargets": 0}
    record = {"native_owner_observations": [{"stage": "final", "evidence": value}]}
    if problem == "missing": record = {}
    elif problem == "capture": record["native_owner_observations"][0]["capture_error"] = "read failed"
    elif problem == "limit": value["droppedRegistrations"] = 1
    elif problem == "sink-error": value["diagnosticErrors"] = 1
    elif problem == "missing-owner": value["registrations"].pop()
    elif problem == "no-delivery": value["callbacks"].pop()
    with pytest.raises(AssertionError):
        diagnostic.require_owners(record)


def test_actual_locked_callback_annotations_preserve_native_calls_errors_and_scheduling():
    native = Path(streamlit.__file__).parent / "static/static/js" / assets.FLOATING
    source = native.read_text()
    start = source.index("function rn(")
    rn = source[start:source.index("var an=", start)]
    args = {"xt": assets.XT, "observedXt": assets.XT_OBSERVED,
            "rn": rn, "observedRn": rn.replace(assets.RN, assets.RN_OBSERVED)}
    subprocess.run(["node", "tests/qa_native_owner_callbacks_test.cjs", json.dumps(args)],
                   check=True, capture_output=True, text=True, timeout=15)


def test_bounded_sink_uses_delivered_boxes_only_and_cannot_change_native_or_error_behavior():
    subprocess.run(["node", "--test", "tests/qa_native_owner_sink_test.cjs"],
                   check=True, capture_output=True, text=True, timeout=15)
