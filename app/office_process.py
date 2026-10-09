"""Run one office process tree to completion before its conversion lease ends."""
from __future__ import annotations

import os
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence

_DIAGNOSTIC_BYTES = 16 * 1024
_CLEANUP_SECONDS = 5


class OfficeCleanupPending(RuntimeError):
    """A previous process still owns resources; do not admit another converter."""


def _marker() -> Path:
    from app.monthly_report_library import _root
    folder = _root() / 'render-jobs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / '.active-office.json'


def _boot_id() -> str:
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip() + ':' + os.readlink('/proc/self/ns/pid')
    except OSError:
        return ''


def require_idle() -> None:
    """Called under the cross-process lease before *any* office job is admitted."""
    marker = _marker()
    try:
        with marker.open() as stream:
            raw = stream.read(1025)
        if len(raw) > 1024:
            raise ValueError('Oversized process marker')
        value = json.loads(raw)
        pid = value['pid']
        if type(pid) is not int or pid <= 1:
            raise ValueError('Invalid process marker')
        previous_boot = value.get('boot', '')
        current_boot = _boot_id()
        restarted = bool(previous_boot and current_boot and previous_boot != current_boot)
        if not restarted and _group_running(pid):
            raise OfficeCleanupPending('The previous PDF conversion is still stopping. Your saved work is unchanged; try again shortly.')
        marker.unlink()
    except FileNotFoundError:
        pass
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise OfficeCleanupPending('PDF conversion cleanup could not be checked. Your saved work is unchanged.') from exc


def _record(pid: int) -> None:
    marker = _marker()
    temporary = marker.with_suffix('.tmp')
    temporary.write_text(json.dumps({'pid': pid, 'boot': _boot_id()}))
    temporary.replace(marker)


def _clear(pid: int) -> None:
    marker = _marker()
    try:
        if json.loads(marker.read_text()).get('pid') == pid:
            marker.unlink()
    except FileNotFoundError:
        pass


def _group_running(group: int) -> bool:
    # Linux keeps orphan zombies until init reaps them. They cannot execute or
    # write files and must not hold the renderer lease indefinitely.
    if sys.platform != 'linux':
        try:
            os.kill(group, 0)
            return True
        except ProcessLookupError:
            return False
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group and fields[0] not in {'Z', 'X'}:
                return True
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, IndexError):
            continue
    return False


def _stop(process: subprocess.Popen) -> None:
    if os.name == 'posix':
        deadline = time.monotonic() + _CLEANUP_SECONDS
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise OfficeCleanupPending('The previous PDF conversion is still stopping. Try again shortly.') from exc
        if sys.platform == 'linux':
            # SIGKILL delivery is asynchronous. Do not release the shared lease
            # while a descendant still has code/IO running. No pipe-drain wait:
            # the private log files below cannot be held open by an orphan pipe.
            while _group_running(process.pid):
                if time.monotonic() >= deadline:
                    raise OfficeCleanupPending('The previous PDF conversion is still stopping. Try again shortly.')
                time.sleep(.01)
    elif process.poll() is None:
        # Windows is not a production/CI renderer. Preserve process-tree cleanup
        # there without signaling the application's own console process group.
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=True)
        process.wait(timeout=_CLEANUP_SECONDS)


def run_office(command: Sequence[str], *, timeout: float = 120) -> subprocess.CompletedProcess:
    """Capture bounded diagnostics and clean descendants on success or failure.

    The caller owns the conversion lease and disposable output directory. A
    TimeoutExpired is raised only after the launched process tree has stopped.
    """
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(list(command), stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr,
                                   start_new_session=os.name == 'posix')
        try:
            _record(process.pid)
            process.wait(timeout=timeout)
        finally:
            # If cleanup cannot finish, leave the marker. Other processes check
            # it under the shared lease instead of launching an overlapping job.
            _stop(process)
            _clear(process.pid)
        stdout.seek(0); stderr.seek(0)
        return subprocess.CompletedProcess(command, process.returncode,
            stdout.read(_DIAGNOSTIC_BYTES).decode('utf-8', 'replace'),
            stderr.read(_DIAGNOSTIC_BYTES).decode('utf-8', 'replace'))
