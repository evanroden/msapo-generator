"""Bounded raster preparation never claims a PDF alone makes pages ready."""
from dataclasses import replace
from unittest.mock import patch
import pytest
from app import monthly_report_preview_store as module
from test_monthly_report_preview_store import sample


def test_all_pages_prepare_incrementally_and_reuse_without_pdf_reopens():
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner', sample(10))
        assert cache.prepared_pages('owner',ticket) == ()
        with patch.object(module.fitz,'open',wraps=module.fitz.open) as opened:
            for n in range(10):
                status = cache.prepare_next_page('owner',ticket)
                assert cache.prepared_pages('owner',ticket) == tuple(range(n+1))
                assert status == ('ready' if n == 9 else 'preparing')
            assert opened.call_count == 10
            opened.reset_mock()
            assert cache.prepare_next_page('owner',ticket) == 'ready'
            for n in range(10):
                assert cache.pages('owner',ticket,(n,))
            assert opened.call_count == 0
    finally:
        cache.close()


def test_preparation_at_capacity_does_not_decode_or_evict_other_visitors():
    cache = module.PreviewStore(disk_bytes=module.MAX_PAGE_BYTES)
    try:
        kept = cache.put('kept',sample())
        wanted = cache.put('wanted',sample())
        image = cache.pages('kept',kept,(0,))
        before = cache.stats()
        with patch.object(module.fitz,'open',wraps=module.fitz.open) as opened:
            assert cache.prepare_next_page('wanted',wanted) == 'limited'
            assert opened.call_count == 0
        assert cache.stats() == before
        assert cache.pages('kept',kept,(0,)) == image
        assert cache.prepared_pages('wanted',wanted) == ()
    finally:
        cache.close()


def test_prepared_indexes_authenticate_owner_ticket_and_pdf_lifetime():
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner',sample(2))
        cache.prepare_next_page('owner',ticket)
        assert cache.prepared_pages('foreign',ticket) is None
        assert cache.prepare_next_page('foreign',ticket) == 'obsolete'
        assert cache.prepared_pages('owner',replace(ticket,pages=3)) is None
        cache.discard('owner',ticket)
        assert cache.prepared_pages('owner',ticket) is None
        assert cache.stats()['raster_entries'] == 0
    finally:
        cache.close()


def test_source_change_during_decode_never_publishes_the_old_page():
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner',sample())
        calls = []
        def current():
            calls.append(1)
            return len(calls) == 1
        assert cache.prepare_next_page('owner',ticket,is_current=current) == 'obsolete'
        assert cache.prepared_pages('owner',ticket) == ()
    finally:
        cache.close()


def test_out_of_order_visible_page_does_not_make_preparation_falsely_complete():
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner',sample(5))
        cache.pages('owner',ticket,(0,))
        assert cache.prepare_next_page('owner',ticket) == 'preparing'
        cache.pages('owner',ticket,(2,))
        assert cache.prepare_next_page('owner',ticket) == 'preparing'
        assert cache.prepare_next_page('owner',ticket) == 'ready'
        assert cache.prepared_pages('owner',ticket) == (0,1,2,3,4)
    finally:
        cache.close()


def test_ui_warming_is_cancellable_and_visible_jobs_precede_it(monkeypatch):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    from app import monthly_report_section_preview_ui as ui
    cache = module.PreviewStore()
    jobs = []
    class Worker:
        def submit(self, fn, *args):
            jobs.append((fn,args))
            return Future()
    monkeypatch.setattr(ui,'STORE',cache)
    monkeypatch.setattr(ui,'_PREVIEW_WORKER',Worker())
    monkeypatch.setattr(ui,'_PREVIEW_SLOT',BoundedSemaphore(1))
    ticket = cache.put('owner',sample(3))
    state = {'owner':'owner','visible':{'activity':True},
             'wanted':{'activity':'a'}, 'generations':{'activity':1},
             'cache':{'activity':{'fingerprint':'a','ticket':ticket}},
             'preparation_order':('activity',),'queue':{'activity':object()}}
    try:
        ui._advance_raster_preparation(state)
        assert not jobs
        state['queue'].clear()
        ui._advance_raster_preparation(state)
        assert len(jobs) == 1
        current = jobs[0][1][-1]
        assert current()
        state['generations']['activity'] = 3
        assert not current(), 'ABA must invalidate old page preparation'
        state['generations']['activity'] = 1
        state['visible']['activity'] = False
        assert not current(), 'Leaving the pane stops speculative decoding'
    finally:
        cache.close()


