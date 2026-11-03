"""Transparent, read-only callback tracing for the isolated synthetic fixture."""
from functools import wraps
from hashlib import sha256
import json
import time


def trace_callback(callback, state, record):
    def snapshot(key):
        pending = state().get(key, {}).get('pending')
        return sha256(repr(pending).encode()).hexdigest()

    @wraps(callback)
    def traced(*args, **kwargs):
        # Diagnostics must neither prevent nor replace the native callback.
        def emit(phase):
            try:
                record({'phase': phase, 'at_ns': time.time_ns(),
                        'key_hash': sha256(str(args[0]).encode()).hexdigest(),
                        'action': kwargs.get('action', args[5] if len(args) > 5 else 'edit'),
                        'pending_hash': snapshot(args[0])})
            except Exception:
                pass  # A diagnostic sink cannot change native callback semantics.
        emit('before')
        try:
            return callback(*args, **kwargs)
        finally:
            emit('after')
    return traced


def install(row_ui, state):
    if getattr(row_ui._queue, '_qa_row_callback_trace', False):
        return
    traced = trace_callback(row_ui._queue, state,
                            lambda row: print('ENFRA_QA_ROW_CALLBACK ' + json.dumps(row), flush=True))
    traced._qa_row_callback_trace = True
    row_ui._queue = traced
