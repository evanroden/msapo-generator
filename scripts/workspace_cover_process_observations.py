"""Bounded numeric-only process evidence for the marked Cover service fixture.

No command lines, paths, user content, process signals, scheduling or polling.
The caller already owns the existing phase boundary and namespace check.
"""
import json
import os
from pathlib import Path
import stat

FILE_NAME = 'cover-memory-phases.jsonl'
MAX_FILE_BYTES = 512 * 1024
MAX_ROW_BYTES = 4096
MAX_PROCESSES = 16
MAX_TASKS = 128
MAX_FALLBACK_ENTRIES = 256
MAX_READ = 16384


def _directory(path):
    """Read-only no-follow walk; never create an evidence/namespace ancestor."""
    path = Path(path)
    if '..' in path.parts:
        raise ValueError('Invalid diagnostic directory')
    path = path.absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def validate(row):
    """Whitelist numeric evidence only, including when collecting after a crash."""
    allowed = {'sequence', 'phase', 'current', 'peak', 'stat', 'oom_kill', 'counters',
               'processes', 'process_scan_truncated', 'process_scan_unavailable',
               'heavy_slot_locked', 'conversion_slot_locked', 'current_thread_heavy',
               'current_thread_conversion', 'foreground_waiting', 'office_marker',
               'office_pid', 'process_counters', 'durable_phase'}
    number = lambda value: type(value) is int and 0 <= value < 2**63
    phases = {name + ':' + edge for name in ('native-registration', 'same-upload-reuse',
              'immutable-upload-read', 'original-archive', 'normal-admission') for edge in ('before', 'after')}
    if (type(row) is not dict or not set(row) <= allowed or not number(row.get('sequence'))
            or not 1 <= row['sequence'] <= 256 or row.get('phase') not in phases):
        raise ValueError('Invalid diagnostic row')
    for key, value in row.items():
        if key in ('sequence', 'phase'):
            continue
        if key == 'processes':
            if not isinstance(value, list) or len(value) > MAX_PROCESSES:
                raise ValueError('Invalid process evidence')
            for item in value:
                if (type(item) is not dict or set(item) != {'pid', 'ppid', 'rss', 'role'}
                        or any(not number(item[n]) for n in ('pid', 'ppid', 'rss'))
                        or item['role'] not in ('service', 'office', 'python-child', 'shell', 'other')):
                    raise ValueError('Invalid process evidence')
        elif key == 'stat':
            if (type(value) is not dict or not set(value) <= {'anon', 'file', 'file_dirty', 'file_writeback', 'slab'}
                    or not all(number(v) for v in value.values())):
                raise ValueError('Invalid memory evidence')
        elif key in ('process_scan_truncated', 'heavy_slot_locked', 'conversion_slot_locked',
                     'current_thread_heavy', 'current_thread_conversion'):
            if type(value) is not bool:
                raise ValueError('Invalid lock evidence')
        elif key == 'office_marker':
            if value not in ('missing', 'same-boot', 'unverified', 'unavailable'):
                raise ValueError('Invalid office evidence')
        elif key in ('counters', 'process_counters', 'durable_phase'):
            if value != 'unavailable':
                raise ValueError('Invalid diagnostic status')
        elif not number(value):
            raise ValueError('Invalid numeric evidence')
    return row


def _read(path, limit=MAX_READ):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Diagnostic input exceeded its bound')
    return raw.decode('ascii')


def processes(proc=Path('/proc'), pid=None):
    """One bounded walk of this service's thread-owned descendant processes."""
    pid = os.getpid() if pid is None else pid
    pending = [(pid, None)]
    seen = set()
    rows = []
    tasks = 0
    truncated = False
    unavailable = 0
    parents = None
    while pending and len(seen) < MAX_PROCESSES:
        current, expected_parent = pending.pop(0)
        if current in seen:
            continue
        seen.add(current)
        folder = proc / str(current)
        try:
            values = dict(line.split(':', 1) for line in _read(folder / 'status').splitlines() if ':' in line)
            comm = _read(folder / 'comm', 128).strip()
            rss = values.get('VmRSS', '0 kB').split()
            if len(rss) != 2 or rss[1] != 'kB':
                raise ValueError('Invalid RSS unit')
            parent = int(values['PPid'])
            if expected_parent is not None and parent != expected_parent:
                raise ValueError('Process parent changed during observation')
            rss_bytes = int(rss[0]) * 1024
            if parent < 0 or rss_bytes < 0:
                raise ValueError('Invalid numeric process counter')
            role = ('service' if current == pid else 'office' if comm in ('soffice.bin', 'soffice', 'oosplash')
                    else 'python-child' if comm in ('python', 'python3', 'python3.12')
                    else 'shell' if comm in ('sh', 'bash', 'dash') else 'other')
            rows.append({'pid': current, 'ppid': parent, 'rss': rss_bytes, 'role': role})
            if tasks >= MAX_TASKS:
                truncated = True
                continue
            missing_children = False
            with os.scandir(folder / 'task') as entries:
                for entry in entries:
                    if tasks >= MAX_TASKS:
                        truncated = True
                        break
                    tasks += 1
                    if not entry.name.isdecimal():
                        continue
                    try:
                        children = _read(Path(entry.path) / 'children', 4096).split()
                        for child in children:
                            if not child.isdecimal() or int(child) <= 0:
                                raise ValueError('Invalid child PID')
                            value = int(child)
                            if value not in seen and value not in (item[0] for item in pending):
                                if len(seen) + len(pending) >= MAX_PROCESSES:
                                    truncated = True
                                else:
                                    pending.append((value, current))
                    except (OSError, ValueError, UnicodeError):
                        unavailable += 1
                        missing_children = True
            # Some sandbox kernels expose status but omit task/children. Use
            # one bounded PPid-only snapshot in that case, never an unbounded
            # global walk, command-line read or repeated observation/poll.
            if missing_children:
                if parents is None:
                    parents = {}
                    with os.scandir(proc) as entries:
                        for index, entry in enumerate(entries):
                            if index >= MAX_FALLBACK_ENTRIES:
                                truncated = True
                                break
                            if not entry.name.isdecimal():
                                continue
                            try:
                                status = _read(Path(entry.path) / 'status')
                                owner = next(int(line.split(':', 1)[1]) for line in status.splitlines() if line.startswith('PPid:'))
                                parents[int(entry.name)] = owner
                            except (OSError, ValueError, UnicodeError, StopIteration):
                                unavailable += 1
                for child, owner in parents.items():
                    if owner == current and child not in seen and child not in (item[0] for item in pending):
                        if len(seen) + len(pending) >= MAX_PROCESSES:
                            truncated = True
                        else:
                            pending.append((child, current))
        except (OSError, ValueError, KeyError, UnicodeError):
            unavailable += 1
    return {'processes': rows, 'process_scan_truncated': truncated or bool(pending),
            'process_scan_unavailable': unavailable}


