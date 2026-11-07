"""Offline observation-safety tests. No native display or browser is started."""
import ast
import inspect
import json
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
from types import ModuleType
from unittest.mock import Mock

import pytest

from scripts import qa_directory_retention_headed as headed
from scripts import qa_directory_retention_local as local

SHA = "d" * 40


@pytest.fixture
def base():
    with tempfile.TemporaryDirectory(prefix=local.PREFIX) as value:
        path = Path(value)
        (path / local.MARKER).write_text("f" * 32)
        (path / local.GUARD_LOG).write_text("")
        (path / "ordinary-canary").write_bytes(local.CANARY)
        authority = path / headed.AUTHORITY
        authority.write_bytes(b"fake-authority-for-offline-test")
        authority.chmod(0o600)
        yield path


def test_all_route_identity_storage_and_action_guards_are_inherited():
    for name in ("run", "guard", "boundary", "transport_boundary", "action", "button", "fill", "radio"):
        assert getattr(headed.HeadedJourney, name) is getattr(local.LocalJourney, name)
    assert headed.Server is local.Server
    assert headed.allowed_url is local.allowed_url
    assert headed.final_isolation_failure is local.final_isolation_failure


def owned_environment(base, monkeypatch):
    monkeypatch.setenv("DISPLAY", ":123")
    monkeypatch.setenv("XAUTHORITY", str(base / headed.AUTHORITY))


def test_only_private_owned_display_is_added_to_scrubbed_environment(base, monkeypatch):
    owned_environment(base, monkeypatch)
    for key in ("DBUS_SESSION_BUS_ADDRESS", "GITHUB_TOKEN", "HTTPS_PROXY", "MONTHLY_QA_DIRECTORY_ACCEPTANCE"):
        monkeypatch.setenv(key, "must-not-propagate")
    env = headed.display_environment(base, SHA)
    assert env["DISPLAY"] == ":123"
    assert env["XAUTHORITY"] == str(base / headed.AUTHORITY)
    assert env["HOME"] == str(base / "home")
    assert not ({"DBUS_SESSION_BUS_ADDRESS", "GITHUB_TOKEN", "HTTPS_PROXY", "MONTHLY_QA_DIRECTORY_ACCEPTANCE"} & env.keys())


@pytest.mark.parametrize("drift", ["display", "authority", "mode", "empty", "symlink"])
def test_display_fail_closed(base, monkeypatch, drift):
    owned_environment(base, monkeypatch)
    path = base / headed.AUTHORITY
    if drift == "display":
        monkeypatch.setenv("DISPLAY", "remote.example:123")
    elif drift == "authority":
        monkeypatch.setenv("XAUTHORITY", "/tmp/unowned-authority")
    elif drift == "mode":
        path.chmod(0o644)
    elif drift == "empty":
        path.write_bytes(b"")
    else:
        path.unlink()
        path.symlink_to(base / local.MARKER)
    with pytest.raises(local.SafetyStop):
        headed.display_environment(base, SHA)


def fake_journey(base, tmp_path):
    item = headed.HeadedJourney(Mock(), Mock(), "e" * 32,
        local.LocalConfig(SHA, "f" * 32), tmp_path, base, Mock(), b"invented")
    item.guard = Mock()
    return item


def test_desktop_capture_is_guarded_and_refuses_overwrite(base, tmp_path, monkeypatch):
    item = fake_journey(base, tmp_path)
    monkeypatch.setattr(headed, "display_environment", Mock(return_value={}))
    read = Mock(return_value=({"window_tree": "synthetic windows", "windows": []}, b"fakepng"))
    monkeypatch.setattr(headed, "desktop_measurement", read)
    item.capture_desktop("before-click")
    assert item.guard.call_count == 2
    assert (tmp_path / "desktop-before-click.png").read_bytes() == b"fakepng"
    assert item.desktop_observations[0]["stage"] == "before-click"
    with pytest.raises(FileExistsError):
        item.capture_desktop("before-click")


@pytest.mark.parametrize("when", [0, 1])
def test_capture_discards_on_boundary_drift(base, tmp_path, monkeypatch, when):
    item = fake_journey(base, tmp_path)
    item.guard.side_effect = [local.SafetyStop("drift")] if when == 0 else [None, local.SafetyStop("drift")]
    monkeypatch.setattr(headed, "display_environment", Mock(return_value={}))
    read = Mock(return_value=({}, b"untrusted screenshot"))
    monkeypatch.setattr(headed, "desktop_measurement", read)
    with pytest.raises(local.SafetyStop):
        item.capture_desktop("after-click")
    assert item.desktop_observations == []
    assert list(tmp_path.iterdir()) == []
    assert read.call_count == when


