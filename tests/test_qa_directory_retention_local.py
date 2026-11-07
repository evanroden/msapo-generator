"""Offline tests for the loopback-only companion. No browser/server is started."""
import ast
import inspect
import json
from pathlib import Path
import tempfile
import textwrap
from unittest.mock import Mock

import pytest

from scripts import qa_directory_retention_live as live
from scripts import qa_directory_retention_local as local

TOKEN = "e" * 32
NONCE = "f" * 32
SHA = "d" * 40


@pytest.fixture
def base():
    with tempfile.TemporaryDirectory(prefix=local.PREFIX) as value:
        root = Path(value)
        (root / local.MARKER).write_text(NONCE)
        (root / local.GUARD_LOG).write_text("")
        (root / "ordinary-canary").write_bytes(local.CANARY)
        yield root


def test_local_orchestration_tracks_production_without_editing_its_globals():
    normalize = lambda method: ast.dump(ast.parse(textwrap.dedent(inspect.getsource(method))), include_attributes=False)
    assert normalize(local.LocalJourney.run) == normalize(live.Journey.run)
    assert local.LocalJourney.download_grid is live.Journey.download_grid
    assert local.LocalJourney.action is live.Journey.action
    assert local.LocalJourney.button is live.Journey.button
    assert local.LocalJourney.radio is live.Journey.radio
    assert local.LocalJourney.fill is live.Journey.fill
    assert live.ORIGIN == "https://msapo-generator.onrender.com"
    with pytest.raises(live.SafetyStop):
        live.validate_route(local.LocalConfig(SHA, NONCE).address("directory"), "directory")
    with pytest.raises(live.SafetyStop):
        live.Config.from_environment({}, SHA)


@pytest.mark.parametrize("origin", [
    "https://msapo-generator.onrender.com", "http://localhost:8529",
    "http://127.0.0.1:8530", "http://127.1:8529", "https://127.0.0.1:8529",
    "http://user@127.0.0.1:8529", "http://127.0.0.1:8529.evil.example"])
def test_loopback_target_is_exact(origin):
    with pytest.raises(local.SafetyStop):
        local.LocalConfig(SHA, NONCE, origin)
    assert not local.allowed_url(origin + "/?workflow=monthly&monthly_qa=isolated&monthly_admin=directory",
                                 "directory", top_level=True)


@pytest.mark.parametrize("suffix", ["", "&monthly_qa=isolated", "&other=1", "#fragment"])
def test_route_fails_closed(suffix):
    address = local.ORIGIN + "/?workflow=monthly" if not suffix else local.LocalConfig(SHA, NONCE).address("directory") + suffix
    assert not local.allowed_url(address, "directory", top_level=True)


def test_local_http_websocket_and_blob_rules():
    config = local.LocalConfig(SHA, NONCE)
    assert local.allowed_url(config.address("directory"), "directory", top_level=True)
    assert local.allowed_url(local.ORIGIN + "/_stcore/upload_file/id", "directory")
    assert local.allowed_url("ws://127.0.0.1:8529/_stcore/stream", "directory", websocket=True)
    for url in ("wss://127.0.0.1:8529/_stcore/stream", "ws://127.0.0.1:8529/else",
                "ws://127.0.0.1:8529/_stcore/stream?other=1"):
        assert not local.allowed_url(url, "directory", websocket=True)
    assert local.allowed_url("blob:" + local.ORIGIN + "/12345678-1234-1234-1234-123456789abc", "directory")
    assert not local.allowed_url("blob:" + live.ORIGIN + "/12345678-1234-1234-1234-123456789abc", "directory")
    assert not local.allowed_url(config.address("storage"), "directory", top_level=True)


def test_child_environment_is_scrubbed_and_root_bound(base, monkeypatch, tmp_path):
    monkeypatch.setattr(local, "ROOT", tmp_path)
    for key in ("HOME", "EPC_DATA_DIR", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "AWS_ACCESS_KEY_ID",
                "HTTPS_PROXY", "PYTHONPATH", "MONTHLY_QA_PUBLIC_URL", "MONTHLY_QA_DIRECTORY_ACCEPTANCE"):
        monkeypatch.setenv(key, "synthetic-should-not-be-inherited")
    env = local.child_environment(base, SHA)
    assert env["EPC_DATA_DIR"] == str(base) and env["APP_GIT_COMMIT"] == SHA
    assert env["HOME"] == env["XDG_CONFIG_HOME"] == str(base / "home")
    assert env["ANTHROPIC_API_KEY"] == "" and env["OPENAI_API_KEY"] == ""
    assert not ({"GITHUB_TOKEN", "AWS_ACCESS_KEY_ID", "HTTPS_PROXY", "PYTHONPATH",
                 "MONTHLY_QA_PUBLIC_URL", "MONTHLY_QA_DIRECTORY_ACCEPTANCE"} & env.keys())
    (tmp_path / ".env").write_text("SYNTHETIC_ONLY=1")
    with pytest.raises(local.SafetyStop):
        local.child_environment(base, SHA)