def ownership(target):
    """Read existing lock flags and only the current namespace's office PID.

    Do not call office_process._marker()/require_idle(): those create or clear
    records. Descriptor-relative reads reject links in every owned ancestor.
    """
    from app import monthly_report_render_jobs as jobs
    from app.office_process import _boot_id
    result = {'heavy_slot_locked': jobs._WORK_SLOT.locked(),
              'conversion_slot_locked': jobs._SLOT.locked(),
              'current_thread_heavy': bool(getattr(jobs._WORK_LOCAL, 'active', False)),
              'current_thread_conversion': bool(getattr(jobs._CONVERSION_LOCAL, 'active', False)),
              'foreground_waiting': int(jobs._FOREGROUND_WAITING),
              'office_marker': 'missing', 'office_pid': 0}
    descriptor = None
    try:
        descriptor = _directory(target)
        for part in ('monthly_reports', 'render-jobs'):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        marker = os.open('.active-office.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        try:
            info = os.fstat(marker)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024:
                raise ValueError('Invalid office record')
            raw = os.read(marker, 1025)
            if len(raw) > 1024:
                raise ValueError('Oversized office record')
            record = json.loads(raw)
            if (type(record) is not dict or set(record) != {'pid', 'boot'}
                    or type(record['pid']) is not int or record['pid'] <= 1
                    or not isinstance(record['boot'], str)):
                raise ValueError('Invalid office record')
            current = _boot_id()
            result.update(office_marker='same-boot' if current and record['boot'] == current else 'unverified',
                          office_pid=record['pid'])
        finally:
            os.close(marker)
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        result['office_marker'] = 'unavailable'
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return result


def append(base, row):
    """Durable one-row append, no-follow and hard bounded; never source bytes."""
    import fcntl
    raw = (json.dumps(validate(row), sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    if len(raw) > MAX_ROW_BYTES:
        raise ValueError('Diagnostic row exceeded its bound')
    parent = _directory(base)
    try:
        fd = os.open(FILE_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=parent)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                    or info.st_mode & 0o077 or info.st_size + len(raw) > MAX_FILE_BYTES):
                raise ValueError('Diagnostic file exceeded its bound or is linked')
            if os.write(fd, raw) != len(raw):
                raise OSError('Incomplete diagnostic write')
            os.fsync(fd)
            if info.st_size == 0:
                os.fsync(parent)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate diagnostic key')
        result[key] = value
    return result


def canonical(raw):
    """Validate every nested object and emit only canonical numeric records."""
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('Diagnostic file exceeded its bound')
    lines = raw.splitlines(keepends=True)
    if len(lines) > 256:
        raise ValueError('Too many diagnostic records')
    checked = []
    for index, line in enumerate(lines):
        if len(line) > MAX_ROW_BYTES:
            raise ValueError('Oversized diagnostic record')
        if not line.endswith(b'\n') and index == len(lines) - 1:
            # Never send unvalidated crash-tail bytes to the artifact receiver.
            import sys
            print('Cover process evidence: incomplete trailing row omitted', file=sys.stderr)
            break
        value = validate(json.loads(line, object_pairs_hook=_unique_pairs))
        checked.append((json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii'))
    result = b''.join(checked)
    if len(result) > MAX_FILE_BYTES:
        raise ValueError('Canonical evidence exceeded its bound')
    return result


def read_evidence(source):
    """Privileged side: exact private file, bounded read, validated stdout only."""
    source = Path(source)
    if source.name != FILE_NAME:
        raise ValueError('Unexpected diagnostic filename')
    parent = _directory(source.parent)
    try:
        try:
            fd = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return b''
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES
                or info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError('Invalid diagnostic file')
        raw = os.read(fd, MAX_FILE_BYTES + 1)
    finally:
        os.close(fd)
    return canonical(raw)


def receive(target, raw):
    """Unprivileged side: validate again, create a runner-owned private artifact."""
    target = Path(target)
    if target.name != FILE_NAME:
        raise ValueError('Unexpected diagnostic filename')
    checked = canonical(raw)
    if not checked:
        return
    parent = _directory(target.parent)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(checked)
    finally:
        os.close(parent)


def collect(source, target):
    """Local same-identity convenience; hosted collection separates identities."""
    receive(target, read_evidence(source))


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 3 or sys.argv[1] not in ('--emit', '--receive'):
        raise SystemExit('Expected --emit source or --receive target')
    if sys.argv[1] == '--emit':
        sys.stdout.buffer.write(read_evidence(sys.argv[2]))
    else:
        receive(sys.argv[2], sys.stdin.buffer.read(MAX_FILE_BYTES + 1))
