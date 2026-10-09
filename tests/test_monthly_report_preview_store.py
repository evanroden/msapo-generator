"""Cache ownership, eviction and visible-page decoding use real PDF objects."""
from dataclasses import replace
from io import BytesIO

import fitz
from PIL import Image
import pytest

from app.monthly_report_preview import ReportPreview
from app.monthly_report_preview_store import PreviewStore, MAX_PAGE_PIXELS
from app.monthly_report_preview_view import viewport


def sample(pages=6):
    with fitz.open() as pdf:
        for index in range(pages):
            pdf.new_page().insert_text((72, 72), f'Synthetic cache page {index + 1}')
        return ReportPreview(pdf.tobytes(), pages, 'fingerprint', 'September 2026')


@pytest.fixture
def cache():
    value = PreviewStore()
    yield value
    value.close()


def test_cache_rasterizes_only_requested_pages_and_reuses_them(cache, monkeypatch):
    ticket = cache.put('visitor-one', sample())
    calls = []
    original = fitz.Page.get_pixmap
    def pixmap(page, *args, **kwargs):
        calls.append(page.number)
        return original(page, *args, **kwargs)
    monkeypatch.setattr(fitz.Page, 'get_pixmap', pixmap)
    first = cache.pages('visitor-one', ticket, (0, 1))
    assert calls == [0, 1]
    assert cache.pages('visitor-one', ticket, (0, 1)) == first
    assert calls == [0, 1]
    last = cache.pages('visitor-one', ticket, (5,))
    assert calls == [0, 1, 5]
    assert first[0][1].startswith(b'\xff\xd8') and last[0][0] == 5
    image = Image.open(BytesIO(first[0][1]))
    assert image.width * image.height <= MAX_PAGE_PIXELS + 5000
    assert 0 < cache.stats()['raster_bytes'] <= cache.raster_limit


def test_tickets_do_not_authorize_another_visitors_pages(cache):
    ticket = cache.put('visitor-one', sample())
    assert not cache.available('visitor-two', ticket)
    assert cache.pages('visitor-two', ticket, (0,)) is None
    cache.discard('visitor-two', ticket)
    assert cache.available('visitor-one', ticket)
    assert cache.pages('visitor-one', replace(ticket, key='../private-file'), (0,)) is None
    assert cache.pages('visitor-one', replace(ticket, pages=500), (0,)) is None


def test_global_disk_budget_evicts_lru_across_owners_and_rasters():
    preview = sample()
    cache = PreviewStore(disk_bytes=len(preview.pdf)*2+1, raster_bytes=100_000)
    try:
        first = cache.put('one', preview)
        second = cache.put('two', preview)
        cache.pages('one', first, (0,))
        third = cache.put('three', preview)
        assert cache.available('one', first)
        assert not cache.available('two', second)
        assert cache.available('three', third)
        assert cache.stats()['pdf_bytes'] <= cache.disk_limit
        cache.discard('one', first)
        assert cache.stats()['raster_bytes'] == 0
    finally:
        cache.close()


def test_single_oversized_file_is_rejected_instead_of_ignoring_budget():
    preview = sample()
    cache = PreviewStore(disk_bytes=len(preview.pdf)-1)
    try:
        with pytest.raises(ValueError, match='budget'):
            cache.put('one', preview)
        assert cache.stats()['pdf_bytes'] == 0
    finally:
        cache.close()


def test_oversized_raster_is_returned_but_not_retained_above_cache_budget():
    cache = PreviewStore(raster_bytes=100)
    try:
        ticket = cache.put('one', sample())
        assert cache.pages('one', ticket, (0,))
        assert cache.stats()['raster_bytes'] == 0
    finally:
        cache.close()


def test_missing_file_is_a_cache_miss_not_a_permanent_error(cache):
    ticket = cache.put('one', sample())
    cache._files[ticket.key].path.unlink()
    assert not cache.available('one', ticket)
    assert cache.stats()['pdf_bytes'] == 0


def test_expiry_removes_ephemeral_files_without_touching_library(cache, monkeypatch, tmp_path):
    import app.monthly_report_preview_store as module
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    original = tmp_path / 'saved-report.json'
    original.write_text('Keep this saved report')
    clock = [10.0]
    monkeypatch.setattr(module, 'monotonic', lambda: clock[0])
    ticket = cache.put('one', sample())
    path = cache._files[ticket.key].path
    assert path.stat().st_mode & 0o777 == 0o600
    clock[0] += cache.max_age + 1
    assert not cache.available('one', ticket)
    assert not path.exists() and original.read_text() == 'Keep this saved report'


@pytest.mark.parametrize('indexes', [(0,1,2), (-1,), (6,), (True,), ('0',)])
def test_page_requests_are_bounded(cache, indexes):
    ticket = cache.put('one', sample())
    with pytest.raises(ValueError):
        cache.pages('one', ticket, indexes)


@pytest.mark.parametrize('change', [
    {'generation':'old'}, {'visible':'true'}, {'pages':[0,1,2]},
    {'pages':[-1]}, {'pages':[True]}, {'pages':['0']}, {'dpi':10000},
])
def test_browser_state_cannot_expand_page_or_generation_scope(change):
    value = {'generation':'current','visible':True,'pages':[0,1],'dpi':120, **change}
    assert viewport(value, 'current') is None


def test_valid_viewport_tracks_only_visible_bounded_pages():
    assert viewport({'generation':'g','visible':True,'pages':[3,4],'dpi':150}, 'g') == {
        'visible':True,'pages':(3,4),'dpi':150}