def test_root_requires_exact_marker_and_not_arbitrary_directory(base, tmp_path):
    assert local.guarded_root(base) == base
    with pytest.raises(local.SafetyStop):
        local.guarded_root(tmp_path)
    (base / local.MARKER).write_text("invalid")
    with pytest.raises(local.SafetyStop):
        local.guarded_root(base)


def test_socket_audit_blocks_external_attempt_and_records_it(base, monkeypatch):
    hook = Mock()
    monkeypatch.setattr(local.sys, "addaudithook", hook)
    local.install_outbound_guard(base)
    audit = hook.call_args.args[0]
    audit("socket.connect", (None, ("127.0.0.1", 8529)))
    audit("socket.getaddrinfo", ("localhost", 8529))
    with pytest.raises(local.SafetyStop):
        audit("socket.connect", (None, ("203.0.113.10", 443)))
    assert json.loads((base / local.GUARD_LOG).read_text()) == {"blocked": "socket.connect:non-loopback"}


def journey(base, tmp_path):
    page, context, server = Mock(), Mock(), Mock()
    config = local.LocalConfig(SHA, NONCE)
    page.url = config.address("directory")
    context.cookies.return_value = [{"name": "epc_device_id", "value": TOKEN, "domain": "127.0.0.1", "path": "/"}]
    item = local.LocalJourney(page, context, TOKEN, config, tmp_path, base, server, b"synthetic")
    item.namespace.mkdir(parents=True)
    (item.namespace / ".enfra-qa-namespace").write_text(item.namespace.name + "|" + "a" * 32)
    return item


@pytest.mark.parametrize("drift", ["root_nonce", "generation", "ordinary", "network", "symlink", "cookie", "process"])
def test_physical_boundary_drift_blocks_next_mutation(base, tmp_path, drift):
    item = journey(base, tmp_path)
    item.boundary()
    if drift == "root_nonce":
        (base / local.MARKER).write_text("b" * 32)
    elif drift == "generation":
        (item.namespace / ".enfra-qa-namespace").write_text(item.namespace.name + "|" + "b" * 32)
    elif drift == "ordinary":
        (base / "monthly_reports").mkdir()
    elif drift == "network":
        item.blocked.append("unexpected")
    elif drift == "symlink":
        (item.namespace / "link").symlink_to(tmp_path, target_is_directory=True)
    elif drift == "cookie":
        item.context.cookies.return_value[0]["value"] = "b" * 32
    else:
        item.server.alive.side_effect = local.SafetyStop("server exited")
    item.guard = item.boundary
    action = Mock()
    with pytest.raises(local.SafetyStop):
        item.action("Save", action)
    action.assert_not_called()
    assert item.events == []


def test_workflow_runs_only_local_native_preflight():
    source = (local.ROOT / ".github/workflows/directory-retention-local.yml").read_text()
    assert "pull_request:" in source and "workflow_run:" not in source and "workflow_dispatch:" not in source
    assert "push:" not in source and "schedule:" not in source
    assert "permissions:\n  contents: read" in source
    assert "persist-credentials: false" in source
    assert "python scripts/qa_directory_retention_local.py" in source
    assert "python -m scripts.qa_directory_retention_live" not in source
    assert "MONTHLY_QA_DIRECTORY_ACCEPTANCE:" not in source
    assert "MONTHLY_QA_PUBLIC_URL:" not in source


@pytest.mark.parametrize("field,value", [("blocked_requests", ["late HTTP"]),
    ("page_errors", ["late error"]), ("server_guard", ["late outbound"]),
    ("ordinary_canary_unchanged", False)])
def test_final_isolation_failure_cannot_leave_passed_receipt(field, value):
    record = {"result": "passed native local", "blocked_requests": [], "page_errors": [],
              "server_guard": [], "ordinary_canary_unchanged": True}
    assert not local.final_isolation_failure(record)
    record[field] = value
    assert local.final_isolation_failure(record)
    assert record["result"] == "failed final isolation checks"
