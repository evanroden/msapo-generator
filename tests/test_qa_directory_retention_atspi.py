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
    DESKTOP_COORDS=0, ROLE_FRAME='frame', ROLE_ENTRY='entry', ROLE_TEXT='text', ROLE_PASSWORD_TEXT='password', RELATION_LABELLED_BY='labelled-by',
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
    assert bus.dialog_owner({'windows': [dialog, parent], 'window_tree': ' 0x2 "Warning": ("chrome" "Chrome") 1124x822+0+0 +0+0\n 0x1 "Browser": ("browser" "Chromium-browser") 1448x1085+10+10 +10+10\n'}, '/pinned')['pid'] == 123
    assert verified == [(123, '/pinned')]
    parent['properties'] = parent['properties'].replace('123', '456')
    with pytest.raises(local.SafetyStop): bus.dialog_owner({'windows': [dialog, parent], 'window_tree': ' 0x2 "Warning": ("chrome" "Chrome") 1124x822+0+0 +0+0\n 0x1 "Browser": ("browser" "Chromium-browser") 1448x1085+10+10 +10+10\n'}, '/pinned')
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


def topology_fixture():
    frame = Node('frame', 'Synthetic native window', children=[Node('entry', 'not traversed')])
    return reader.failure_topology([Node('application', 'Chromium', children=[frame])], 123, API, 0)


def test_dialog_count_retains_only_shallow_metadata_and_still_fails():
    class ShallowOnly(Node):
        def getChildAtIndex(self, index): raise AssertionError('Deeper topology read')
        def queryText(self): raise AssertionError('Failure diagnostic text read')
        def getRelationSet(self): raise AssertionError('Failure diagnostic relations read')
    frame = ShallowOnly('frame', 'Synthetic native window', children=[Node()])
    with pytest.raises(reader.ObservationFailure, match='dialog_count') as exc:
        collect(desktop([frame]), 123, {'dialog'})
    value = exc.value.topology
    assert reader.valid_failure_topology(value, 123)
    assert value['dialog_count'] == 0 and value['application_count'] == 1
    assert [node['role'] for node in value['nodes']] == ['application', 'frame']
    assert all('editable_entry_text' not in node and 'labelled_by' not in node for node in value['nodes'])


def test_duplicate_dialogs_remain_failed_with_counts():
    with pytest.raises(reader.ObservationFailure) as exc:
        collect(desktop([Node(), Node()]), 123, {'dialog'})
    assert exc.value.reason == 'dialog_count'
    assert exc.value.topology['dialog_count'] == 2


@pytest.mark.parametrize('mode', ['foreign', 'protected', 'bound'])
def test_failure_topology_rejects_unsafe_nodes(mode):
    frame = Node('frame')
    if mode == 'foreign': frame.pid = 999
    if mode == 'protected': frame.role = 'password'
    children = [frame] if mode != 'bound' else [frame] * 64
    with pytest.raises(reader.ObservationFailure):
        reader.failure_topology([Node('application', children=children)], 123, API, 0)


@pytest.mark.parametrize('mode', ['pid', 'extra', 'text', 'deep', 'count', 'rectangle'])
def test_parent_topology_schema_rejects_drift(mode):
    data = topology_fixture()
    if mode == 'pid': data['pid'] = 999
    if mode == 'extra': data['unrequested'] = 'value'
    if mode == 'text': data['nodes'][1]['editable_entry_text'] = 'value'
    if mode == 'deep': data['nodes'][1]['parent'] = 1
    if mode == 'count': data['dialog_count'] = 1
    if mode == 'rectangle': data['nodes'][1]['screen_rect'] = {'x': 0, 'y': 0, 'width': 1, 'height': 1}
    assert not reader.valid_failure_topology(data, 123)


def test_parent_failure_diagnostic_remains_exception(monkeypatch):
    failure = {'stage': 'dialogs', 'reason': 'dialog_count', 'type': 'ObservationFailure'}
    topology = topology_fixture()
    monkeypatch.setattr(bus.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        stdout=json.dumps(topology).encode(), stderr=json.dumps(failure).encode(), returncode=1))
    with pytest.raises(bus.AccessibilityDiagnosticFailure) as exc:
        bus.capture_accessibility({}, {'pid': 123})
    assert exc.value.topology == topology


