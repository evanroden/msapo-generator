"""Opt-in, bounded passive receipts for disposable synthetic simplicity QA only."""
from functools import wraps
from hashlib import sha256
import json
import os
from pathlib import Path
import time

LIMIT = 192

def digest(value):
    return sha256(str(value).encode()).hexdigest()

def report_receipt(draft, blocks=None):
    if draft is None:
        return None
    blocks = blocks if blocks is not None else {b.key: b for b in draft.blocks}
    block = blocks.get('activity_summary')
    return {'report': digest(draft.fingerprint), 'profile': digest(draft.profile.key),
            'contract': digest(getattr(draft.profile, 'contract', '')),
            'month': digest(draft.period.key), 'block': digest(block.fingerprint) if block else None,
            'sources': [{'id': digest(s.id), 'revision': digest(s.fingerprint)} for s in draft.sources[:16]]}

def snapshot(state):
    rows = []
    for key, draft in state.items():
        if not (key.startswith('report_guided_') and key.endswith('_draft') and hasattr(draft, 'blocks')):
            continue
        prefix = key[:-6]
        pending = state.get(prefix + '_pending_accepted_workorders')
        row = {'scope': digest(prefix), 'draft': report_receipt(draft),
               'pending': bool(pending), 'manager': bool(state.get(prefix + '_batch_files_open')),
               'open_request': bool(state.get(prefix + '_batch_files_open_open_request')),
               'close_request': bool(state.get(prefix + '_batch_files_open_close_request')),
               'refresh': bool(state.get(prefix + '_period_editor_refresh')),
               'resolution': [{'id': digest(k), 'resolved': bool(v)} for k,v in
                              list(state.get(prefix + '_source_manager_resolution', {}).items())[:16]]}
        if isinstance(pending, dict):
            row['request'] = {k: digest(pending[k]) for k in
                              ('contract','profile','month','expected','scope','source_id','reference','text') if k in pending}
            row['request']['reference_revision'] = digest(str(pending.get('reference','')).split(':')[-1])
            epoch = state.get(prefix + '_rich_text_epoch')
            if epoch is not None:
                from app.monthly_report_upload_ui import _signature
                scope = _signature((prefix, epoch, state.get('_monthly_qa_generation', '')))
                row['action_scope'] = digest(scope)
        rows.append(row)
        if len(rows) == 4:
            break
    return rows

def trace(callback, state, record, kind, render=False):
    @wraps(callback)
    def wrapped(*args, **kwargs):
        def emit(phase, result=None):
            try:
                row = {'kind': kind, 'phase': phase, 'at_ns': time.time_ns(), 'state': snapshot(state())}
                if render and len(args) >= 3:
                    row['render'] = report_receipt(args[0], args[2])
                    if result is not None:
                        row['result'] = report_receipt(result[0], result[1])
                record(row)
            except Exception:
                pass
        emit('before')
        try:
            result = callback(*args, **kwargs)
        except BaseException:
            emit('exception')
            raise
        emit('after', result)
        return result
    return wrapped

def allowed():
    if os.environ.get('EPC_MONTHLY_SIMPLICITY_DIAGNOSTICS') != '1':
        return False
    if not all(os.environ.get(k) == '1' for k in
               ('EPC_MONTHLY_DOM_FIXTURE','EPC_MONTHLY_FRESH_TASK','EPC_MONTHLY_SIMPLICITY_TASK')):
        raise ValueError('Simplicity diagnostics require all disposable task flags')
    from scripts.workspace_browser_observations import require_synthetic_root
    base = Path(os.environ.get('EPC_DATA_DIR','')).resolve()
    require_synthetic_root(base)
    from app.memory import _data_dir
    if _data_dir().resolve() != base:
        raise ValueError('Simplicity diagnostic storage mismatch')
    return True

def install(st, guided, record=None):
    if not allowed() or getattr(st.button, '_qa_simplicity_delivery', False):
        return
    count = 0
    def bounded(row):
        nonlocal count
        if count >= LIMIT:
            return
        count += 1
        if record is None:
            print('ENFRA_QA_SIMPLICITY ' + json.dumps(row), flush=True)
        else:
            record(row)
    state = lambda: st.session_state.filtered_state if hasattr(st.session_state, 'filtered_state') else dict(st.session_state)
    native_button = st.button
    @wraps(native_button)
    def button(*args, **kwargs):
        callback = kwargs.get('on_click')
        if (args and args[0] == 'Add totals to summary' and callable(callback)
                and callback.__module__ == 'app.monthly_report_upload_ui'
                and callback.__name__ == 'accept_workorders'):
            kwargs = dict(kwargs, on_click=trace(callback, state, bounded, 'accept-callback'))
        return native_button(*args, **kwargs)
    button._qa_simplicity_delivery = True
    native_render = guided._render_ordered_section
    traced_render = trace(native_render, state, bounded, 'activity-render', render=True)
    @wraps(native_render)
    def render(*args, **kwargs):
        if len(args) > 1 and getattr(args[1], 'key', None) == 'activity':
            return traced_render(*args, **kwargs)
        return native_render(*args, **kwargs)
    st.button = button
    guided._render_ordered_section = render

