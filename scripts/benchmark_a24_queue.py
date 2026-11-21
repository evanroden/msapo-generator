#!/usr/bin/env python3
"""A24 admission-only synthetic benchmark (no DOCX, PDF or browser paint).

Legacy is a faithful reimplementation of the *admission decision* on main at
f0af99567223aea3375f60e671450048be2bf0a0 for automatic previews vs.
queued exports. New imports the actual PR queue. Durations simulate small/large
job lifetimes; 'cold/warm' is NOT an OS/application-cache measurement.
"""
import json
from pathlib import Path
import resource
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Event, Lock
from time import monotonic, process_time, sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.monthly_report_visible_queue import VisibleFirstQueue


def sample(mode, large_seconds, export_seconds, small_seconds):
    slot = Lock()
    foreground = [0]
    priority_lock = Condition()
    queue = VisibleFirstQueue()
    started, allow_large_to_finish = Event(), Event()
    clocks = {}
    start = monotonic()
    cpu = process_time()
    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    depths = []

    def large():
        slot.acquire()
        started.set()
        if not allow_large_to_finish.wait(4):
            raise TimeoutError('synthetic barrier')
        sleep(large_seconds)
        slot.release()

    def export():
        with priority_lock:
            foreground[0] += 1
        if mode == 'new':
            queue.acquire(slot, wait_seconds=4)
        else:
            slot.acquire()
        with priority_lock:
            foreground[0] -= 1
        sleep(export_seconds)
        clocks['export'] = monotonic() - start
        if mode == 'new':
            queue.release(slot)
        else:
            slot.release()

    def small(name):
        retries = 0
        while True:
            if mode == 'new':
                queue.acquire(slot, preview=True, owner=('pane', name),
                              revision='v1', wait_seconds=4)
                break
            # Main's background preview branch, without mutation/render work:
            # a waiting foreground export blocks the nonblocking slot claim.
            with priority_lock:
                admitted = not foreground[0] and slot.acquire(blocking=False)
            if admitted:
                break
            retries += 1
            sleep(.005)
        clocks[name + '_admitted'] = monotonic() - start
        sleep(small_seconds)
        clocks[name + '_ready'] = monotonic() - start
        clocks[name + '_retries'] = retries
        if mode == 'new':
            queue.release(slot)
        else:
            slot.release()

    with ThreadPoolExecutor(max_workers=4) as workers:
        big = workers.submit(large)
        if not started.wait(2):
            raise TimeoutError('large job did not start')
        other = workers.submit(export)
        deadline = monotonic() + 2
        while foreground[0] != 1 and monotonic() < deadline:
            sleep(.001)
        if foreground[0] != 1:
            raise TimeoutError('bulk job was not queued')
        one = workers.submit(small, 'one')
        two = workers.submit(small, 'two')
        if mode == 'new':
            deadline = monotonic() + 2
            while queue.snapshot()['depth'] < 3 and monotonic() < deadline:
                sleep(.001)
            if queue.snapshot()['depth'] != 3:
                raise TimeoutError('visible queue never filled')
            depths.append(queue.snapshot()['depth'])
        sleep(.025)
        allow_large_to_finish.set()
        for future in (big, other, one, two):
            future.result(timeout=5)
    return {
        'first_useful_seconds': min(clocks['one_ready'], clocks['two_ready']),
        'last_preview_seconds': max(clocks['one_ready'], clocks['two_ready']),
        'bulk_complete_seconds': clocks['export'],
        'first_preview_before_bulk_complete':
            min(clocks['one_admitted'], clocks['two_admitted']) < clocks['export'],
        'retry_count': clocks['one_retries'] + clocks['two_retries'],
        'max_queued': max(depths, default=1),
        'wall_seconds': monotonic() - start,
        'cpu_seconds': process_time() - cpu,
        'rss_peak_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'rss_before_kib': rss_before,
    }


def _cgroup_text(filename):
    try:
        return (Path('/sys/fs/cgroup') / filename).read_text().strip()
    except OSError:
        return 'unavailable'


def main():
    runs = {}
    for label, durations in (
        ('synthetic_cold', (.12, .12, .01)),
        ('synthetic_warm', (.04, .04, .004)),
    ):
        runs[label] = {}
        for mode in ('legacy', 'new'):
            values = [sample('old' if mode == 'legacy' else 'new', *durations)
                      for _ in range(3)]
            runs[label][mode] = {
                'runs': values,
                'mean_first_useful_seconds':
                    statistics.mean(row['first_useful_seconds'] for row in values),
                'mean_cpu_seconds': statistics.mean(row['cpu_seconds'] for row in values),
            }
    print(json.dumps({
        'baseline_sha': 'f0af99567223aea3375f60e671450048be2bf0a0',
        'evidence': 'isolated real new queue against simulated legacy policy; sleeps, not LO/browser',
        'cgroup_memory_max': _cgroup_text('memory.max'),
        'cgroup_cpu_max': _cgroup_text('cpu.max'),
        'workloads': runs,
    }, indent=2))


if __name__ == '__main__':
    main()