@pytest.mark.parametrize('drift', [False, True])
def test_failed_metadata_retained_only_after_post_read_guard(monkeypatch, drift):
    from unittest.mock import Mock
    topology = topology_fixture()
    error = bus.AccessibilityDiagnosticFailure('failed')
    error.topology = topology
    monkeypatch.setattr(headed.HeadedJourney, 'capture_desktop', lambda self, stage: None)
    monkeypatch.setattr(probe, 'display_environment', lambda *args: {})
    monkeypatch.setattr(probe, 'verified_browser', lambda *args: {'path': '/pinned'})
    monkeypatch.setattr(probe, 'desktop_measurement', lambda env: ({}, b''))
    owner = {'pid': 123}
    owners = iter([owner, {'pid': 999} if drift else owner])
    monkeypatch.setattr(bus, 'dialog_owner', lambda *args: next(owners))
    def fail(*args): raise error
    monkeypatch.setattr(bus, 'capture_accessibility', fail)
    journey = object.__new__(probe.HeadedJourney)
    journey.base = Path('/unused')
    journey.config = SimpleNamespace(commit='a' * 40)
    journey.desktop_observations = [{}]
    journey.guard = Mock()
    with pytest.raises(local.SafetyStop): journey.capture_desktop('settled-after-click')
    assert ('accessibility_failure_topology' in journey.desktop_observations[0]) is not drift
    assert journey.guard.call_count == (1 if drift else 2)


def nested_fixture(children=()):
    frame = Node('frame', 'Browser', children=children)
    frame.interfaces = ['Component']
    frame.states = ['showing', 'visible']
    frame.rect = SimpleNamespace(x=10, y=10, width=1448, height=1085)
    owner = {'pid': 123, 'window': '0x2', 'transient_for': '0x1', 'title': 'Warning',
             'screen_rect': {'x': 0, 'y': 0, 'width': 1124, 'height': 822},
             'browser_parent': {'title': 'Browser', 'screen_rect': vars(frame.rect).copy()}}
    app = Node('application', children=[frame])
    return app, frame, owner


def test_nested_candidate_is_metadata_only_and_still_failure():
    candidate = Node('panel', 'Warning')  # Role is observed, never substituted.
    candidate.interfaces = ['Component', 'Text', 'EditableText']
    candidate.states = ['showing', 'visible', 'editable']
    candidate.rect = SimpleNamespace(x=0, y=0, width=1124, height=822)
    def forbidden(): raise AssertionError('Nested diagnostic queried text or relations')
    candidate.queryText = candidate.getRelationSet = forbidden
    app, frame, owner = nested_fixture([Node('panel', children=[candidate])])
    with pytest.raises(reader.ObservationFailure, match='dialog_count') as exc:
        reader.collect(Node('desktop', children=[app]), 123, {'dialog'}, API, owner)
    topology = exc.value.topology
    nested = topology['nested']
    assert nested['complete'] and nested['candidate_indices'] == [2]
    assert nested['nodes'][2]['role'] == 'panel'
    assert reader.valid_failure_topology(topology, 123, owner)
    assert all('editable_entry_text' not in node and 'labelled_by' not in node for node in nested['nodes'])


@pytest.mark.parametrize('mode', ['pid', 'title', 'rect', 'role', 'multiple-children', 'multiple-apps'])
def test_nested_traversal_requires_unique_verified_frame(mode):
    app, frame, owner = nested_fixture([Node()])
    apps = [app]
    if mode == 'pid': frame.pid = 999
    if mode == 'title': frame.name = 'Different'
    if mode == 'rect': frame.rect.x = 11
    if mode == 'role': frame.role = 'unknown'
    if mode == 'multiple-children': app.children.append(Node())
    if mode == 'multiple-apps': apps.append(app)
    with pytest.raises(reader.ObservationFailure, match='ownership'):
        reader.nested_topology(apps, 123, API, owner)


