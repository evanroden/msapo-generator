"""System-Python AT-SPI read-only helper. No actions, focus changes, setters or value mutation APIs.

Invoked only after the parent proves X11 window ownership and pinned process
ancestry. A failed/partial traversal produces no evidence, never a fallback input.
"""
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys

MAX_NODES = 256
MAX_CHILDREN = 64
MAX_DEPTH = 16
MAX_STRING = 256
MAX_BYTES = 131072
MAX_RELATIONS = 16
MAX_LABELS = 8
STAGE = 'startup'
STAGES = {'startup', 'runtime', 'session_socket', 'accessibility_bus',
          'accessibility_socket', 'registry', 'applications', 'dialogs', 'nodes',
          'relations', 'serialization'}
REASONS = {'arguments', 'runtime_ownership', 'socket_syntax', 'socket_ownership',
           'missing_application', 'missing_owned_application', 'dialog_count',
           'ownership', 'label_bound', 'child_bound', 'tree_bound', 'relation_bound',
           'rectangle_bound', 'text_bound', 'byte_bound', 'timeout', 'capability',
           'filesystem', 'ipc_or_unexpected', 'protected_field', 'attribute_bound'}
TYPES = {'ObservationFailure', 'TimeoutError', 'ImportError', 'NotImplementedError',
         'OSError', 'IPCOrUnexpectedError'}


class ObservationFailure(RuntimeError):
    def __init__(self, reason):
        if reason not in REASONS:
            reason = 'ipc_or_unexpected'
        self.reason = reason
        super().__init__(reason)


def diagnostic(exc):
    if isinstance(exc, ObservationFailure):
        reason, kind = exc.reason, 'ObservationFailure'
    elif isinstance(exc, TimeoutError):
        reason, kind = 'timeout', 'TimeoutError'
    elif isinstance(exc, ImportError):
        reason, kind = 'capability', 'ImportError'
    elif isinstance(exc, NotImplementedError):
        reason, kind = 'capability', 'NotImplementedError'
    elif isinstance(exc, OSError):
        reason, kind = 'filesystem', 'OSError'
    else:
        reason, kind = 'ipc_or_unexpected', 'IPCOrUnexpectedError'
    return {'stage': STAGE if STAGE in STAGES else 'startup', 'reason': reason, 'type': kind}


def alarm_timeout(signum, frame):
    raise TimeoutError()



def bounded_text(value):
    value = str(value)
    if len(value) > MAX_STRING:
        raise ObservationFailure('label_bound')
    return value


def socket_address(address, runtime, exact=None):
    match = re.fullmatch(r'unix:path=([^,;]+)(?:,guid=[0-9a-f]{32})?', address)
    if not match:
        raise ObservationFailure('socket_syntax')
    path = Path(match[1])
    if (path.resolve() != path or runtime not in path.parents
            or (exact is not None and path != exact)
            or path.stat().st_uid != os.getuid() or not stat.S_ISSOCK(path.stat().st_mode)):
        raise ObservationFailure('socket_ownership')
    return address


def child_count(node):
    count = node.childCount
    if not isinstance(count, int) or not 0 <= count <= MAX_CHILDREN:
        raise ObservationFailure('child_bound')
    return count


def surface_metadata(node, pid, api):
    """Only one owned node's bounded metadata; never Text or relations."""
    if node is None or node.get_process_id() != pid:
        raise ObservationFailure('ownership')
    # GTK exposes password entries with PASSWORD_TEXT; also reject explicit
    # protected/password attributes rather than reading any text from them.
    attributes = node.get_attributes()
    if not isinstance(attributes, dict) or len(attributes) > 32:
        raise ObservationFailure('attribute_bound')
    for key, value in attributes.items():
        bounded_text(key)
        bounded_text(value)
    if (node.getRole() == api.ROLE_PASSWORD_TEXT
            or any(str(attributes.get(key, '')).lower() in {'true', '1', 'password'}
                   for key in ('protected', 'password', 'text-input-type', 'input-type'))):
        raise ObservationFailure('protected_field')
    state = node.getState()
    states = {name: bool(state.contains(getattr(api, 'STATE_' + name.upper())))
              for name in ('showing', 'visible', 'enabled', 'sensitive', 'focused', 'editable')}
    interfaces = api.listInterfaces(node)
    if len(interfaces) > 32:
        raise ObservationFailure('tree_bound')
    rectangle = None
    if 'Component' in interfaces and states['showing'] and states['visible']:
        bounds = node.queryComponent().getExtents(api.DESKTOP_COORDS)
        rectangle = {key: int(getattr(bounds, key)) for key in ('x', 'y', 'width', 'height')}
        if (any(abs(rectangle[key]) > 32768 for key in ('x', 'y'))
                or any(not 0 <= rectangle[key] <= 32768 for key in ('width', 'height'))):
            raise ObservationFailure('rectangle_bound')
    return {'role': bounded_text(node.getRoleName()), 'name': bounded_text(node.name),
            'children': child_count(node), 'states': states, 'screen_rect': rectangle}