def test_current_page_warming_precedes_already_queued_next_pdf(monkeypatch):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    from app import monthly_report_section_preview_ui as ui
    cache = module.PreviewStore()
    submitted = []
    class Worker:
        def submit(self, fn, *args):
            submitted.append(fn)
            return Future()
    monkeypatch.setattr(ui, 'STORE', cache)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', BoundedSemaphore(1))
    ticket = cache.put('owner', sample(3))
    state = {'owner':'owner', 'visible':{'activity':True},
             'wanted':{'activity':'a', 'water':'w'},
             'requests':{'water':('w', object(), {}, 'Water')},
             'generations':{'activity':1},
             'cache':{'activity':{'fingerprint':'a', 'ticket':ticket}},
             'preparation_order':('activity','water'),
             'queue':{'water':('w', object(), {}, 'Water')}}
    try:
        ui._advance_preview_queue(state)
        assert submitted == [ui._prepare_raster_page]
        assert state.get('raster_running')
        assert not state.get('running')
        assert 'water' in state['queue']
    finally:
        cache.close()


def test_prepared_pages_use_existing_disk_budget_and_survive_ram_eviction():
    cache = module.PreviewStore(raster_bytes=100)
    try:
        ticket = cache.put('owner', sample(12))
        original = cache.stats()['pdf_bytes']
        for _ in range(ticket.pages):
            cache.prepare_next_page('owner', ticket)
        assert cache.prepared_pages('owner', ticket) == tuple(range(12))
        assert original < cache.stats()['pdf_bytes'] <= cache.disk_limit
        assert cache.stats()['raster_bytes'] == 0
        with patch.object(module.fitz, 'open', wraps=module.fitz.open) as opened:
            for page in range(12):
                assert cache.pages('owner', ticket, (page,))
            assert opened.call_count == 0
        assert cache.stats()['raster_bytes'] <= 100
        cache.discard('owner', ticket)
        assert cache.stats()['pdf_bytes'] == 0
        assert not cache._prepared
    finally:
        cache.close()


def test_disk_preparation_cancellation_leaves_no_jpeg_or_accounted_bytes():
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner', sample(2))
        before = cache.stats()
        calls = []
        def current():
            calls.append(True)
            return len(calls) == 1
        assert cache.prepare_next_page('owner', ticket, is_current=current) == 'obsolete'
        assert cache.stats() == before
        assert not cache._prepared
        assert not tuple(cache._files[ticket.key].path.parent.glob('*.jpg'))
    finally:
        cache.close()


def test_failed_prepared_page_unlink_remains_accounted_and_revoked(monkeypatch):
    from pathlib import Path
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner', sample())
        cache.prepare_next_page('owner', ticket)
        before = cache.stats()['pdf_bytes']
        unlink = Path.unlink
        blocked = [True]
        def fail_jpeg(path, *args, **kwargs):
            if path.suffix == '.jpg' and blocked[0]:
                raise OSError('Synthetic file busy')
            return unlink(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'unlink', fail_jpeg)
        cache.discard('owner', ticket)
        assert not cache.available('owner', ticket)
        assert cache.stats()['pdf_bytes'] == before
        assert cache.prepared_pages('owner', ticket) is None
        blocked[0] = False
        assert cache.stats()['pdf_bytes'] == 0
        assert not cache._prepared
    finally:
        cache.close()


@pytest.mark.parametrize('damage', ['delete', 'truncate'])
def test_damaged_prepared_file_is_not_ready_and_can_be_prepared_again(damage):
    cache = module.PreviewStore()
    try:
        ticket = cache.put('owner', sample(2))
        for _ in range(2):
            cache.prepare_next_page('owner', ticket)
        original = cache.stats()['pdf_bytes']
        path, _ = cache._prepared[(ticket.key, 1, 120)]
        if damage == 'delete':
            path.unlink()
        else:
            path.write_bytes(b'broken')
        assert cache.prepared_pages('owner', ticket) == (0,)
        assert cache.prepare_next_page('owner', ticket) == 'ready'
        assert cache.prepared_pages('owner', ticket) == (0, 1)
        assert cache.stats()['pdf_bytes'] == original
    finally:
        cache.close()


def test_one_page_visible_pane_does_not_start_redundant_background_job(monkeypatch):
    from app import monthly_report_section_preview_ui as ui
    cache = module.PreviewStore()
    ticket = cache.put('owner', sample(1))
    class Worker:
        def submit(self, *args):
            pytest.fail('The visible single page is decoded by its delivery path')
    monkeypatch.setattr(ui, 'STORE', cache)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    state = {'owner': 'owner', 'visible': {'cover': True},
             'wanted': {'cover': 'a'}, 'generations': {'cover': 1},
             'cache': {'cover': {'fingerprint': 'a', 'ticket': ticket}},
             'preparation_order': ('cover',), 'queue': {}}
    try:
        ui._advance_raster_preparation(state)
        assert not state.get('raster_running')
    finally:
        cache.close()


