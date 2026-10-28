"""Marked-fixture-only, bounded observations and real-lock contention control.

Never mutates a report, original, cache, revision or decoder policy. The optional
control holds the actual global work slot for at most fifteen seconds; it is
controlled contention, not a simulated concurrent export.
"""
from dataclasses import asdict
from hashlib import sha256
from html import escape
import json
import os
from threading import Event, Thread
import time


def require(base, token):
    from scripts.workspace_history_observations import namespace
    from app import monthly_report_testing as testing
    if (os.environ.get('EPC_MONTHLY_COVER_SERVICE_TASK') != '1'
            or os.environ.get('EPC_MONTHLY_DOM_FIXTURE') != '1'):
        raise ValueError('Cover service QA requires the marked isolated fixture')
    target, identity, generation = namespace(base, token)
    if (testing.scope(), testing.generation()) != (identity, generation):
        raise ValueError('Cover service QA namespace mismatch')
    return target, identity, generation


def contention_controls(base, token):
    require(base, token)
    import streamlit as st
    import sys
    from app.monthly_report_render_jobs import work_slot, RenderBusy
    st.button('QA refresh cover service receipt')  # Native rerun, no report mutation.
    key = '_cover_service_qa_contention'
    held = getattr(sys, key, None)
    if st.button('QA hold real report work slot for 15 seconds'):
        if held and held['thread'].is_alive():
            raise ValueError('Synthetic contention already active')
        ready, release = Event(), Event()
        held = {'owner': token, 'ready': ready, 'release': release, 'acquired': False}
        def run():
            try:
                with work_slot(wait_seconds=0):
                    held['acquired'] = True
                    held['deadline'] = time.monotonic() + 15
                    ready.set()
                    release.wait(15)
            except RenderBusy:
                ready.set()
            finally:
                release.set()
        held['thread'] = Thread(target=run, daemon=True)
        setattr(sys, key, held)
        held['thread'].start()
        if not ready.wait(2) or not held['acquired']:
            raise ValueError('Synthetic contention did not acquire actual work slot')
    if held and held['owner'] == token:
        if st.button('QA release controlled report contention'):
            held['release'].set()
            held['thread'].join(2)
        st.caption('QA controlled contention active: ' + str(
            held['acquired'] and not held['release'].is_set()).lower())


def emit(base, token):
    _, identity, generation = require(base, token)
    import streamlit as st
    from app import monthly_report_qa_fixture as fixture, monthly_report_library as library
    from app.monthly_report_testing_ui import _working_report
    from app.monthly_report_active_work import load
    from scripts.qa_cover_recovery_resources import cgroup_value, oom_kills
    from app.monthly_report_editor import _signature
    saved = library.load_snapshot(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
    sequence_key = '_cover_service_qa_sequence'
    sequence = st.session_state.get(sequence_key, 0) + 1
    st.session_state[sequence_key] = sequence
    receipt = {'sequence': sequence, 'scope': identity, 'generation': generation,
               'revision': saved.revision if saved else 0,
               'memory': {name: cgroup_value('memory.' + name) for name in ('current', 'peak', 'max')},
               'oom_kill': oom_kills(), 'working': None, 'durable': None}
    if saved:
        draft = _working_report(saved)
        active = load(token, fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        def state(report):
            block = next((b for b in report.blocks if b.key == 'cover_photo'), None)
            return {'fingerprint': report.fingerprint, 'cover': asdict(block) if block else None,
                    'sources': [s.fingerprint for s in report.sources],
                    'request': asdict(report.cover_recovery_request) if report.cover_recovery_request else None}
        prefix = 'report_guided_' + _signature((fixture.CONTRACT, fixture.profile().key, fixture.PERIOD.key))
        assets = st.session_state.get(prefix + '_assets', {})
        receipt.update(working=state(draft), durable=state(active.draft if active else saved.draft),
            assets={ref: {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()} for ref, raw in assets.items()})
        versions, older = library.snapshot_history(fixture.CONTRACT, fixture.profile().key, fixture.PERIOD)
        if older:
            raise ValueError('Synthetic history exceeded its bounded page')
        receipt['versions'] = [(v.revision, v.generated_at) for v in versions]
    # UploadedFile.size is metadata. Do not materialize/copy held 64 MiB buffers.
    from streamlit.runtime.uploaded_file_manager import UploadedFile
    receipt['held_upload_sizes'] = sorted(value.size for value in st.session_state.values()
        if isinstance(value, UploadedFile))
    encoded = json.dumps(receipt, sort_keys=True)
    if len(encoded) > 32768:
        raise ValueError('Cover service receipt exceeded its bound')
    require(base, token)
    st.html('<span hidden data-cover-service-receipt="' + escape(encoded, quote=True) + '"></span>')