def failure_topology(apps, pid, api, dialog_count):
    """Failure diagnostic only: owned apps plus immediate children, no recursion."""
    nodes = []
    for app in apps:
        if len(nodes) >= MAX_CHILDREN:
            raise ObservationFailure('tree_bound')
        parent = len(nodes)
        metadata = surface_metadata(app, pid, api)
        nodes.append({'index': parent, 'parent': None, **metadata})
        for offset in range(metadata['children']):
            if len(nodes) >= MAX_CHILDREN:
                raise ObservationFailure('tree_bound')
            child = app.getChildAtIndex(offset)
            nodes.append({'index': len(nodes), 'parent': parent,
                          **surface_metadata(child, pid, api)})
    return {'pid': pid, 'observation_only': True, 'diagnostic_only': True,
            'scope': 'owned-applications-and-immediate-children',
            'application_count': len(apps), 'dialog_count': dialog_count, 'nodes': nodes}


def valid_failure_topology(data, pid):
    """Validate helper JSON before retaining any failed-attempt diagnostic."""
    if (not isinstance(data, dict) or set(data) != {'pid', 'observation_only',
            'diagnostic_only', 'scope', 'application_count', 'dialog_count', 'nodes'}
            or data['pid'] != pid or data['observation_only'] is not True
            or data['diagnostic_only'] is not True
            or data['scope'] != 'owned-applications-and-immediate-children'
            or type(data['dialog_count']) is not int or not 0 <= data['dialog_count'] <= MAX_CHILDREN
            or data['dialog_count'] == 1 or type(data['application_count']) is not int
            or not 1 <= data['application_count'] <= MAX_CHILDREN
            or not isinstance(data['nodes'], list) or not 1 <= len(data['nodes']) <= MAX_CHILDREN):
        return False
    roots = []
    for index, node in enumerate(data['nodes']):
        if (not isinstance(node, dict) or set(node) != {'index', 'parent', 'role', 'name',
                'children', 'states', 'screen_rect'} or node['index'] != index
                or type(node['children']) is not int or not 0 <= node['children'] <= MAX_CHILDREN
                or any(not isinstance(node[key], str) or len(node[key]) > MAX_STRING for key in ('role', 'name'))
                or not isinstance(node['states'], dict)
                or set(node['states']) != {'showing', 'visible', 'enabled', 'sensitive', 'focused', 'editable'}
                or any(type(value) is not bool for value in node['states'].values())):
            return False
        if node['parent'] is None:
            roots.append(index)
        elif type(node['parent']) is not int or node['parent'] not in roots:
            return False
        rect = node['screen_rect']
        if rect is not None:
            if (not node['states']['showing'] or not node['states']['visible']
                    or not isinstance(rect, dict) or set(rect) != {'x', 'y', 'width', 'height'}
                    or any(type(value) is not int for value in rect.values())
                    or any(abs(rect[key]) > 32768 for key in ('x', 'y'))
                    or any(not 0 <= rect[key] <= 32768 for key in ('width', 'height'))):
                return False
    return len(roots) == data['application_count'] and all(
        sum(node['parent'] == root for node in data['nodes']) == data['nodes'][root]['children']
        for root in roots)


