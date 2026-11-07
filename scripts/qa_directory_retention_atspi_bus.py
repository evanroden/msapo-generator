"""Private desktop boundaries for observation only; no native input interfaces."""
from pathlib import Path
import json
import os
import re
import stat
import subprocess
from xml.sax.saxutils import escape

from scripts.qa_directory_retention_local import guarded_root, child_environment, SafetyStop
from scripts import qa_directory_retention_headed as headed
from scripts import qa_directory_retention_atspi_read as reader

RUNTIME = 'owned-runtime'
MAX_BYTES = 131072


def private_directory(path):
    if (path.is_symlink() or not path.is_dir() or path.resolve() != path
            or path.stat().st_uid != os.getuid()
            or stat.S_IMODE(path.stat().st_mode) != 0o700):
        raise SafetyStop('Private runtime directory was not proven')
    return path


def prepare_bus(base):
    base = guarded_root(base)
    runtime = base / RUNTIME
    runtime.mkdir(mode=0o700)
    services = runtime / 'services'
    services.mkdir(mode=0o700)
    launcher = Path('/usr/libexec/at-spi-bus-launcher')
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise SafetyStop('Official Ubuntu accessibility bus launcher is missing')
    (services / 'org.a11y.Bus.service').write_text(
        '[D-BUS Service]\nName=org.a11y.Bus\nExec=' + str(launcher) + ' --launch-immediately\n')
    # No standard service directories or inherited session configuration.
    config = runtime / 'session.conf'
    config.write_text('''<busconfig>
<type>session</type><listen>unix:path=''' + escape(str(runtime / 'session-bus')) + '''</listen>
<auth>EXTERNAL</auth><servicedir>''' + escape(str(services)) + '''</servicedir>
<policy context="default"><allow user="''' + str(os.getuid()) + '''"/>
<allow own="*"/><allow send_destination="*"/><allow receive_sender="*"/></policy>
</busconfig>''')
    return config


def launch_environment(base, commit):
    base = guarded_root(base)
    runtime = private_directory(base / RUNTIME)
    env = child_environment(base, commit)
    env.update(XDG_RUNTIME_DIR=str(runtime), NO_AT_BRIDGE='0', GTK_MODULES='atk-bridge',
               ACCESSIBILITY_ENABLED='1')
    return env


def validate_socket_address(address, runtime, exact=None):
    # Reject abstract sockets, multiple transports, escapes, alternate paths.
    match = re.fullmatch(r'unix:path=([^,;]+)(?:,guid=[0-9a-f]{32})?', address)
    if not match:
        raise SafetyStop('Private bus address syntax was not proven')
    path = Path(match[1])
    runtime = private_directory(runtime)
    if (not path.is_absolute() or path.resolve() != path or runtime not in path.parents
            or (exact is not None and path != exact)
            or not stat.S_ISSOCK(path.stat().st_mode)
            or path.stat().st_uid != os.getuid()):
        raise SafetyStop('Bus socket is not confined to the owned runtime')
    return address


def accessibility_environment(base, commit):
    base = guarded_root(base)
    env = headed.display_environment(base, commit)
    owned = launch_environment(base, commit)
    runtime = base / RUNTIME
    if os.environ.get('XDG_RUNTIME_DIR') != str(runtime):
        raise SafetyStop('Inherited runtime differs from the owned runtime')
    address = validate_socket_address(os.environ.get('DBUS_SESSION_BUS_ADDRESS', ''),
                                      runtime, runtime / 'session-bus')
    for name in ('XDG_RUNTIME_DIR', 'NO_AT_BRIDGE', 'GTK_MODULES', 'ACCESSIBILITY_ENABLED'):
        env[name] = owned[name]
    env['DBUS_SESSION_BUS_ADDRESS'] = address
    return env


def owned_pid(pid, binary):
    process = Path('/proc') / str(pid)
    if process.stat().st_uid != os.getuid() or (process / 'exe').resolve() != Path(binary):
        raise SafetyStop('Dialog PID is not the pinned browser owned by this uid')
    current = pid
    for _ in range(16):
        status = (Path('/proc') / str(current) / 'status').read_text()
        match = re.search(r'^PPid:\s+(\d+)$', status, re.M)
        if not match:
            break
        current = int(match[1])
        if current == os.getpid():
            return
        if current <= 1:
            break
    raise SafetyStop('Dialog PID is not a descendant of this observation worker')


