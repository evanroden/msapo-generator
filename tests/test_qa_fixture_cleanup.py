"""Portable harness contracts and native-control fault checks, not DOM evidence."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile

import pytest
from streamlit.testing.v1 import AppTest
from scripts import qa_fixture_cleanup as qa


@pytest.fixture
def root(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="shared-fixture-dom-synthetic-") as temp:
        base = Path(temp)
        (base / qa.shared.MARKER).write_text("shared-fixture-dom-v1")
        (base / qa.CONTROL).mkdir()
        monkeypatch.setenv("EPC_DATA_DIR", str(base))
        qa.seed(base)
        yield base


@pytest.mark.parametrize("url,ws,allowed", [
    (qa.URL, False, True), ("ws://127.0.0.1:8521/_stcore/stream", True, True),
    ("ws://127.0.0.1:8521/other", True, False), ("https://127.0.0.1:8521/", False, False),
    ("http://localhost:8521/", False, False), ("http://127.0.0.1:9999/", False, False),
    ("http://user@127.0.0.1:8521/", False, False), ("http://127.0.0.1.evil.test:8521/", False, False),
    ("https://msapo-generator.onrender.com/", False, False), ("wss://example.test/", True, False),
    ("blob:http://127.0.0.1:8521/5a73e9e0-97fc-4c11-8bde-cdd54f619117", False, True),
    ("blob:https://example.test/5a73e9e0-97fc-4c11-8bde-cdd54f619117", False, False),
    ("blob:http://127.0.0.1:8521/not-a-uuid", False, False), ("data:text/html,unsafe", False, False),
])
def test_exact_http_and_websocket_allowlist(url, ws, allowed):
    assert qa.allowed_url(url, websocket=ws) is allowed


def test_environment_has_no_runner_credentials_or_existing_home(root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-to-forward")
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token-not-to-forward")
    monkeypatch.setenv("HTTPS_PROXY", "https://example.test/")
    monkeypatch.setenv("HOME", "/nonexistent-existing-home")
    env = qa.child_environment(root)
    assert env["EPC_DATA_DIR"] == str(root) and env["OPENAI_API_KEY"] == ""
    assert "GITHUB_TOKEN" not in env and "HTTPS_PROXY" not in env
    assert Path(env["HOME"]).is_relative_to(root)


def test_unmarked_and_symlinked_roots_refused(root, tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        qa.guarded_root(tmp_path)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        qa.guarded_root(alias)
    (root / qa.shared.MARKER).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        qa.guarded_root(root)


def test_snapshot_does_not_create_namespace(root):
    before = qa.snapshot(root, "a" * 32)
    assert before["exists"] is False and before["reservations"] == []
    assert not qa.namespace(root, "a" * 32).exists()


@contextmanager
def wrapped_faults(root, monkeypatch):
    from app import monthly_report_fixture_admission as admission
    from app import monthly_report_fixture_vault as vault
    from app import monthly_report_testing as testing
    with monkeypatch.context() as patch:
        # Register original values with pytest before the harness replaces them.
        for obj, name in ((admission, "_save"), (vault, "_write_file"), (testing, "recover_set_aside")):
            patch.setattr(obj, name, getattr(obj, name))
        qa.install_faults(root)
        yield


def native(cookie):
    app = AppTest.from_string("from app.monthly_report_ui import render_monthly_report_workflow\n"
        "render_monthly_report_workflow(" + repr(cookie) + ")", default_timeout=30)
    app.query_params["monthly_qa"] = "fixtures"
    app.run()
    assert not app.exception
    return app


def click(app, label):
    next(item for item in app.button if item.label == label).click().run()
    if "_shared_fixture_pending" in app.session_state:
        app.run()
    assert not app.exception


def test_exact_scope_one_shot_fault_through_native_start_preserves_original(root, monkeypatch):
    a, b = "a" * 32, "b" * 32
    first = native(a)
    click(first, "Start fresh test with this fixture")
    before = qa.snapshot(root, a)
    second = native(b)
    qa.age(root, a)
    with wrapped_faults(root, monkeypatch):
        qa.arm(root, b, "source-failure")
        click(second, "Start fresh test with this fixture")
        assert "SYNTHETIC source-write failure" in "\n".join(item.value for item in second.error)
        after = qa.snapshot(root, a)
        assert after == before
        assert qa.snapshot(root, b)["source_sha256"] is None
        receipts = [json.loads(line) for line in (root / qa.CONTROL / "events.jsonl").read_text().splitlines()]
        assert receipts == [{"armed": {"scope": qa.namespace(root, b).name, "mode": "source-failure"}},
                            {"triggered": {"scope": qa.namespace(root, b).name, "mode": "source-failure"}}]
        first.run()
        click(second, "Start fresh test with this fixture")
        assert qa.snapshot(root, b)["source_sha256"] == before["source_sha256"]
        assert len(qa.snapshot(root, a)["reservations"]) == 2


def test_accounting_budget_setup_is_explicitly_one_byte(root):
    app = native("a" * 32)
    click(app, "Start fresh test with this fixture")
    receipt = qa.fill_budget(root)
    assert receipt["physical_bytes"] == 1
    assert receipt["reserved_bytes"] > 120 * 1024 * 1024
    assert sum(item["added_bytes"] for item in qa.snapshot(root, "a" * 32)["reservations"]) == 128 * 1024 * 1024


def test_workflow_is_read_only_and_not_a_production_dispatch():
    text = (qa.ROOT / ".github/workflows/fixture-cleanup.yml").read_text()
    assert "contents: read" in text and "persist-credentials: false" in text
    assert "secrets." not in text and "workflow_dispatch" not in text
    assert "python scripts/qa_fixture_cleanup.py" in text
    assert "chromium webkit" in text and "if: always()" in text


def crash_native(base, cookie):
    # Separate process preserves real kernel-release behavior. No AppTest monkey-
    # patched exception is treated as equivalent to os._exit.
    os.environ['EPC_DATA_DIR'] = str(base)
    qa.install_faults(base)
    app = native(cookie)
    click(app, 'Start fresh test with this fixture')
    raise AssertionError('Synthetic process never reached its armed crash')


@pytest.mark.parametrize('corrupt', [False, True])
def test_native_partial_crash_wrapper_and_affected_reset_boundary(root, monkeypatch, corrupt):
    import multiprocessing
    a, b, c = 'a' * 32, 'b' * 32, 'c' * 32
    app = native(a)
    click(app, 'Start fresh test with this fixture')
    before = qa.snapshot(root, a)
    qa.age(root, a)
    qa.arm(root, b, 'crash-partial')
    child = multiprocessing.get_context('spawn').Process(target=crash_native, args=(root, b))
    try:
        child.start()
        child.join(45)
        assert child.exitcode == 23
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)
    hidden = qa.snapshot(root, a)
    assert hidden['journal'] and not hidden['exists'] and len(hidden['tombstones']) == 1
    assert any(before['source_sha256'] in files.values() for files in hidden['tombstones'].values())
    returned = native(a)
    assert 'awaiting fixture cleanup recovery' in '\n'.join(item.value for item in returned.error)
    if corrupt:
        (root / qa.ADMISSION / qa.JOURNAL).write_text('{"schema":2}')
    other = native(c)
    click(other, 'Start fresh test with this fixture')
    expected = 'Fixture installation recovery metadata is invalid.' if corrupt else "requires its browser's scoped reset"
    assert expected in '\n'.join(item.value for item in other.error)
    affected = native(b)
    click(affected, 'Reset this test workspace')
    assert (root / qa.ADMISSION / qa.JOURNAL).exists()
    with wrapped_faults(root, monkeypatch):
        (root / qa.CONTROL / 'restored.jsonl').write_text('')
        click(other, 'Start fresh test with this fixture')
    final = qa.snapshot(root, a)
    assert final['originals'] == before['originals'] and final['live_canary'] == before['live_canary']
    if corrupt:
        assert expected in '\n'.join(item.value for item in other.error)
        assert final['tombstones'] == hidden['tombstones'] and final['journal']
        assert qa.snapshot(root, c)['source_sha256'] is None
    else:
        assert not final['journal']
        assert qa.snapshot(root, c)['source_sha256'] == before['source_sha256']
        rows = [json.loads(line) for line in (root / qa.CONTROL / 'restored.jsonl').read_text().splitlines()]
        assert any({'scope': before['scope'], 'generation': before['generation_marker'].split('|')[1],
                    'source_sha256': before['source_sha256']} in row['restored'] for row in rows)


def test_cookie_survives_actual_entrypoint_identity_validation():
    from app.device_identity import device_token
    cookie = qa.new_cookie()
    assert len(cookie) == 32
    assert device_token({"epc_device_id": cookie}) == cookie
    assert device_token({"epc_device_id": "a" * 48}) == ""


def test_local_configuration_refused_before_child_can_read_it(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, 'ROOT', tmp_path)
    (tmp_path / '.env').write_text('SYNTHETIC_ONLY=not-a-real-credential')
    with pytest.raises(ValueError, match='local credential configuration'):
        qa.require_clean_configuration()


def test_pre_import_network_guard_blocks_without_connecting(root):
    import subprocess
    (root / qa.shared.GUARD_LOG).write_text('')
    command = '''from scripts import qa_fixture_cleanup as qa
import os, socket
qa.install_outbound_guard(os.environ['EPC_DATA_DIR'])
try:
    socket.getaddrinfo('example.invalid', 443)
except AssertionError:
    pass
else:
    raise AssertionError('Guard did not block the call before DNS')
'''
    result = subprocess.run([qa.sys.executable, '-c', command], cwd=qa.ROOT,
        env=qa.child_environment(root), capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads((root / qa.shared.GUARD_LOG).read_text()) == {'blocked': 'socket.getaddrinfo:non-loopback'}


def test_generation_poll_does_not_inventory_a_resetting_namespace(root, monkeypatch):
    cookie = qa.new_cookie()
    target = qa.namespace(root, cookie)
    monkeypatch.setattr(qa, 'inventory', lambda *_: pytest.fail('Polling must not inventory changing trees'))
    assert qa.poll_generation(root, cookie) is None
    target.mkdir(parents=True)
    marker = target / qa.SENTINEL
    marker.write_text('')
    assert qa.poll_generation(root, cookie) is None
    marker.write_text(target.name + '|' + 'a' * 32)
    assert qa.poll_generation(root, cookie) == marker.read_text()
    marker.unlink()
    assert qa.poll_generation(root, cookie) is None


def test_browser_observation_dispatches_queued_websocket_without_reclick(root, monkeypatch):
    # A routed click can be queued after locator.click returns. Only entering
    # Playwright dispatches it; Python sleep must never be the browser poll.
    cookie = qa.new_cookie()
    target = qa.namespace(root, cookie)
    target.mkdir(parents=True)
    marker = target / qa.SENTINEL
    old = target.name + '|' + 'a' * 32
    new = target.name + '|' + 'b' * 32
    marker.write_text(old)
    calls = []
    def dispatch(milliseconds):
        calls.append(milliseconds)
        marker.write_text(new)  # queued native callback, never another click
    monkeypatch.setattr(qa.time, 'sleep', lambda _: pytest.fail('Browser poll starved Playwright'))
    qa.wait_until(lambda: qa.poll_generation(root, cookie) not in (None, '', old),
                  dispatch_events=dispatch, label='native Start generation')
    assert calls == [50]
    assert qa.poll_generation(root, cookie) == new


def test_browser_observation_timeout_is_bounded_and_labels_phase(monkeypatch):
    clock = [0.0]
    polls = []
    def dispatch(milliseconds):
        polls.append(milliseconds)
        clock[0] += milliseconds / 1000
    monkeypatch.setattr(qa.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(qa.time, 'sleep', lambda _: pytest.fail('Browser poll used Python sleep'))
    with pytest.raises(AssertionError, match='native Reset generation'):
        qa.wait_until(lambda: False, seconds=.12, dispatch_events=dispatch,
                      label='native Reset generation')
    assert len(polls) == 3 and abs(sum(polls) - 120) < .001


def test_browser_observation_does_not_dispatch_after_success(monkeypatch):
    qa.wait_until(lambda: True, dispatch_events=lambda _: pytest.fail('Unneeded event dispatch'),
                  label='already observed')


def test_all_browser_filesystem_waits_preserve_event_dispatch():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(qa.exercise))
    waits = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'wait_until']
    assert len(waits) == 6
    for wait in waits:
        keywords = {item.arg: item.value for item in wait.keywords}
        assert {'dispatch_events', 'label'} <= keywords.keys()
        assert isinstance(keywords['dispatch_events'], ast.Attribute)
        assert keywords['dispatch_events'].attr == 'wait_for_timeout'
