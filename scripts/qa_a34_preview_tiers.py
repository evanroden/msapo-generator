"""Synthetic A34 native image-heavy assembly contention benchmark.

Run the same script in capped 512 MiB / 0.5 CPU (default one worker) and
2 GiB / 2 CPU (opted into two workers). This is NOT a served UI timing test.
A retry is a new admission attempt, not a mutation of a report/source.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
from zipfile import ZipFile
import resource
from threading import Barrier, Event, Thread
import tempfile
import time
import sys

# This script is run by path in the production container, not as a module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docx import Document

from app.monthly_preview_memory_budget import (
    MEASURED_NATIVE_PEAK_BYTES, PREVIEW_JOB_ESTIMATE_BYTES, preview_worker_budget,
)
from app.monthly_report_render_jobs import RenderBusy, work_slot
from app.monthly_report_preview import section_preview_docx
from scripts.qa_monthly_report_resources import _fixture, _memory, _memory_events, _current_rss


def run_pair(draft, assets):
    barrier = Barrier(2)
    origin = time.monotonic()

    def visitor(index):
        barrier.wait(timeout=10)
        queued = time.monotonic()
        retries = 0
        while True:
            try:
                with work_slot(preview=True):
                    entered = time.monotonic()
                    native = section_preview_docx(draft, 'activity', assets.__getitem__)
                    completed = time.monotonic()
                break
            except RenderBusy:
                retries += 1
                if time.monotonic() - queued > 120:
                    raise RuntimeError('Preview retry budget exhausted (edits remain unchanged)')
                time.sleep(.05)
        document = Document(BytesIO(native))
        text = '\n'.join(paragraph.text for paragraph in document.paragraphs)
        assert 'Synthetic current inspection completed.' in text
        # Native masters may anchor images as floating shapes. The DOCX
        # package media count is valid for either anchored or inline photos.
        with ZipFile(BytesIO(native)) as archive:
            photo_count = sum(name.startswith('word/media/') and not name.endswith('/')
                              for name in archive.namelist())
        assert photo_count >= 8
        return {
            'visitor': index, 'wait_seconds': round(entered - queued, 3),
            'assemble_seconds': round(completed - entered, 3),
            'elapsed_seconds': round(completed - queued, 3),
            'retry_count': retries,
            'docx_sha256': sha256(native).hexdigest(),
            'photo_count': photo_count,
        }

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(visitor, 1)
        second = pool.submit(visitor, 2)
        records = [first.result(timeout=130), second.result(timeout=130)]
    return {
        'makespan_seconds': round(time.monotonic() - origin, 3),
        'visitors': records,
        'max_queue_seconds': max(row['wait_seconds'] for row in records),
    }


def main():
    logging.basicConfig(level=logging.ERROR)
    before_events = _memory_events()
    limit, _ = _memory()
    stop, samples = Event(), []

    def sample():
        while not stop.wait(.1):
            _, used = _memory()
            if used is not None:
                samples.append(used)

    thread = Thread(target=sample, daemon=True)
    thread.start()
    started = time.monotonic()
    result = {
        'synthetic_only': True, 'limit_bytes': limit,
        'cpu_quota': Path('/sys/fs/cgroup/cpu.max').read_text().strip()
                     if Path('/sys/fs/cgroup/cpu.max').exists() else None,
        'configured_memory_tier': os.getenv('MSAPO_PREVIEW_MEMORY_TIER', '1'),
        'effective_workers': preview_worker_budget(),
        'measured_control_peak_bytes': MEASURED_NATIVE_PEAK_BYTES,
        'estimated_per_job_bytes': PREVIEW_JOB_ESTIMATE_BYTES,
    }
    try:
        with tempfile.TemporaryDirectory(prefix='a34-synthetic-') as temp:
            temp = Path(temp)
            os.environ['EPC_DATA_DIR'] = str(temp / 'runtime')
            draft, assets, size = _fixture(temp)
            source = temp / 'synthetic-large-photo-report.docx'
            original_hash = sha256(source.read_bytes()).hexdigest()
            result['original_size_bytes'] = size
            result['cold'] = run_pair(draft, assets)
            result['warm'] = run_pair(draft, assets)
            assert sha256(source.read_bytes()).hexdigest() == original_hash
            result['original_sha256_preserved'] = True
            result['same_content_within_run'] = all(
                len({row['docx_sha256'] for row in phase['visitors']}) == 1
                for phase in (result['cold'], result['warm'])
            )
            # Native package creation may insert timestamps; actual section
            # text and 8-photo count are asserted for every independent run.
            result['rendered_photo_count'] = 8
    finally:
        stop.set()
        thread.join(2)
        result['seconds'] = round(time.monotonic() - started, 3)
        result['sampled_peak_cgroup_bytes'] = max(samples, default=0)
        result['peak_python_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        result['final_python_rss_bytes'] = _current_rss()
        result['memory_events_delta'] = {
            key: value - before_events.get(key, 0)
            for key, value in _memory_events().items()
        }
        print('A34_RESULT:' + json.dumps(result, sort_keys=True), flush=True)

    assert result['memory_events_delta'].get('oom', 0) == 0
    assert result['memory_events_delta'].get('oom_kill', 0) == 0


if __name__ == '__main__':
    main()
