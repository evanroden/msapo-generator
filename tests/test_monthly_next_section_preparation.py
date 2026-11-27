"""Synthetic bounded preparation, no authentic report fixtures."""
from concurrent.futures import Future
from threading import BoundedSemaphore

from app.monthly_report_preview_preparation import next_preparation, refresh_preparation
from app import monthly_report_section_preview_ui as ui


def test_only_immediate_registered_included_successor():
    order = ('cover', 'activity', 'water', 'training')
    registered = dict.fromkeys(order)
    assert next_preparation(order, {}, registered) == ()
    assert next_preparation(order, {'activity': True}, registered) == ('water',)
    assert next_preparation(order, {'activity': True, 'water': True}, registered) == ('training',)
    assert next_preparation(order, {'training': True}, registered) == ()
    assert next_preparation(order, {'activity': True}, {'training': 1}) == ()


def state():
    return {'owner': 'synthetic-preparation', 'visible': {'activity': True},
            'preparation_order': ('activity', 'water', 'training'),
            'wanted': {'activity': 'a', 'water': 'w', 'training': 't'},
            'requests': {'activity': ('a', object(), {}, 'Activity'),
                         'water': ('w', object(), {}, 'Water'),
                         'training': ('t', object(), {}, 'Training')},
            'queue': {}, 'cache': {'activity': {'fingerprint': 'a'}}, 'running': None, 'last_good': {}}


def test_one_successor_retired_when_visible_selection_changes():
    s = state()
    refresh_preparation(s)
    assert tuple(s['queue']) == ('water',)
    s['visible'] = {'water': True}
    s['cache']['water'] = {'fingerprint': 'w'}
    refresh_preparation(s)
    assert s['preparing'] == ('training',)
    assert 'training' in s['queue']
    s['visible'] = {}
    refresh_preparation(s)
    assert s['preparing'] == () and not s['queue']


def test_visible_queue_precedes_preparation_and_uses_existing_slot(monkeypatch):
    submitted = []
    class Worker:
        def submit(self, fn, *args):
            submitted.append(args)
            return Future()
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    s = state()
    refresh_preparation(s)  # Speculative request was queued first.
    s['cache'].clear()
    ui._enqueue_visible(s, 'activity')
    ui._advance_preview_queue(s)
    assert s['running'][0] == 'activity'
    assert not slot.acquire(False)
    assert len(submitted) == 1
    slot.release()


def test_prepared_pdf_is_not_visible_and_does_not_claim_page_readiness(monkeypatch):
    submitted = []
    class Worker:
        def submit(self, fn, *args):
            submitted.append(args)
            return Future()
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    s = state()
    ui._advance_preview_queue(s)
    assert s['running'][0] == 'water'
    assert not ui._pending(s, 'water')
    is_current = submitted[0][-2]
    assert is_current()
    s['wanted']['water'] = 'changed'
    assert not is_current()
    s['wanted']['water'] = 'w'
    s['visible'] = {'training': True}
    refresh_preparation(s)
    assert not is_current()
    slot.release()


def test_preparation_does_not_publish_after_navigation_or_aba(monkeypatch):
    import pymupdf as fitz
    from app.monthly_report_preview import ReportPreview
    from app.monthly_report_preview_store import PreviewStore
    futures = []; checks = []
    class Worker:
        def submit(self, fn, *args):
            checks.append(args[-2])
            f = Future(); futures.append(f); return f
    store = PreviewStore(); slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, 'STORE', store)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', slot)
    s = state(); s['generations'] = {'water': 1}
    try:
        ui._advance_preview_queue(s)
        assert checks[0]()
        s['generations']['water'] = 3
        assert not checks[0](), 'Same fingerprint after ABA is a different request'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72,72), 'Synthetic old preparation')
            ticket = store.put(s['owner'], ReportPreview(pdf.tobytes(), 1, 'Synthetic', 'Synthetic'))
        s['visible'] = {'training': True}
        refresh_preparation(s)
        futures[0].set_result({'ticket': ticket, 'pages': 1}); slot.release()
        ui._advance_preview_queue(s)
        assert not store.available(s['owner'], ticket)
        assert 'water' not in s['cache']
    finally:
        store.close()


def test_no_preparation_while_current_pdf_missing_stale_or_failed():
    for entry in (None, {'fingerprint':'old'}, {'fingerprint':'a','error':'Synthetic failure'}):
        s = state()
        s['cache'] = {'activity': entry} if entry else {}
        refresh_preparation(s)
        assert not s['queue']


def test_visible_edit_retains_inflight_unchanged_successor_without_new_work():
    s = state()
    refresh_preparation(s)
    future = Future()
    s['running'] = ('water', 'w', future)
    s['queue'].clear()
    s['wanted']['activity'] = 'edited'
    s['cache'].pop('activity')
    refresh_preparation(s)
    assert s['preparing'] == ('water',)
    assert not s['queue']
    assert ui.eligible(s, 'water')
    s['visible'] = {'training': True}
    refresh_preparation(s)
    assert not ui.eligible(s, 'water')
