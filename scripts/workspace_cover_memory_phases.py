"""Marked synthetic service only: bounded, read-only allocation phase counters."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
from pathlib import Path
import sys
from threading import Lock

_ACTIVE = ContextVar('cover_memory_phase_fixture', default=None)
_LOCK = Lock()
_INSTALLED = False
_COUNT = 0
_MAX_RECORDS = 256
_STAT_KEYS = ('anon','file','file_dirty','file_writeback','slab')


def _record(label):
    global _COUNT
    active = _ACTIVE.get()
    if active is None:
        return
    from scripts.workspace_cover_service_observations import require
    namespace = require(*active)
    with _LOCK:
        if _COUNT >= _MAX_RECORDS:
            return
        _COUNT += 1
        sequence = _COUNT
    root = Path('/sys/fs/cgroup')
    try:
        def bounded(name):
            with (root/name).open('r') as source:
                value=source.read(16385)
            if len(value)>16384:raise ValueError('Oversize cgroup counter')
            return value
        stat=dict(line.split() for line in bounded('memory.stat').splitlines())
        events=dict(line.split() for line in bounded('memory.events').splitlines())
        receipt={'sequence':sequence,'phase':label,
                 'current':int(bounded('memory.current')),
                 'peak':int(bounded('memory.peak')),
                 'stat':{key:int(stat[key]) for key in _STAT_KEYS if key in stat},
                 'oom_kill':int(events.get('oom_kill',0))}
    except (OSError,ValueError,KeyError):
        receipt={'sequence':sequence,'phase':label,'counters':'unavailable'}
    from scripts import workspace_cover_process_observations as process
    try:
        receipt.update(process.processes())
        receipt.update(process.ownership(namespace[0]))
    except (OSError, ValueError, TypeError):
        receipt['process_counters'] = 'unavailable'
    try:
        process.append(active[0], receipt)
    except (OSError, ValueError, TypeError):
        receipt['durable_phase'] = 'unavailable'
    print('COVER_MEMORY_PHASE '+json.dumps(receipt,sort_keys=True),file=sys.stderr,flush=True)


def _safe_record(label):
    # Diagnostic counter/namespace/output failures must not replace an action's
    # result or original error. The ordinary application still owns all guards.
    try:
        _record(label)
    except Exception:
        pass


def _wrap(owner, name, label, predicate=None):
    original=getattr(owner,name)
    @wraps(original)
    def observed(*args,**kwargs):
        enabled=_ACTIVE.get() is not None and (predicate is None or predicate(args,kwargs))
        if enabled:_safe_record(label+':before')
        try:return original(*args,**kwargs)
        finally:
            if enabled:_safe_record(label+':after')
    setattr(owner,name,observed)


def _install():
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:return
        import streamlit as st
        from app import monthly_report_cover_ui as ui
        from app import monthly_report_cover_originals as originals
        from app import monthly_report_cover_recovery as recovery
        _wrap(st,'file_uploader','native-registration',
              lambda a,k:(a[0] if a else k.get('label'))=='New photograph for this report')
        _wrap(ui,'_reuse_cover_upload','same-upload-reuse')
        _wrap(ui,'read_picture_upload','immutable-upload-read')
        _wrap(originals,'store_cover_original','original-archive')
        _wrap(recovery,'_normal_candidate','normal-admission')
        _INSTALLED=True


@contextmanager
def observe(base,token):
    from scripts.workspace_cover_service_observations import require
    try:
        require(base,token)  # Must fail before installing anything outside QA.
    except ValueError as exc:
        # First render creates the isolated namespace. Do not observe or install
        # anything until that ordinary initialization has completed.
        if str(exc) == 'History observations require an existing isolated namespace.':
            yield
            return
        # isolated() binds the cookie immediately; the normal storage boundary
        # binds its generation later in render. Setup may be read-only before
        # that first access. Every emitted phase still runs full require().
        if str(exc) != 'Cover service QA namespace mismatch':
            raise
        from app import monthly_report_testing as testing
        from scripts.workspace_history_observations import namespace
        _, identity, _ = namespace(base,token)
        if testing.scope() != identity or testing.generation() is not None:
            raise
    _install()
    marker=_ACTIVE.set((base,token))
    try:yield
    finally:_ACTIVE.reset(marker)