def test_failed_page_write_never_claims_readiness_or_leaves_unaccounted_jpeg(monkeypatch):
    from pathlib import Path
    cache = module.PreviewStore()
    ticket = cache.put('owner', sample(2))
    before = cache.stats()
    original = Path.open
    class BrokenWrite:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, raw):
            self.stream.write(raw[:10])
            raise OSError('Synthetic partial disk write')
    def partial(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        return BrokenWrite(stream) if path.suffix == '.jpg' else stream
    monkeypatch.setattr(Path, 'open', partial)
    try:
        with pytest.raises(OSError, match='partial disk write'):
            cache.prepare_next_page('owner', ticket)
        assert cache.prepared_pages('owner', ticket) == ()
        assert cache.stats() == before
        assert not tuple(cache._files[ticket.key].path.parent.glob('*.jpg'))
    finally:
        cache.close()


def test_expiry_removes_prepared_jpegs_and_all_accounted_bytes(monkeypatch):
    cache = module.PreviewStore(max_age=10)
    clock = [20.0]
    monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    ticket = cache.put('owner', sample(3))
    try:
        for _ in range(3):
            cache.prepare_next_page('owner', ticket)
        paths = [value[0] for value in cache._prepared.values()]
        assert paths and all(path.exists() for path in paths)
        clock[0] += 11
        assert cache.prepared_pages('owner', ticket) is None
        assert all(not path.exists() for path in paths)
        assert cache.stats()['pdf_bytes'] == 0
    finally:
        cache.close()


def test_partial_write_with_failed_cleanup_is_accounted_and_ticket_revoked(monkeypatch):
    from pathlib import Path
    cache = module.PreviewStore()
    ticket = cache.put('owner', sample(2))
    before = cache.stats()['pdf_bytes']
    original_open, original_unlink = Path.open, Path.unlink
    blocked = [True]
    class BrokenWrite:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def write(self, raw):
            self.stream.write(raw[:10])
            raise OSError('Synthetic partial write')
    def partial(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return BrokenWrite(stream) if path.suffix == '.jpg' else stream
    def busy(path, *args, **kwargs):
        if path.suffix == '.jpg' and blocked[0]:
            raise OSError('Synthetic cleanup failure')
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', partial)
    monkeypatch.setattr(Path, 'unlink', busy)
    try:
        with pytest.raises(OSError):
            cache.prepare_next_page('owner', ticket)
        assert cache.stats()['pdf_bytes'] == before + 10
        assert not cache.available('owner', ticket)
        assert cache.prepared_pages('owner', ticket) is None
        blocked[0] = False
        assert cache.stats()['pdf_bytes'] == 0
        assert not cache._prepared
    finally:
        cache.close()


@pytest.mark.parametrize('dpi', [96, 120, 150])
def test_ui_warms_active_resolution_and_cancels_on_viewport_change(monkeypatch, dpi):
    from concurrent.futures import Future
    from threading import BoundedSemaphore
    from app import monthly_report_section_preview_ui as ui
    cache = module.PreviewStore()
    ticket = cache.put('owner', sample(2))
    jobs = []
    class Worker:
        def submit(self, fn, *args):
            jobs.append((fn, args))
            return Future()
    monkeypatch.setattr(ui, 'STORE', cache)
    monkeypatch.setattr(ui, '_PREVIEW_WORKER', Worker())
    monkeypatch.setattr(ui, '_PREVIEW_SLOT', BoundedSemaphore(1))
    state = {'owner':'owner', 'visible':{'activity':True}, 'wanted':{'activity':'a'},
             'cache':{'activity':{'fingerprint':'a','ticket':ticket}}, 'queue':{},
             'preparation_order':('activity',), 'page_requests':{'activity':{
                 'generation':'a','ticket_key':ticket.key,'dpi':dpi}}}
    try:
        ui._advance_raster_preparation(state)
        fn, args = jobs[0]
        assert args[2] == dpi and args[-1]()
        fn(*args)
        assert cache.prepared_pages('owner', ticket, dpi=dpi) == (0,)
        with patch.object(module.fitz, 'open', wraps=module.fitz.open) as opened:
            assert cache.pages('owner', ticket, (0,), dpi=dpi)
            assert opened.call_count == 0
        state['page_requests']['activity']['dpi'] = 96 if dpi != 96 else 150
        assert not args[-1](), 'Resolution changes invalidate in-flight preparation'
    finally:
        cache.close()
