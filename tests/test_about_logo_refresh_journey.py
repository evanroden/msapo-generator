"""Local non-browser guards; native engine acceptance remains a separate run."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
from xml.etree import ElementTree
from dataclasses import replace
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'a3' * 16


def validate_child_receipt(path):
    root = ElementTree.parse(path).getroot()
    suites = root.findall('.//testsuite')
    cases = root.findall('.//testcase')
    assert len(suites) == 1 and len(cases) == 1, 'Expected exactly one executed child test'
    assert suites[0].attrib['tests'] == '1'
    for name in ('failures', 'errors', 'skipped'):
        assert suites[0].attrib[name] == '0', 'Child test did not pass: ' + name
    assert not any(cases[0].find(name) is not None for name in ('failure', 'error', 'skipped'))


def run_app_test_child(node, tmp_path):
    log = tmp_path / 'child-pytest.log'
    receipt = tmp_path / 'child-results.xml'
    timed_out = False
    with log.open('w') as output:
        process = subprocess.Popen(
            [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
             '--basetemp', str(tmp_path / 'child-pytest'),
             '--junitxml', str(receipt), node],
            cwd=ROOT, env=dict(os.environ, EPC_ABOUT_APPTEST_CHILD=node),
            stdout=output, stderr=subprocess.STDOUT, text=True, start_new_session=True,
        )
        def stop_group(sig):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            stop_group(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        finally:
            # The group leader may exit before a TERM-resistant descendant.
            # Always retire the owned group and reap its leader, even on failure.
            stop_group(signal.SIGKILL)
            process.wait(timeout=5)
    details = log.read_text()
    assert not timed_out, 'AppTest child exceeded 180 seconds:\n' + details
    assert process.returncode == 0, details
    validate_child_receipt(receipt)


@pytest.fixture
def app_test_process(request, tmp_path):
    """The standalone fixture owns irreversible audit hooks: isolate its process.

    Re-enter only this selected test in a disposable child, preserving all real
    assertions and native output generation. Parent tests never execute the app.
    """
    node = request.node.nodeid
    if os.environ.get('EPC_ABOUT_APPTEST_CHILD') == node:
        return True
    from app import monthly_report_ai, ocr, smartsheet
    targets = ((monthly_report_ai, 'request_json'), (ocr, '_ocr_request'),
               (smartsheet, 'submit_po'))
    originals = [getattr(module, name) for module, name in targets]
    missing = object()
    names = ('_monthly_dom_guard_installed', '_monthly_dom_attempts', 'addaudithook')
    original_sys = {name: getattr(sys, name, missing) for name in names}
    run_app_test_child(node, tmp_path)
    for (module, name), original in zip(targets, originals):
        assert getattr(module, name) is original
    for name, original in original_sys.items():
        assert getattr(sys, name, missing) is original
    # Audit events only, never actual network: the parent must have no leaked deny.
    sys.audit('socket.connect', None, ('203.0.113.1', 443))
    sys.audit('socket.getaddrinfo', 'synthetic.invalid', 443, 0, 0, 0)
    return False


def app_for(monkeypatch, tmp_path, mode):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('EPC_MONTHLY_DOM_FIXTURE', '1')
    monkeypatch.setenv('EPC_MONTHLY_DOM_APPTEST', '1')
    monkeypatch.setenv('EPC_MONTHLY_LOGO_REFRESH_TASK', '1')
    (tmp_path / 'monthly-dom-synthetic-only.marker').write_text('synthetic-monthly-dom-v1')
    from app import monthly_report_section_preview_ui as preview
    monkeypatch.setattr(preview, 'render_section_preview', lambda *a, **kw: None)
    app = AppTest.from_file(str(ROOT / 'tests/fixtures/workspaces/monthly_app.py'), default_timeout=45)
    app.session_state['_monthly_dom_app_test_token'] = TOKEN
    app.query_params['logo_mode'] = mode
    app.run()
    assert not app.exception
    next(b for b in app.button if b.label == 'Create synthetic ' + mode + ' logo report').click().run()
    assert not app.exception
    return app


def receipt(app):
    from app.monthly_report_testing import isolated
    from scripts.workspace_logo_refresh_observations import snapshot
    # AppTest session state is only bound while its script executes: use the
    # emitted observation, not a second editor constructed by this test.
    from html import unescape
    import re
    values = [e.proto.body for e in app.get('html')]
    raw = next(re.search(r'data-enfra-logo-refresh="([^"]+)"', value).group(1)
               for value in values if 'data-enfra-logo-refresh=' in value)
    return json.loads(unescape(raw))


@pytest.mark.parametrize('mode', ['imported', 'custom', 'omit'])
def test_real_guided_setup_passive_explicit_and_recovery(monkeypatch, tmp_path, mode, app_test_process):
    if not app_test_process:
        return
    from scripts.workspace_history_observations import storage_state
    app = app_for(monkeypatch, tmp_path, mode)
    before = receipt(app)
    if mode == 'omit': assert before['working']['block']['source'] == 'Omit'
    files = storage_state(tmp_path, TOKEN)
    app.run(); assert not app.exception
    passive = receipt(app)
    assert passive['working'] == before['working']
    assert passive['saved'] == before['saved']
    assert passive['original_unchanged']
    action = next(b for b in app.button if b.label in ('Use this logo in this report', 'Add this logo to this report'))
    action.click().run(); assert not app.exception
    after = receipt(app)
    assert after['working'] == after['durable']
    assert after['working']['block']['asset_hashes'] == [after['company_asset']]
    assert after['working']['assets'][0]['sha256'] == after['company_sha256']
    assert after['working']['without_logo'] == before['working']['without_logo']
    assert after['saved'] == before['saved'] and after['saved_revision'] == 2
    assert after['catalog_revision'] == 1 and after['original_unchanged']
    latest = storage_state(tmp_path, TOKEN)
    for group in ('history', 'standing', 'assets'):
        assert latest['groups'][group] == files['groups'][group]
    assert latest['live_library_absent']


def test_setup_rejects_existing_namespace_and_bad_mode(monkeypatch, tmp_path, app_test_process):
    if not app_test_process:
        return
    from app.monthly_report_testing import isolated
    from scripts.workspace_logo_refresh_observations import setup
    app_for(monkeypatch, tmp_path, 'custom')
    with isolated(TOKEN):
        from app.monthly_report_testing import data_dir
        data_dir(tmp_path)
        with pytest.raises(ValueError, match='Existing synthetic report'):
            setup(tmp_path, TOKEN, 'custom')
        with pytest.raises(ValueError, match='current synthetic namespace'):
            setup(tmp_path, TOKEN, 'not-a-mode')


def test_receipt_cannot_read_live_or_missing_namespace(tmp_path):
    from scripts.workspace_logo_refresh_observations import snapshot
    with pytest.raises(ValueError):
        snapshot(tmp_path, TOKEN)


from conftest import requires_libreoffice

@requires_libreoffice
@pytest.mark.parametrize('mode', ['imported', 'custom', 'omit'])
def test_actual_native_output_assertions_before_and_after_refresh(monkeypatch, tmp_path, mode, app_test_process):
    if not app_test_process:
        return
    from scripts.qa_about_logo_refresh import validate_native_outputs
    from scripts.workspace_logo_refresh_observations import artwork
    app = app_for(monkeypatch, tmp_path, mode)
    for stage in ('before', 'after'):
        if stage == 'after':
            next(b for b in app.button if b.label == 'Use this logo in this report').click().run()
            assert not app.exception
        next(b for b in app.button if b.label == 'Render synthetic native logo outputs').click().run()
        assert not app.exception
        docx, pdf = app.session_state['_logo_refresh_outputs']
        directory = tmp_path / stage; directory.mkdir()
        (directory / 'actual.docx').write_bytes(docx)
        (directory / 'actual.pdf').write_bytes(pdf)
        expected = ([artwork('green'), artwork('red')] if stage == 'after' else
            [artwork('purple' if mode == 'custom' else 'red'), artwork('red')])
        validate_native_outputs(directory, expected)


def predicate(state, wanted, running='notRunning'):
    import ast
    import subprocess
    tree = ast.parse((ROOT / 'scripts/qa_about_logo_refresh.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'wait_state')
    expression = ast.literal_eval(function.body[0].value.args[0])
    script = '''const state=JSON.parse(process.argv[1]);
const document={querySelectorAll:()=>[{dataset:{enfraLogoRefresh:JSON.stringify(state)}}],
 querySelector:()=>({getAttribute:()=>process.argv[3]})};
console.log(JSON.stringify(eval('('+process.argv[4]+')')(JSON.parse(process.argv[2]))));'''
    result = subprocess.run(['node', '-e', script, json.dumps(state), json.dumps(wanted), running, expression],
        capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def test_native_wait_requires_fresh_exact_scope_generation_and_durable_choice():
    from copy import deepcopy
    block = {'source': 'Replace once', 'asset_hashes': ['current.png']}
    working = {'block': block, 'without_logo': 'unchanged'}
    state = {'sequence': 3, 'scope': 'scope', 'generation': 'generation', 'original_unchanged': True,
        'company_asset': 'current.png', 'working': working, 'durable': deepcopy(working)}
    wanted = {'after': 2, 'scope': 'scope', 'generation': 'generation', 'company': True}
    assert predicate(state, wanted)
    assert not predicate(state, wanted, running='running')
    for key, value in [('sequence', 2), ('scope', 'wrong'), ('generation', 'wrong'), ('original_unchanged', False)]:
        assert not predicate(dict(state, **{key: value}), wanted)
    for field, value in [('source', 'Omit'), ('asset_hashes', ['old.png'])]:
        changed = deepcopy(state); changed['working']['block'][field] = value
        changed['durable'] = deepcopy(changed['working'])
        assert not predicate(changed, wanted)
    changed = deepcopy(state); changed['durable']['without_logo'] = 'different'
    assert not predicate(changed, wanted)


@pytest.mark.parametrize("marker", [None, "wrong-marker"])
def test_controller_environment_does_not_relax_disposable_marker(tmp_path, monkeypatch, marker):
    import os
    from scripts.qa_about_logo_refresh import controller_environment
    monkeypatch.setenv("EPC_DATA_DIR", "original-root")
    monkeypatch.delenv("EPC_MONTHLY_DOM_FIXTURE", raising=False)
    if marker is not None:
        (tmp_path / "monthly-dom-synthetic-only.marker").write_text(marker)
    with pytest.raises(ValueError):
        with controller_environment(tmp_path):
            pytest.fail("Invalid disposable root was accepted")
    assert os.environ["EPC_DATA_DIR"] == "original-root"
    assert "EPC_MONTHLY_DOM_FIXTURE" not in os.environ


def test_controller_observations_share_marked_server_environment_and_restore(tmp_path, monkeypatch):
    import os
    from scripts.qa_about_logo_refresh import controller_environment
    from scripts.workspace_browser_observations import require_synthetic_root
    monkeypatch.setenv("EPC_DATA_DIR", "original-root")
    monkeypatch.setenv("EPC_MONTHLY_DOM_FIXTURE", "original-value")
    (tmp_path / "monthly-dom-synthetic-only.marker").write_text("synthetic-monthly-dom-v1")
    with controller_environment(tmp_path):
        assert os.environ["EPC_DATA_DIR"] == str(tmp_path)
        assert os.environ["EPC_MONTHLY_DOM_FIXTURE"] == "1"
        require_synthetic_root(tmp_path)
    assert os.environ["EPC_DATA_DIR"] == "original-root"
    assert os.environ["EPC_MONTHLY_DOM_FIXTURE"] == "original-value"


def test_output_and_controller_guards_import_without_optional_playwright():
    import subprocess
    import sys
    code = """