def native_setup(base, tmp_path, monkeypatch):
    item = fake_journey(base, tmp_path)
    api = ModuleType("playwright.sync_api")
    api.expect = Mock()
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    item.capture_csv_geometry = Mock()
    item.capture_desktop = Mock()
    monkeypatch.setattr(headed.time, "sleep", Mock())
    box = Mock()
    return item, box


def test_first_native_click_stops_before_caller_can_confirm_or_save(base, tmp_path, monkeypatch):
    item, box = native_setup(base, tmp_path, monkeypatch)
    after_export = Mock()
    with pytest.raises(headed.ObservationComplete):
        item.download_grid(box, "reviewed-contacts")
        after_export()
    grid = box.get_by_test_id.return_value
    grid.hover.assert_called_once_with()
    grid.get_by_role.assert_called_once_with("button", name="Download as CSV", exact=True)
    grid.get_by_role.return_value.click.assert_called_once_with()
    assert [call.args[0] for call in item.capture_desktop.call_args_list] == ["before-click", "after-click", "settled-after-click"]
    assert item.events[-1]["status"] == "completed"
    after_export.assert_not_called()
    item.page.expect_download.assert_not_called()
    assert item.storage_receipts == []


def test_native_failure_preserved_when_capture_also_fails(base, tmp_path, monkeypatch):
    item, box = native_setup(base, tmp_path, monkeypatch)
    original = RuntimeError("native click failed")
    box.get_by_test_id.return_value.get_by_role.return_value.click.side_effect = original
    item.capture_desktop.side_effect = [None, ValueError("capture failed")]
    with pytest.raises(RuntimeError) as failure:
        item.download_grid(box, "reviewed-contacts")
    assert failure.value is original
    assert item.desktop_observations == [{"stage": "failed-click", "capture_error_type": "ValueError"}]
    assert item.events[-1]["status"] == "attempted"


def test_failed_preclick_capture_prevents_click(base, tmp_path, monkeypatch):
    item, box = native_setup(base, tmp_path, monkeypatch)
    item.capture_desktop.side_effect = local.SafetyStop("drift")
    with pytest.raises(local.SafetyStop):
        item.download_grid(box, "reviewed-contacts")
    box.get_by_test_id.return_value.get_by_role.assert_not_called()


def test_rejects_later_export_names(base, tmp_path, monkeypatch):
    item, box = native_setup(base, tmp_path, monkeypatch)
    with pytest.raises(local.SafetyStop):
        item.download_grid(box, "saved-history")
    box.get_by_test_id.assert_not_called()


def test_x11_reader_only_uses_read_utilities_and_bounds(monkeypatch):
    fake = Mock(stdout="too big" * 10000)
    run = Mock(return_value=fake)
    monkeypatch.setattr(headed.subprocess, "run", run)
    with pytest.raises(local.SafetyStop):
        headed.bounded_x11(["xwininfo", "-root", "-tree"], {})
    assert run.call_args.kwargs["timeout"] == 5
    assert run.call_args.kwargs["check"] is True


def test_shared_network_handlers_have_exact_ast_parity():
    get = lambda function: ast.parse(textwrap.dedent(inspect.getsource(function)))
    for name in ("route", "websocket"):
        nodes = [next(n for n in ast.walk(get(func)) if isinstance(n, ast.FunctionDef) and n.name == name)
                 for func in (local.exercise, headed.observe_owned_display)]
        assert ast.dump(nodes[0]) == ast.dump(nodes[1])
    source = inspect.getsource(headed.observe_owned_display)
    for invariant in ("context.cookies()", 'service_workers="block"', "journey.namespace.exists()",
                      'context.route("**/*", route)', 'context.route_web_socket("**/*", websocket)',
                      "final_isolation_failure(record)"):
        assert invariant in source
    assert 'headless=False, env=env, executable_path=binary["path"]' in source
    assert 'binary = verified_browser(base)' in source


