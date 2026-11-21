"""A24: deterministic synthetic multi-owner queue, safety and persistence proofs.

No client originals, external AI, live app or office process is used here.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Event
from time import monotonic, sleep
import json

import pytest

from app import monthly_report_render_jobs as jobs
from app import monthly_report_visible_queue as visible


@pytest.fixture(autouse=True)
def isolated_queue(monkeypatch):
    monkeypatch.setattr(visible, 'QUEUE', visible.VisibleFirstQueue())
    monkeypatch.setattr(jobs, 'memory_headroom',
                        lambda: 512 * 1024 * 1024 - 64 * 1024 * 1024)


def until(predicate, seconds=3):
    deadline = monotonic() + seconds
    while not predicate():
        assert monotonic() < deadline, 'admission queue did not reach deterministic barrier'
        sleep(.005)


def test_one_running_large_two_small_and_one_waiting_large_visible_first():
    order = []
    running, finish = Event(), Event()

    def large_running():
        with jobs.work_slot(wait_seconds=3):
            running.set()
            assert finish.wait(4)

    def waiting_bulk():
        with jobs.work_slot(wait_seconds=3):
            order.append(('bulk', monotonic()))

    def small(key):
        with jobs.work_slot(preview=True, owner=('synthetic', key),
                            revision='v1', wait_seconds=2):
            order.append((key, monotonic()))

    with ThreadPoolExecutor(max_workers=4) as pool:
        first = pool.submit(large_running)
        assert running.wait(2)
        bulk = pool.submit(waiting_bulk)
        until(lambda: jobs.queue_state()['exports'] == 1)
        first_small = pool.submit(small, 'small-a')
        until(lambda: jobs.queue_state()['visible'] == 1)
        second_small = pool.submit(small, 'small-b')
        until(lambda: jobs.queue_state() == {'depth': 3, 'visible': 2, 'exports': 1})
        released_at = monotonic()
        finish.set()
        first.result(timeout=4)
        first_small.result(timeout=4)
        second_small.result(timeout=4)
        bulk.result(timeout=4)
    assert [name for name, _ in order] == ['small-a', 'small-b', 'bulk']
    first_useful = order[0][1] - released_at
    bulk_first = order[2][1] - released_at
    assert 0 <= first_useful < bulk_first
    assert jobs.queue_state()['depth'] == 0 and not jobs._WORK_SLOT.locked()


def test_two_preview_turns_max_before_waiting_export():
    order = []
    assert jobs._WORK_SLOT.acquire(False)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = []
            for n in range(3):
                def small(num=n):
                    with jobs.work_slot(preview=True, owner=('separate-owner', num),
                                        revision='v1', wait_seconds=2):
                        order.append(f'small-{num}')
                futures.append(pool.submit(small))
                until(lambda n=n: jobs.queue_state()['visible'] == n + 1)
            def bulk():
                with jobs.work_slot(wait_seconds=2):
                    order.append('bulk')
            futures.append(pool.submit(bulk))
            until(lambda: jobs.queue_state()['depth'] == 4)
            jobs._WORK_SLOT.release()
            for result in futures:
                result.result(timeout=4)
    finally:
        if jobs._WORK_SLOT.locked():
            jobs._WORK_SLOT.release()
    assert order == ['small-0', 'small-1', 'bulk', 'small-2']


def test_revised_owner_cancels_only_old_waiter_and_does_not_touch_saved_draft(tmp_path):
    draft = tmp_path / 'saved-report.json'
    original = {'contract': 'synthetic-contract', 'site': 'site-A', 'period': '2026-10',
                'prepared_by': 'Human edit', 'approved_pin': 'rev-original'}
    draft.write_text(json.dumps(original))
    digest = sha256(draft.read_bytes()).hexdigest()
    current = {'revision': 'new'}
    assert jobs._WORK_SLOT.acquire(False)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            def preview(revision):
                with jobs.work_slot(preview=True, owner=('owner-1', 'cover'),
                                    revision=revision, is_current=lambda: current['revision'] == revision,
                                    wait_seconds=1.5):
                    return revision
            current['revision'] = 'old'
            stale = pool.submit(preview, 'old')
            until(lambda: jobs.queue_state()['visible'] == 1)
            current['revision'] = 'new'
            latest = pool.submit(preview, 'new')
            until(lambda: jobs.queue_state()['visible'] == 1)
            with pytest.raises(jobs.RenderBusy, match='replaced|current'):
                stale.result(timeout=2)
            assert not latest.done()
            jobs._WORK_SLOT.release()
            assert latest.result(timeout=3) == 'new'
    finally:
        if jobs._WORK_SLOT.locked():
            jobs._WORK_SLOT.release()
    assert sha256(draft.read_bytes()).hexdigest() == digest
    assert json.loads(draft.read_text()) == original
    assert jobs.queue_state()['depth'] == 0


def test_hide_cancels_queued_preview_not_accepted_save_or_other_owner(tmp_path):
    destination = tmp_path / 'shared-synthetic-snapshot.json'
    assert jobs._WORK_SLOT.acquire(False)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            def preview():
                with jobs.work_slot(preview=True, owner=('tab-1', 'activity'),
                                    revision='old', wait_seconds=1.5):
                    pytest.fail('hidden preview started')
            def unrelated():
                with jobs.work_slot(preview=True, owner=('tab-2', 'cover'),
                                    revision='current', wait_seconds=1.5):
                    return 'independent site'
            def save():
                # A real shared write remains independent of preview cancellation.
                with jobs.work_slot(wait_seconds=2):
                    destination.write_text(json.dumps({'site': 'site-A', 'edit': 'accepted'}))
            obsolete = pool.submit(preview)
            until(lambda: jobs.queue_state()['visible'] == 1)
            survivor = pool.submit(unrelated)
            until(lambda: jobs.queue_state()['visible'] == 2)
            saved = pool.submit(save)
            until(lambda: jobs.queue_state()['exports'] == 1)
            jobs.cancel_queued_preview(('tab-1', 'activity'))
            with pytest.raises(jobs.RenderBusy, match='replaced'):
                obsolete.result(timeout=2)
            assert jobs.queue_state()['visible'] == 1
            jobs._WORK_SLOT.release()
            assert survivor.result(timeout=3) == 'independent site'
            saved.result(timeout=3)
    finally:
        if jobs._WORK_SLOT.locked():
            jobs._WORK_SLOT.release()
    assert json.loads(destination.read_text()) == {'site': 'site-A', 'edit': 'accepted'}


def test_untrusted_or_missing_revision_fails_closed_without_mutation():
    for proof in (lambda: False, lambda: (_ for _ in ()).throw(ValueError('malformed'))):
        with pytest.raises(jobs.RenderBusy, match='current'):
            with jobs.work_slot(preview=True, owner='pane', revision='invalid',
                                is_current=proof, wait_seconds=0):
                pytest.fail('unverified owner may not render')
    with pytest.raises(ValueError, match='Revision cancellation'):
        with jobs.work_slot(owner='not-allowed-on-save'):
            pytest.fail('save cannot be cancellable by a preview token')
    with pytest.raises(ValueError, match='Review priority'):
        with jobs.work_slot(review=True):
            pytest.fail('review must keep memory guard')
    assert jobs.queue_state()['depth'] == 0


def test_wait_queue_is_bounded_and_timeout_never_steals_foreign_job(monkeypatch):
    monkeypatch.setattr(visible, 'MAX_QUEUED', 2)
    assert jobs._WORK_SLOT.acquire(False)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_waiting_preview, f'owner-{n}') for n in range(2)]
            until(lambda: jobs.queue_state()['depth'] == 2)
            with pytest.raises(jobs.RenderBusy, match='queue is full'):
                with jobs.work_slot(preview=True, owner='third', revision='v1',
                                    wait_seconds=.05):
                    pytest.fail('bounded queue accepted an extra waiter')
            assert jobs._WORK_SLOT.locked()
            jobs._WORK_SLOT.release()
            assert [future.result(timeout=3) for future in futures] == [0, 0]
    finally:
        if jobs._WORK_SLOT.locked():
            jobs._WORK_SLOT.release()
    assert jobs.queue_state()['depth'] == 0


def _waiting_preview(owner):
    with jobs.work_slot(preview=True, owner=owner, revision='same', wait_seconds=1.5):
        return 0


def test_busy_and_unverified_preview_status_never_claim_ready():
    from app.monthly_report_section_preview_ui import _preview_status
    assert _preview_status(pending=True) == 'Updating preview…'
    assert not _preview_status(pending=True).startswith('Current')
    assert _preview_status(pages=2) == 'Current · 2 pages'
    assert jobs.queue_state() == {'depth': 0, 'visible': 0, 'exports': 0}