import importlib.abc, sys
class NoBrowser(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'playwright' or fullname.startswith('playwright.'):
            raise ModuleNotFoundError('Optional Playwright deliberately unavailable', name='playwright')
sys.meta_path.insert(0, NoBrowser())
from scripts import qa_about_logo_refresh as runner
assert callable(runner.validate_native_outputs) and callable(runner.controller_environment)
try:
    runner.main()
except ModuleNotFoundError as exc:
    assert exc.name == 'playwright'
else:
    raise AssertionError('Native acceptance must not silently skip missing Playwright')
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)


def test_child_fixture_keeps_process_wide_guards_strict(monkeypatch, tmp_path, app_test_process):
    if not app_test_process:
        return
    from app import monthly_report_ai, ocr, smartsheet
    app_for(monkeypatch, tmp_path, 'custom')
    for call in (monthly_report_ai.request_json, ocr._ocr_request, smartsheet.submit_po):
        with pytest.raises(AssertionError, match='Synthetic Monthly DOM fixture blocked'):
            call()
    with pytest.raises(AssertionError, match='blocked external network'):
        sys.audit('socket.connect', None, ('203.0.113.1', 443))
    with pytest.raises(AssertionError, match='blocked external network'):
        sys.audit('socket.getaddrinfo', 'synthetic.invalid', 443, 0, 0, 0)