class Wire:
    """Only the accepted-totals widget identity and trigger values; no raw frames."""
    def __init__(self):
        self.rows = []
        self.ids = set()
    def message(self, direction, raw):
        try:
            from streamlit.proto.BackMsg_pb2 import BackMsg
            from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
            if not isinstance(raw, bytes) or len(self.rows) >= LIMIT:
                return
            msg = ForwardMsg() if direction == 'received' else BackMsg()
            msg.ParseFromString(raw)
            row = {'direction': direction, 'at_ns': time.time_ns()}
            if direction == 'received' and msg.WhichOneof('type') == 'delta':
                element = msg.delta.new_element
                if element.WhichOneof('type') != 'button' or element.button.label != 'Add totals to summary':
                    return
                identity = digest(element.button.id)
                self.ids.add(identity)
                row.update(kind='button', id=identity, path=list(msg.metadata.delta_path))
            elif direction == 'sent' and msg.WhichOneof('type') == 'rerun_script':
                row.update(kind='rerun', fragment=digest(msg.rerun_script.fragment_id),
                           actions=[{'id': digest(w.id), 'pressed': w.trigger_value}
                                    for w in msg.rerun_script.widget_states.widgets
                                    if w.WhichOneof('value') == 'trigger_value' and digest(w.id) in self.ids][:16])
            else:
                return
            self.rows.append(row)
        except Exception:
            pass
    def attach(self, page):
        from urllib.parse import urlparse
        def connected(socket):
            parsed = urlparse(socket.url)
            if parsed.hostname != '127.0.0.1' or parsed.port != 8543:
                return
            socket.on('framereceived', lambda raw: self.message('received', raw))
            socket.on('framesent', lambda raw: self.message('sent', raw))
        page.on('websocket', connected)

def safe_trace(path):
    """Retain only bounded, paired action timing; never raw trace parameters.

    Non-action trace traffic cannot consume the action budget. Any excess or
    incomplete action is explicit rather than silently disappearing.
    """
    from zipfile import ZipFile
    allowed = {'click', 'press', 'setInputFiles', 'goto', 'fill'}
    pairs, pending = [], {}
    result = {'pairs': pairs, 'record_limit': LIMIT, 'overflow_calls': 0,
              'unpaired_calls': 0, 'skipped_oversize_entries': 0,
              'skipped_oversize_lines': 0, 'malformed_lines': 0}
    try:
        with ZipFile(path) as archive:
            for info in archive.infolist():
                if not info.filename.endswith('.trace'):
                    continue
                if info.file_size > 8 * 1024 * 1024:
                    result['skipped_oversize_entries'] += 1
                    continue
                with archive.open(info) as source:
                    for line in source:
                        if len(line) > 256 * 1024:
                            result['skipped_oversize_lines'] += 1
                            continue
                        try:
                            value = json.loads(line)
                        except (ValueError, UnicodeError):
                            result['malformed_lines'] += 1
                            continue
                        if not isinstance(value, dict):
                            result['malformed_lines'] += 1
                            continue
                        kind = value.get('type')
                        call = digest(value.get('callId', ''))
                        if kind == 'before' and value.get('method') in allowed:
                            if len(pairs) + len(pending) >= LIMIT // 2:
                                result['overflow_calls'] += 1
                                continue
                            pending[call] = {'call': call, 'method': value['method'],
                                'before': {'startTime': value.get('startTime')
                                           if type(value.get('startTime')) in (int, float) else None}}
                        elif kind == 'after' and call in pending:
                            pair = pending.pop(call)
                            pair['after'] = {'endTime': value.get('endTime')
                                             if type(value.get('endTime')) in (int, float) else None}
                            pairs.append(pair)
        result['unpaired_calls'] = len(pending)
        result['truncated'] = any(result[key] for key in
            ('overflow_calls', 'unpaired_calls', 'skipped_oversize_entries',
             'skipped_oversize_lines', 'malformed_lines'))
        return result
    finally:
        Path(path).unlink(missing_ok=True)