@pytest.mark.parametrize('mode', ['node', 'depth', 'child', 'byte'])
def test_nested_budget_retains_explicit_incomplete_prefix(monkeypatch, mode):
    app, frame, owner = nested_fixture([Node('panel', children=[Node('panel', children=[Node()])])])
    if mode == 'node': monkeypatch.setattr(reader, 'MAX_NODES', 2)
    if mode == 'depth': monkeypatch.setattr(reader, 'NESTED_DEPTH', 1)
    if mode == 'child': frame.children[0].children = [Node()] * 65
    if mode == 'byte': monkeypatch.setattr(reader, 'NESTED_BYTES', 650)
    value = reader.nested_topology([app], 123, API, owner)
    assert value['complete'] is False
    assert value['truncation'] == mode + '_limit'
    assert value['nodes']
    assert reader.valid_nested_topology(value, owner)


def test_nested_foreign_descendant_is_not_read():
    class Foreign(Node):
        def get_attributes(self): raise AssertionError('Foreign metadata read')
    app, frame, owner = nested_fixture([Foreign(pid=999)])
    with pytest.raises(reader.ObservationFailure, match='ownership'):
        reader.nested_topology([app], 123, API, owner)


def test_nested_schema_rejects_false_candidate_and_extra_text():
    app, frame, owner = nested_fixture([Node()])
    value = reader.nested_topology([app], 123, API, owner)
    value['candidate_indices'] = [1]
    assert not reader.valid_nested_topology(value, owner)
    value['candidate_indices'] = []
    value['nodes'][1]['text'] = 'unrequested'
    assert not reader.valid_nested_topology(value, owner)


def test_helper_receives_bounded_owned_descriptor_on_stdin(monkeypatch):
    _, _, owner = nested_fixture()
    def run(args, **kwargs):
        assert json.loads(kwargs['input']) == owner
        assert len(kwargs['input']) <= 4096
        return SimpleNamespace(stdout=b'{}', stderr=b'', returncode=0)
    monkeypatch.setattr(bus.subprocess, 'run', run)
    with pytest.raises(local.SafetyStop): bus.capture_accessibility({}, owner)


@pytest.mark.parametrize('limit', ['depth', 'child', 'node'])
def test_nested_breadth_first_preserves_shallow_candidate_after_large_first_branch(monkeypatch, limit):
    first = Node('panel', children=[Node('panel', children=[Node()])])
    if limit == 'depth': monkeypatch.setattr(reader, 'NESTED_DEPTH', 1)
    if limit == 'child': first.children = [Node()] * 65
    if limit == 'node':
        first.children = [Node()] * 20
        monkeypatch.setattr(reader, 'MAX_NODES', 3)
    candidate = Node('panel', 'Warning')
    candidate.interfaces = ['Component']
    candidate.states = ['showing', 'visible']
    candidate.rect = SimpleNamespace(x=0, y=0, width=1124, height=822)
    app, frame, owner = nested_fixture([first, candidate])
    result = reader.nested_topology([app], 123, API, owner)
    assert result['complete'] is False
    assert result['truncation'] == limit + '_limit'
    assert len(result['candidate_indices']) == 1
    assert result['nodes'][result['candidate_indices'][0]]['name'] == 'Warning'
    assert len(result['nodes']) <= reader.MAX_NODES
    assert reader.valid_nested_topology(result, owner)


def test_nested_total_scheduled_nodes_and_queue_are_bounded(monkeypatch):
    reads = []
    class Counted(Node):
        def getChildAtIndex(self, index):
            reads.append(index)
            return super().getChildAtIndex(index)
    children = [Counted('panel', children=[Node()] * 64) for _ in range(64)]
    app, frame, owner = nested_fixture(children)
    monkeypatch.setattr(reader, 'MAX_NODES', 10)
    result = reader.nested_topology([app], 123, API, owner)
    assert len(result['nodes']) == 10
    assert reads == []  # Scheduled sibling budget leaves no room for descendants.
    assert result['complete'] is False and result['truncation'] == 'node_limit'