@pytest.mark.parametrize('timeout,exit_code', [(False, 1), (True, 0)])
def test_child_failure_or_timeout_fails_parent_and_reaps_group(monkeypatch, tmp_path, timeout, exit_code):
    from types import SimpleNamespace
    signals, waits = [], []
    process = SimpleNamespace(pid=123456, returncode=exit_code)
    def wait(*, timeout):
        waits.append(timeout)
        if len(waits) == 1 and should_timeout:
            raise subprocess.TimeoutExpired('synthetic pytest child', timeout)
        return process.returncode
    should_timeout = timeout
    process.wait = wait
    def launch(command, **kwargs):
        assert command[-1] == 'synthetic-node'
        assert kwargs['env']['EPC_ABOUT_APPTEST_CHILD'] == 'synthetic-node'
        assert kwargs['start_new_session'] is True
        kwargs['stdout'].write('synthetic first-failure evidence')
        return process
    monkeypatch.setattr(subprocess, 'Popen', launch)
    monkeypatch.setattr(os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(AssertionError, match='synthetic first-failure evidence'):
        run_app_test_child('synthetic-node', tmp_path)
    assert signals == ([(123456, signal.SIGTERM)] if timeout else []) + [(123456, signal.SIGKILL)]
    assert waits == ([180, 5, 5] if timeout else [180, 5])
    assert (tmp_path / 'child-pytest.log').read_text() == 'synthetic first-failure evidence'


@pytest.mark.parametrize('tests,failures,errors,skipped', [
    (1, 0, 0, 0), (0, 0, 0, 0), (2, 0, 0, 0),
    (1, 1, 0, 0), (1, 0, 1, 0), (1, 0, 0, 1),
])
def test_child_receipt_requires_one_executed_pass(tmp_path, tests, failures, errors, skipped):
    receipt = tmp_path / 'child-results.xml'
    receipt.write_text(f'<testsuites><testsuite tests="{tests}" failures="{failures}" '
                       f'errors="{errors}" skipped="{skipped}"><testcase name="synthetic"/>'
                       '</testsuite></testsuites>')
    if (tests, failures, errors, skipped) == (1, 0, 0, 0):
        validate_child_receipt(receipt)
    else:
        with pytest.raises(AssertionError):
            validate_child_receipt(receipt)