def test_launcher_never_reuses_display_or_invokes_dialog_input(monkeypatch, tmp_path):
    for key, value in {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "pull_request",
                       "GITHUB_REPOSITORY": "evanroden/msapo-generator",
                       "DISPLAY": ":55", "XAUTHORITY": "/tmp/unowned"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(headed, "OUT", tmp_path / "new-evidence")
    monkeypatch.setattr(headed.shutil, "which", Mock(return_value="/usr/bin/fake"))
    from PIL import features
    monkeypatch.setattr(features, "check_feature", Mock(return_value=True))
    monkeypatch.setattr(headed.subprocess, "check_output", Mock(return_value=SHA))
    monkeypatch.setattr(headed, "resolve_pinned_browser", Mock(return_value={"path": "/fake/pinned", "sha256": "0" * 64, "playwright_version": "1.58.0"}))
    process = Mock(pid=12345)
    process.wait.return_value = 0
    popen = Mock(return_value=process)
    monkeypatch.setattr(headed.subprocess, "Popen", popen)
    kill = Mock(side_effect=ProcessLookupError)
    monkeypatch.setattr(headed.os, "killpg", kill)
    headed.launch()
    args, kwargs = popen.call_args.args[0], popen.call_args.kwargs
    assert args[0:3] == ["xvfb-run", "--auto-servernum", "--auth-file"]
    assert args[4:6] == ["--server-args", "-screen 0 1600x1200x24 -nolisten tcp"]
    assert kwargs["start_new_session"] is True
    assert "DISPLAY" not in kwargs["env"] and "XAUTHORITY" not in kwargs["env"]
    assert process.wait.call_args_list[0].kwargs == {"timeout": 240}
    assert kill.call_args.args[0] == process.pid
    assert json.loads((headed.OUT / "launcher.json").read_text())["result"] == "child completed"


def test_launcher_requires_pr_workflow(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(local.SafetyStop):
        headed.launch()


def test_separate_workflow_cannot_opt_into_production():
    workflow = (local.ROOT / ".github/workflows/directory-retention-headed.yml").read_text()
    assert "pull_request:" in workflow
    for forbidden in ("workflow_run:", "workflow_dispatch:", "schedule:", "push:",
                      "MONTHLY_QA_DIRECTORY_ACCEPTANCE", "MONTHLY_QA_PUBLIC_URL"):
        assert forbidden not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "python scripts/qa_directory_retention_headed.py" in workflow
    assert "python scripts/qa_directory_retention_live.py" not in workflow
    assert "retention-days: 7" in workflow
    source = Path(headed.__file__).read_text()
    for forbidden in ("force=True", "showSaveFilePicker =", "add_init_script", "xdotool", "pyautogui", ".press(", ".keyboard"):
        assert forbidden not in source


@pytest.fixture
def pinned_binary(tmp_path, monkeypatch):
    path = tmp_path / "chromium-1208/chrome-linux64/chrome"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"invented offline executable bytes; never executed")
    path.chmod(0o700)
    monkeypatch.setattr(headed, "version", lambda name: "1.58.0")
    return path


def test_pinned_manifest_resolves_installed_binary_with_scrubbed_home(base, pinned_binary, monkeypatch):
    binary = headed.browser_identity(pinned_binary)
    (base / headed.BROWSER_MANIFEST).write_text(json.dumps({
        "root_nonce": (base / local.MARKER).read_text(), "browser": binary}))
    monkeypatch.setenv("HOME", str(base / "home"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(base / "home/cache"))
    assert headed.verified_browser(base) == binary
    assert not (base / "home/cache/ms-playwright").exists()
    assert binary["playwright_version"] == "1.58.0"


@pytest.mark.parametrize("drift", ["missing", "hash", "version", "fields", "manifest-link", "binary-link", "not-executable", "system-path", "nonce"])
def test_pinned_manifest_fail_closed(base, pinned_binary, monkeypatch, drift):
    binary = headed.browser_identity(pinned_binary)
    manifest = base / headed.BROWSER_MANIFEST
    if drift == "hash":
        pinned_binary.write_bytes(b"changed")
    elif drift == "version":
        monkeypatch.setattr(headed, "version", lambda name: "1.59.0")
    elif drift == "fields":
        binary["extra"] = True
    elif drift == "binary-link":
        original = pinned_binary.with_name("original")
        pinned_binary.rename(original)
        pinned_binary.symlink_to(original)
    elif drift == "not-executable":
        pinned_binary.chmod(0o600)
    elif drift == "system-path":
        binary["path"] = "/usr/bin/chromium"
    if drift != "missing":
        manifest.write_text(json.dumps({
            "root_nonce": (base / local.MARKER).read_text(), "browser": binary}))
    if drift == "nonce":
        (base / local.MARKER).write_text("b" * 32)
    if drift == "manifest-link":
        target = base / "other-manifest"
        manifest.rename(target)
        manifest.symlink_to(target)
    with pytest.raises(local.SafetyStop):
        headed.verified_browser(base)
