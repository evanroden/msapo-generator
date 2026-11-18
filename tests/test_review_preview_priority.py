"""A deliberate full Review waits briefly, without weakening preview admission."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time
import pytest
from app import monthly_report_render_jobs as jobs


def await_condition(condition):
    deadline=time.monotonic()+2
    while not condition():
        assert time.monotonic()<deadline
        time.sleep(.005)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(jobs,'memory_headroom',lambda: jobs.PREVIEW_HEADROOM_BYTES*2)


def test_review_waits_for_existing_job_and_background_yields():
    entered=Event()
    def review():
        with jobs.work_slot(preview=True, review=True, wait_seconds=1):
            assert jobs.preview_memory_guard() is not None
            entered.set()
    jobs._WORK_SLOT.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(review)
            await_condition(lambda: jobs._REVIEW_WAITING==1)
            assert not entered.is_set()
            with pytest.raises(jobs.RenderBusy):
                with jobs.work_slot(preview=True):
                    pytest.fail('automatic preview must yield to waiting Review')
            jobs._WORK_SLOT.release()
            future.result(timeout=2)
    finally:
        if jobs._WORK_SLOT.locked(): jobs._WORK_SLOT.release()
    assert entered.is_set() and jobs._REVIEW_WAITING==0


def test_waiting_review_precedes_export_that_has_not_started():
    # A24 changes only admission order. An admitted export remains uninterrupted.
    order=[]
    finish_review=Event()
    def review():
        with jobs.work_slot(preview=True,review=True,wait_seconds=2):
            order.append('review')
            assert finish_review.wait(2)
    def export():
        with jobs.work_slot(wait_seconds=2):
            order.append('export')
    jobs._WORK_SLOT.acquire()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            review_future=pool.submit(review)
            await_condition(lambda: jobs._REVIEW_WAITING==1)
            export_future=pool.submit(export)
            await_condition(lambda: jobs._FOREGROUND_WAITING==1)
            jobs._WORK_SLOT.release()
            await_condition(lambda: order==['review'])
            assert not export_future.done()
            finish_review.set()
            review_future.result(timeout=3);export_future.result(timeout=3)
    finally:
        finish_review.set()
        if jobs._WORK_SLOT.locked():jobs._WORK_SLOT.release()
    assert order==['review','export']


def test_review_timeout_does_not_take_or_release_another_job():
    jobs._WORK_SLOT.acquire()
    try:
        start=time.monotonic()
        with pytest.raises(jobs.RenderBusy,match='Another report'):
            with jobs.work_slot(preview=True,review=True,wait_seconds=.02):
                pytest.fail('held work may not be bypassed')
        assert time.monotonic()-start<.5
        assert jobs._WORK_SLOT.locked() and jobs._REVIEW_WAITING==0
    finally:jobs._WORK_SLOT.release()


def test_waited_review_rechecks_memory_before_assembly(monkeypatch):
    def review():
        with pytest.raises(jobs.RenderBusy,match='queued'):
            with jobs.work_slot(preview=True,review=True,wait_seconds=1):
                pytest.fail('memory pressure must still refuse')
    jobs._WORK_SLOT.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(review)
        await_condition(lambda: jobs._REVIEW_WAITING==1)
        monkeypatch.setattr(jobs,'memory_headroom',lambda:0)
        jobs._WORK_SLOT.release()
        future.result(timeout=2)
    assert not jobs._WORK_SLOT.locked() and jobs._REVIEW_WAITING==0


def test_only_full_report_preview_requests_review_priority(monkeypatch):
    from app import monthly_report_preview as preview
    from contextlib import contextmanager
    calls=[]
    @contextmanager
    def slot(**kw):calls.append(kw);yield
    monkeypatch.setattr(jobs,'work_slot',slot)
    monkeypatch.setattr(preview,'_preview_report',lambda *a,**k:'full')
    monkeypatch.setattr(preview,'_preview_section',lambda *a,**k:'section')
    assert preview.preview_report(None)=='full'
    assert preview.preview_section(None,'activity')=='section'
    assert calls==[dict(preview=True,review=True,wait_seconds=10),dict(preview=True)]


def test_review_priority_cannot_disable_preview_memory_guard():
    with pytest.raises(ValueError, match='preview memory guard'):
        with jobs.work_slot(review=True):
            pytest.fail('invalid unguarded Review must not be admitted')
    assert not jobs._WORK_SLOT.locked()