def dialog_owner(metadata, binary):
    windows = metadata['windows']
    dialogs = [w for w in windows if '_NET_WM_WINDOW_TYPE(ATOM) = _NET_WM_WINDOW_TYPE_DIALOG\n' in w['properties']]
    if len(dialogs) != 1:
        raise SafetyStop('Exactly one owned native dialog is required')
    dialog = dialogs[0]
    props = dialog['properties']
    transient = re.search(r'WM_TRANSIENT_FOR\(WINDOW\): window id # (0x[0-9a-f]+)', props)
    pid = re.search(r'_NET_WM_PID\(CARDINAL\) = ([0-9]+)', props)
    if not transient or not pid or 'WM_CLASS(STRING) = "chrome", "Chrome"' not in props:
        raise SafetyStop('Native GTK dialog identity was not proven')
    parents = [w for w in windows if w['id'] == transient[1]]
    if (len(parents) != 1 or '_NET_WM_WINDOW_TYPE_NORMAL\n' not in parents[0]['properties']
            or not re.search(r'_NET_WM_PID\(CARDINAL\) = ' + pid[1] + r'\n', parents[0]['properties'])
            or '"Chromium-browser"' not in parents[0]['properties']):
        raise SafetyStop('Native dialog is not transient for the same browser PID')
    owned_pid(int(pid[1]), binary)
    geometry = re.search(r'^\s*' + re.escape(dialog['id'])
        + r' "([^"\n]{1,256})": [^\n]+? (\d+)x(\d+)[+-]\d+[+-]\d+\s+([+-]\d+)([+-]\d+)\s*$',
        metadata.get('window_tree', ''), re.M)
    if not geometry:
        raise SafetyStop('Native dialog title and screen bounds were not proven')
    width, height, x, y = map(int, geometry.groups()[1:])
    if not (0 < width <= 32768 and 0 < height <= 32768 and abs(x) <= 32768 and abs(y) <= 32768):
        raise SafetyStop('Native dialog screen bounds exceeded limit')
    return {'pid': int(pid[1]), 'window': dialog['id'], 'transient_for': transient[1],
            'title': geometry[1], 'screen_rect': {'x': x, 'y': y, 'width': width, 'height': height}}


class AccessibilityDiagnosticFailure(SafetyStop):
    """A failed observation carrying separately validated diagnostic evidence."""


def capture_accessibility(env, owner):
    helper = Path(__file__).with_name('qa_directory_retention_atspi_read.py')
    # Parent timeout + helper alarm bound hung IPC. Helper bounds serialized output
    # before printing, so capture_output cannot accumulate an unbounded tree.
    result = subprocess.run(['/usr/bin/python3', '-I', str(helper), str(owner['pid'])],
        env=env, capture_output=True, timeout=20, check=False)
    if len(result.stdout) > MAX_BYTES or len(result.stderr) > 8192:
        raise SafetyStop('Accessibility helper output exceeded its bound')
    if result.returncode:
        try:
            failure = json.loads(result.stderr)
        except (ValueError, UnicodeError):
            failure = {}
        if (isinstance(failure, dict) and set(failure) == {'stage', 'reason', 'type'}
                and failure['stage'] in reader.STAGES and failure['reason'] in reader.REASONS
                and failure['type'] in reader.TYPES):
            error = AccessibilityDiagnosticFailure('Accessibility helper failed: ' + json.dumps(failure, sort_keys=True))
            if failure == {'stage': 'dialogs', 'reason': 'dialog_count', 'type': 'ObservationFailure'} and result.stdout:
                try:
                    topology = json.loads(result.stdout)
                except (ValueError, UnicodeError):
                    topology = None
                if not reader.valid_failure_topology(topology, owner['pid']):
                    raise SafetyStop('Invalid failure topology withheld')
                error.topology = topology
            raise error
        raise SafetyStop('Accessibility helper failed: unclassified exit (raw output withheld)')
    data = json.loads(result.stdout)
    if (data.get('pid') != owner['pid'] or data.get('observation_only') is not True
            or data.get('dialog_count') != 1 or not data.get('nodes')):
        raise SafetyStop('Accessibility helper did not prove one owned dialog')
    return data
