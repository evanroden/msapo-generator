"""Offline only: no browser, display, bus daemon, or accessible IPC is started."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace

import pytest
from scripts import qa_directory_retention_atspi as probe
from scripts import qa_directory_retention_atspi_bus as bus
from scripts import qa_directory_retention_atspi_read as reader
from scripts import qa_directory_retention_headed as headed
from scripts import qa_directory_retention_local as local


@pytest.fixture
def base():
    with tempfile.TemporaryDirectory(prefix=local.PREFIX) as name:
        path = Path(name)
        (path / local.MARKER).write_text('a' * 32)
        (path / local.GUARD_LOG).write_text('')
        (path / 'ordinary-canary').write_bytes(local.CANARY)
        (path / bus.RUNTIME).mkdir(mode=0o700)
        authority = path / headed.AUTHORITY
        authority.write_bytes(b'fake-offline-authority')
        authority.chmod(0o600)
        yield path


def test_inherited_guard_and_journey_parity():
    for name in ('run', 'guard', 'boundary', 'transport_boundary', 'action', 'download_grid'):
        assert getattr(probe.HeadedJourney, name) is getattr(headed.HeadedJourney, name)
    for name in ('Server', 'allowed_url', 'final_isolation_failure', 'verified_browser'):
        assert getattr(probe, name) is getattr(headed, name)
    original = inspect.getsource(headed.observe_owned_display)
    candidate = inspect.getsource(probe.observe_owned_display)
    candidate = candidate.replace(',\n                args=["--force-renderer-accessibility"]', '')
    candidate = candidate.replace('except headed.ObservationComplete:', 'except ObservationComplete:')
    candidate = candidate.replace('"AT-SPI accessibility bridge and --force-renderer-accessibility change environment and timing; not acceptance parity.",\n                         ', '')
    assert candidate == original


def test_scrubbed_launch_environment(base, monkeypatch):
    for key in ('DISPLAY', 'XAUTHORITY', 'DBUS_SESSION_BUS_ADDRESS', 'AT_SPI_BUS_ADDRESS',
                'DBUS_STARTER_ADDRESS', 'WAYLAND_DISPLAY', 'GITHUB_TOKEN', 'HTTPS_PROXY'):
        monkeypatch.setenv(key, 'inherited-secret')
    env = bus.launch_environment(base, 'a' * 40)
    assert 'inherited-secret' not in env.values()
    assert env['XDG_RUNTIME_DIR'] == str(base / bus.RUNTIME)
    assert env['HOME'] == str(base / 'home')


def test_exact_owned_session_socket(base, monkeypatch):
    runtime = base / bus.RUNTIME
    path = runtime / 'session-bus'
    path.touch()
    original_stat = Path.stat
    def fake_stat(self, *args, **kwargs):
        result = original_stat(self, *args, **kwargs)
        if self == path:
            return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=result.st_uid)
        return result
    monkeypatch.setattr(Path, 'stat', fake_stat)
    address = 'unix:path=' + str(path)
    monkeypatch.setenv('DISPLAY', ':123')
    monkeypatch.setenv('XAUTHORITY', str(base / headed.AUTHORITY))
    monkeypatch.setenv('DBUS_SESSION_BUS_ADDRESS', address)
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(runtime))
    assert bus.accessibility_environment(base, 'a' * 40)['DBUS_SESSION_BUS_ADDRESS'] == address
    monkeypatch.setenv('XDG_RUNTIME_DIR', '/run/user/1000')
    with pytest.raises(local.SafetyStop):
        bus.accessibility_environment(base, 'a' * 40)


@pytest.mark.parametrize('value', ['unix:abstract=foreign', 'tcp:host=localhost,port=1',
    'unix:path=/run/user/1000/bus', 'unix:path=/tmp/foo;unix:path=/tmp/bar', 'autolaunch:'])
def test_reject_bus_transports_and_foreign_sockets(base, value):
    with pytest.raises((local.SafetyStop, OSError)):
        bus.validate_socket_address(value, base / bus.RUNTIME)
    with pytest.raises((RuntimeError, OSError)):
        reader.socket_address(value, base / bus.RUNTIME)


def test_reject_runtime_permissions(base):
    (base / bus.RUNTIME).chmod(0o755)
    with pytest.raises(local.SafetyStop):
        bus.launch_environment(base, 'a' * 40)


def test_config_excludes_inherited_services():
    source = inspect.getsource(bus.prepare_bus)
    assert '<standard_session_servicedirs' not in source
    assert '<include' not in source
    assert '<auth>EXTERNAL</auth>' in source
    assert 'unix:path=' in source


class Node:
    def __init__(self, role='dialog', name='Synthetic', children=(), pid=123):
        self.role, self.name, self.children, self.pid = role, name, list(children), pid
    @property
    def childCount(self): return len(self.children)
    def getChildAtIndex(self, i): return self.children[i]
    def get_process_id(self): return self.pid
    def getRole(self): return self.role
    def getRoleName(self): return self.role
    def get_attributes(self): return getattr(self, 'attributes', {})
    def getState(self): return SimpleNamespace(contains=lambda flag: flag in getattr(self, 'states', []))
    def getRelationSet(self): return getattr(self, 'relations', [])
    def queryComponent(self): return SimpleNamespace(getExtents=lambda coords: self.rect)
    def queryText(self): return SimpleNamespace(characterCount=len(self.text), getText=lambda start, end: self.text[start:end])


API = SimpleNamespace(**{'STATE_' + name.upper(): name for name in
    ('showing', 'visible', 'enabled', 'sensitive', 'focused', 'editable')},
    DESKTOP_COORDS=0, ROLE_ENTRY='entry', ROLE_TEXT='text', ROLE_PASSWORD_TEXT='password', RELATION_LABELLED_BY='labelled-by',
    listInterfaces=lambda node: getattr(node, 'interfaces', []))


def collect(desktop, pid, roles):
    return reader.collect(desktop, pid, roles, API)


def desktop(dialogs):
    return Node('desktop', children=[Node('application', children=dialogs)])


def test_bounded_metadata_only():
    result = collect(desktop([Node(children=[Node('push button', 'Save')])]), 123, {'dialog'})
    assert result['observation_only'] is True
    assert result['nodes'][1]['name'] == 'Save'
    assert set(result['nodes'][1]) == {'index', 'parent', 'depth', 'role', 'name', 'children', 'states', 'screen_rect', 'editable_entry_text', 'labelled_by'}


@pytest.mark.parametrize('dialogs', [[], [Node(), Node()], [Node(pid=999)],
    [Node(name='x' * 257)], [Node(children=[Node()] * 65)]])
def test_ambiguous_ownership_and_bounds_fail_closed(dialogs):
    with pytest.raises(RuntimeError):
        collect(desktop(dialogs), 123, {'dialog'})


def test_depth_and_total_bounds(monkeypatch):
    node = Node()
    for _ in range(17): node = Node(children=[node])
    with pytest.raises(RuntimeError): collect(desktop([node]), 123, {'dialog'})
    monkeypatch.setattr(reader, 'MAX_NODES', 1)
    with pytest.raises(RuntimeError):
        collect(desktop([Node(children=[Node()])]), 123, {'dialog'})


def test_foreign_apps_are_not_traversed():
    class Foreign(Node):
        @property
        def childCount(self): raise AssertionError('Foreign tree read')
    root = desktop([Node()])
    root.children.append(Foreign(pid=999))
    assert collect(root, 123, {'dialog'})['dialog_count'] == 1


def test_owned_pid_rejects_unrelated_process():
    import os
    with pytest.raises(local.SafetyStop):
        bus.owned_pid(os.getpid(), '/untrusted/not-the-browser')


def test_x11_parent_link_and_same_pid(monkeypatch):
    dialog = {'id': '0x2', 'properties': 'WM_CLASS(STRING) = "chrome", "Chrome"\nWM_TRANSIENT_FOR(WINDOW): window id # 0x1\n_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_DIALOG\n_NET_WM_PID(CARDINAL) = 123\n'}
    parent = {'id': '0x1', 'properties': 'WM_CLASS(STRING) = "browser", "Chromium-browser"\n_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_NORMAL\n_NET_WM_PID(CARDINAL) = 123\n'}
    verified = []
    monkeypatch.setattr(bus, 'owned_pid', lambda pid, binary: verified.append((pid, binary)))
    assert bus.dialog_owner({'windows': [dialog, parent], 'window_tree': ' 0x2 "Warning": ("chrome" "Chrome") 1124x822+0+0 +0+0\n'}, '/pinned')['pid'] == 123
    assert verified == [(123, '/pinned')]
    parent['properties'] = parent['properties'].replace('123', '456')
    with pytest.raises(local.SafetyStop): bus.dialog_owner({'windows': [dialog, parent], 'window_tree': ' 0x2 "Warning": ("chrome" "Chrome") 1124x822+0+0 +0+0\n'}, '/pinned')
    with pytest.raises(local.SafetyStop): bus.dialog_owner({'windows': [dialog, dialog]}, '/pinned')


def test_helper_timeout_and_output_validation(monkeypatch):
    def run(args, **kwargs):
        assert args[0:2] == ['/usr/bin/python3', '-I']
        assert kwargs['timeout'] == 20
        return SimpleNamespace(stdout=b'{}', stderr=b'', returncode=0)
    monkeypatch.setattr(bus.subprocess, 'run', run)
    with pytest.raises(local.SafetyStop): bus.capture_accessibility({}, {'pid': 123})


def test_native_input_and_mutation_interfaces_absent():
    forbidden = {'doAction', 'queryAction', 'queryEditableText', 'queryValue',
        'setTextContents', 'grabFocus', 'generateKeyboardEvent', 'generateMouseEvent',
        'setCaretOffset', 'setValue', 'setCurrentValue'}
    for module in (probe, bus, reader):
        source = Path(module.__file__).read_text()
        tree = ast.parse(source)
        assert not forbidden & {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert 'xdotool' not in source and 'force=True' not in source
    assert 'signal.alarm(15)' in inspect.getsource(reader.main)


def test_workflow_pr_only_and_production_off():
    source = Path('.github/workflows/directory-retention-atspi.yml').read_text()
    assert '  pull_request:\n' in source
    for forbidden in ('workflow_dispatch:', 'pull_request_target:', '  push:', 'schedule:',
                      'MONTHLY_QA_DIRECTORY_ACCEPTANCE', 'xdotool', 'secrets.'):
        assert forbidden not in source
    assert 'contents: read' in source
    assert 'python3-pyatspi' in source
    assert 'persist-credentials: false' in source


def entry(text='synthetic.csv'):
    node = Node('text', 'Name')
    node.states = ['editable', 'focused', 'showing', 'visible', 'enabled', 'sensitive']
    node.interfaces = ['Component', 'Text', 'EditableText']
    node.rect = SimpleNamespace(x=10, y=20, width=100, height=30)
    node.text = text
    return node


def relation(target):
    return SimpleNamespace(getRelationType=lambda: 'labelled-by', getNTargets=lambda: 1,
                           getTarget=lambda offset: target)


def test_entry_metadata_and_owned_labels():
    field, label = entry(), Node('label', 'Name:')
    field.relations = [relation(label)]
    result = collect(desktop([Node(children=[field, label])]), 123, {'dialog'})
    value = result['nodes'][1]
    assert all(value['states'].values())
    assert value['screen_rect'] == {'x': 10, 'y': 20, 'width': 100, 'height': 30}
    assert value['editable_entry_text'] == 'synthetic.csv'
    assert value['labelled_by'] == [{'index': 2, 'name': 'Name:'}]


@pytest.mark.parametrize('mode', ['not-editable', 'document'])
def test_no_text_read_outside_editable_entry(mode):
    field = entry()
    if mode == 'not-editable': field.states = []
    else: field.role = mode
    def forbidden(): raise AssertionError('Text must not be queried')
    field.queryText = forbidden
    assert collect(desktop([Node(children=[field])]), 123, {'dialog'})['nodes'][1]['editable_entry_text'] is None


@pytest.mark.parametrize('mode', ['text', 'rectangle', 'foreign-label', 'outside-dialog-label', 'relations'])
def test_enriched_bounds_and_ownership(mode):
    field = entry()
    if mode == 'text': field.text = 'x' * 257
    if mode == 'rectangle': field.rect.width = 32769
    if mode == 'foreign-label': field.relations = [relation(Node(pid=999))]
    if mode == 'outside-dialog-label': field.relations = [relation(Node())]
    if mode == 'relations': field.relations = [relation(field)] * 17
    with pytest.raises(reader.ObservationFailure):
        collect(desktop([Node(children=[field])]), 123, {'dialog'})


def test_failure_diagnostics_never_include_raw_values(monkeypatch):
    monkeypatch.setattr(reader, 'STAGE', 'registry')
    for exc in (RuntimeError('secret raw value'), OSError('secret path'),
                ImportError('secret module'), TimeoutError('secret timeout'),
                reader.ObservationFailure('dialog_count')):
        value = reader.diagnostic(exc)
        assert value['stage'] in reader.STAGES
        assert value['reason'] in reader.REASONS
        assert value['type'] in reader.TYPES
        assert 'secret' not in json.dumps(value)


def test_parent_preserves_only_allowlisted_diagnostic(monkeypatch):
    failure = {'stage': 'dialogs', 'reason': 'dialog_count', 'type': 'ObservationFailure'}
    monkeypatch.setattr(bus.subprocess, 'run', lambda *a, **kw:
        SimpleNamespace(stdout=b'', stderr=json.dumps(failure).encode(), returncode=1))
    with pytest.raises(local.SafetyStop, match='dialog_count'):
        bus.capture_accessibility({}, {'pid': 123})
    failure['reason'] = 'SECRET'
    with pytest.raises(local.SafetyStop, match='unclassified') as exc:
        bus.capture_accessibility({}, {'pid': 123})
    assert 'SECRET' not in str(exc.value)


@pytest.mark.parametrize('mode', ['password-role', 'protected-attribute'])
def test_protected_fields_fail_without_reading_text(mode):
    field = entry()
    if mode == 'password-role': field.role = 'password'
    else: field.attributes = {'protected': 'true'}
    def forbidden(): raise AssertionError('Protected text read')
    field.queryText = forbidden
    with pytest.raises(reader.ObservationFailure, match='protected_field'):
        collect(desktop([Node(children=[field])]), 123, {'dialog'})


@pytest.mark.parametrize('states', [[], ['showing'], ['visible']])
def test_hidden_component_geometry_is_not_queried(states):
    field = entry()
    field.states = states
    field.rect = SimpleNamespace(x=-(2 ** 31), y=-(2 ** 31), width=0, height=0)
    def forbidden(): raise AssertionError('Hidden geometry must not be queried')
    field.queryComponent = forbidden
    value = collect(desktop([Node(children=[field])]), 123, {'dialog'})['nodes'][1]
    assert value['screen_rect'] is None