def collect(desktop, pid, dialog_roles, api):
    global STAGE
    STAGE = "applications"
    apps = []
    for index in range(child_count(desktop)):
        app = desktop.getChildAtIndex(index)
        if app is None:
            raise ObservationFailure('missing_application')
        # No names or descendants are inspected until PID ownership matches.
        if app.get_process_id() == pid:
            apps.append(app)
    if not apps:
        raise ObservationFailure('missing_owned_application')
    STAGE = "dialogs"
    dialogs = []
    for app in apps:
        for index in range(child_count(app)):
            node = app.getChildAtIndex(index)
            if node is None or node.get_process_id() != pid:
                raise ObservationFailure('ownership')
            if node.getRole() in dialog_roles:
                dialogs.append(node)
    if len(dialogs) != 1:
        failure = ObservationFailure('dialog_count')
        failure.topology = failure_topology(apps, pid, api, len(dialogs))
        raise failure
    STAGE = "nodes"
    nodes, owned_nodes = [], []
    def visit(node, parent, depth):
        if depth > MAX_DEPTH or len(nodes) >= MAX_NODES:
            raise ObservationFailure('tree_bound')
        if node is None or node.get_process_id() != pid:
            raise ObservationFailure('ownership')
        index = len(nodes)
        count = child_count(node)
        metadata = surface_metadata(node, pid, api)
        states = metadata['states']
        interfaces = api.listInterfaces(node)
        entry_text = None
        # Never inspect document text or non-editable labels through Text.
        # Password fields are deliberately excluded, even in this synthetic run.
        if (states['editable'] and node.getRole() in {api.ROLE_ENTRY, api.ROLE_TEXT}
                and 'EditableText' in interfaces and 'Text' in interfaces):
            text = node.queryText()
            length = text.characterCount
            if not isinstance(length, int) or not 0 <= length <= MAX_STRING:
                raise ObservationFailure('text_bound')
            entry_text = bounded_text(text.getText(0, length))
        nodes.append({'index': index, 'parent': parent, 'depth': depth,
                      **metadata,
                      'editable_entry_text': entry_text, 'labelled_by': []})
        owned_nodes.append(node)
        for offset in range(count):
            visit(node.getChildAtIndex(offset), index, depth + 1)
    visit(dialogs[0], None, 0)
    STAGE = 'relations'
    for index, node in enumerate(owned_nodes):
        relations = node.getRelationSet()
        if len(relations) > MAX_RELATIONS:
            raise ObservationFailure('relation_bound')
        for relation in relations:
            if relation.getRelationType() != api.RELATION_LABELLED_BY:
                continue
            count = relation.getNTargets()
            if not 0 <= count <= MAX_LABELS:
                raise ObservationFailure('relation_bound')
            for offset in range(count):
                target = relation.getTarget(offset)
                if (target is None or target.get_process_id() != pid
                        or target not in owned_nodes):
                    raise ObservationFailure('ownership')
                if len(nodes[index]['labelled_by']) >= MAX_LABELS:
                    raise ObservationFailure('relation_bound')
                nodes[index]['labelled_by'].append({
                    'index': owned_nodes.index(target), 'name': bounded_text(target.name)})
    return {'pid': pid, 'observation_only': True, 'dialog_count': 1, 'nodes': nodes}


def main():
    global STAGE
    # Hard stop for stalled IPC even if an individual accessibility getter hangs.
    signal.signal(signal.SIGALRM, alarm_timeout)
    signal.alarm(15)
    if len(sys.argv) != 2 or not re.fullmatch(r'[1-9][0-9]*', sys.argv[1]):
        raise ObservationFailure('arguments')
    STAGE = 'runtime'
    base = Path(os.environ['EPC_DATA_DIR'])
    runtime = Path(os.environ['XDG_RUNTIME_DIR'])
    if (runtime != base / 'owned-runtime' or runtime.resolve() != runtime
            or runtime.stat().st_uid != os.getuid()
            or stat.S_IMODE(runtime.stat().st_mode) != 0o700):
        raise ObservationFailure('runtime_ownership')
    STAGE = 'session_socket'
    session = socket_address(os.environ['DBUS_SESSION_BUS_ADDRESS'], runtime, runtime / 'session-bus')
    STAGE = 'accessibility_bus'
    import dbus
    connection = dbus.bus.BusConnection(session)
    proxy = connection.get_object('org.a11y.Bus', '/org/a11y/bus')
    address = str(proxy.GetAddress(dbus_interface='org.a11y.Bus', timeout=3))
    STAGE = 'accessibility_socket'
    os.environ['AT_SPI_BUS_ADDRESS'] = socket_address(address, runtime)
    STAGE = 'registry'
    import pyatspi
    data = collect(pyatspi.Registry.getDesktop(0), int(sys.argv[1]),
                   {pyatspi.ROLE_DIALOG, pyatspi.ROLE_FILE_CHOOSER}, pyatspi)
    data['bus_confined_to_owned_runtime'] = True
    STAGE = 'serialization'
    encoded = json.dumps(data).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ObservationFailure('byte_bound')
    sys.stdout.buffer.write(encoded)
    signal.alarm(0)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Failed role uniqueness stays failed. Retain only bounded shallow
        # owned-PID metadata, never entry text or a broader fallback traversal.
        topology = getattr(exc, 'topology', None)
        if isinstance(exc, ObservationFailure) and exc.reason == 'dialog_count' and topology is not None:
            encoded = json.dumps(topology).encode('utf-8')
            if len(encoded) <= MAX_BYTES:
                sys.stdout.buffer.write(encoded)
        # Only fixed allowlisted classifications, never raw exception text or values.
        print(json.dumps(diagnostic(exc)), file=sys.stderr)
        raise SystemExit(1)
