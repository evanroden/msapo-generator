"""Source-independent synthetic tests for warm preview raster reuse.

A live PDF ticket is always verified before any cached JPEG is returned.
Performance acceptance counts unnecessary opens, not fragile wall-clock time.
"""
from dataclasses import replace
from io import BytesIO
from unittest.mock import patch

import fitz
from PIL import Image
import pytest

from app.monthly_report_preview import ReportPreview
from app import monthly_report_preview_store as store


def synthetic(pages=18, label="First", *, rotated=False):
    with fitz.open() as pdf:
        for n in range(pages):
            page = pdf.new_page(width=595 + n % 2 * 50, height=842)
            page.insert_text((72, 72), f"Synthetic {label} page {n + 1}", fontsize=14)
            if rotated and n == 1:
                page.set_rotation(90)
        return ReportPreview(pdf.tobytes(), pages, label, "September 2026")


@pytest.fixture
def cache():
    value = store.PreviewStore()
    yield value
    value.close()


def test_warm_two_page_viewport_reuses_same_jpegs_without_opening_pdf(cache):
    ticket = cache.put("synthetic-owner", synthetic(32))
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        cold = cache.pages("synthetic-owner", ticket, (0, 1))
        assert opener.call_count == 1
        opener.reset_mock()
        warm = cache.pages("synthetic-owner", ticket, (0, 1))
        assert opener.call_count == 0
        again = cache.pages("synthetic-owner", ticket, (1, 0))
        assert opener.call_count == 0
    assert cold == warm
    assert again == tuple(reversed(cold))
    assert all(raw.startswith(b"\xff\xd8") for _, raw in cold)
    for index, raw in warm:
        with Image.open(BytesIO(raw)) as picture:
            assert picture.width > 0 and picture.height > 0
            assert picture.width * picture.height <= store.MAX_PAGE_PIXELS + 5000
    assert cache.stats()["pdf_entries"] == 1
    assert cache.stats()["raster_entries"] == 2


def test_partial_cache_hit_opens_pdf_once_and_warm_followup_never_reopens(cache):
    ticket = cache.put("synthetic-owner", synthetic(40))
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        first = cache.pages("synthetic-owner", ticket, (0, 1))
        assert opener.call_count == 1
        opener.reset_mock()
        mixed = cache.pages("synthetic-owner", ticket, (1, 2))
        assert opener.call_count == 1
        opener.reset_mock()
        warm = cache.pages("synthetic-owner", ticket, (2, 1))
        assert opener.call_count == 0
    assert first[1] == mixed[0] == warm[1]
    assert mixed[1] == warm[0]
    assert cache.stats()["raster_entries"] == 3


def test_dpi_and_page_rotation_keep_independent_cached_rasters(cache):
    ticket = cache.put("synthetic-owner", synthetic(8, rotated=True))
    assert ticket.sizes[1][0] > ticket.sizes[1][1]
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        low = cache.pages("synthetic-owner", ticket, (1,), dpi=96)
        high = cache.pages("synthetic-owner", ticket, (1,), dpi=150)
        assert opener.call_count == 2
        opener.reset_mock()
        assert cache.pages("synthetic-owner", ticket, (1,), dpi=96) == low
        assert cache.pages("synthetic-owner", ticket, (1,), dpi=150) == high
        assert opener.call_count == 0
    with Image.open(BytesIO(low[0][1])) as l, Image.open(BytesIO(high[0][1])) as h:
        assert l.width < h.width and l.height < h.height
        assert l.width > l.height and h.width > h.height


def test_cached_jpegs_are_not_accessible_after_owner_change_or_ticket_discard(cache):
    ticket = cache.put("first", synthetic(6))
    cache.pages("first", ticket, (0,))
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        assert cache.pages("second", ticket, (0,)) is None
        assert cache.pages("first", replace(ticket, pages=99), (0,)) is None
        assert opener.call_count == 0
    cache.discard("first", ticket)
    assert cache.stats()["raster_entries"] == 0
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        assert cache.pages("first", ticket, (0,)) is None
        assert opener.call_count == 0


def test_missing_pdf_cannot_be_served_from_warm_cache(cache):
    ticket = cache.put("owner", synthetic(4))
    assert cache.pages("owner", ticket, (0,))
    assert cache.stats()["raster_entries"] == 1
    cache._files[ticket.key].path.unlink()
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        assert cache.pages("owner", ticket, (0,)) is None
        assert opener.call_count == 0
    assert cache.stats()["pdf_entries"] == cache.stats()["raster_entries"] == 0


def test_changed_preview_bytes_get_new_ticket_and_fresh_cold_rasters(cache):
    first = cache.put("owner", synthetic(9, label="Old"))
    first_data = cache.pages("owner", first, (0,))
    second = cache.put("owner", synthetic(9, label="Changed"))
    assert first.key != second.key
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        second_data = cache.pages("owner", second, (0,))
        assert opener.call_count == 1
        opener.reset_mock()
        assert cache.pages("owner", second, (0,)) == second_data
        assert opener.call_count == 0
    assert first_data[0][1] != second_data[0][1]
    assert cache.pages("owner", first, (0,)) == first_data
    assert cache.stats()["pdf_entries"] == 2


def test_unretained_oversized_raster_must_redecode_instead_of_faking_cache_hit():
    cache = store.PreviewStore(raster_bytes=100)
    try:
        ticket = cache.put("owner", synthetic(4))
        with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
            one = cache.pages("owner", ticket, (0,))
            two = cache.pages("owner", ticket, (0,))
            assert opener.call_count == 2
        assert one == two
        assert cache.stats()["raster_entries"] == 0
    finally:
        cache.close()


def test_cache_reset_removes_old_owner_pages_without_touching_other_tickets(cache):
    a = cache.put("qa:a:lease1:editor", synthetic(2, label="A"))
    b = cache.put("qa:b:lease1:editor", synthetic(2, label="B"))
    cache.pages("qa:a:lease1:editor", a, (0,))
    cache.pages("qa:b:lease1:editor", b, (0,))
    cache.discard_owner_prefix("qa:a:")
    assert cache.pages("qa:a:lease1:editor", a, (0,)) is None
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opener:
        assert cache.pages("qa:b:lease1:editor", b, (0,))
        assert opener.call_count == 0
