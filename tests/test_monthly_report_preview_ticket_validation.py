"""Malformed preview tickets must miss without inspecting unverified page counts.

Synthetic PDFs and disposable PreviewStore instances only. This tests owner,
ticket, request-shape and raster bounds; no report library or live data.
"""
from dataclasses import replace
from unittest.mock import patch

import pymupdf as fitz
import pytest

from app import monthly_report_preview_store as store
from app.monthly_report_preview import ReportPreview


def synthetic_preview(pages=3):
    with fitz.open() as document:
        for n in range(pages):
            page = document.new_page(width=612, height=792)
            page.insert_text((72, 72), f"TEST ONLY preview page {n + 1}")
        return ReportPreview(document.tobytes(), pages, "synthetic-ticket", "November 2026")


@pytest.fixture
def cache():
    value = store.PreviewStore()
    yield value
    value.close()


@pytest.mark.parametrize("invalid", (None, {}, "old-session", 5, object()))
def test_invalid_ticket_is_cache_miss_without_disclosing_warm_rasters(cache, invalid):
    ticket = cache.put("owner", synthetic_preview())
    original = cache.pages("owner", ticket, (0,))
    before = cache.stats()
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opened:
        assert cache.pages("owner", invalid, (0,)) is None
        assert opened.call_count == 0
    assert cache.available("owner", invalid) is False
    assert cache.stats() == before
    assert cache.pages("owner", ticket, (0,)) == original


def test_invalid_ticket_never_evaluates_its_page_property(cache):
    class PoisonTicket:
        @property
        def pages(self):
            raise AssertionError("Unauthenticated ticket metadata must not be used")

    ticket = cache.put("owner", synthetic_preview())
    assert cache.pages("owner", PoisonTicket(), (0,)) is None
    assert cache.available("owner", ticket)
    assert cache.pages("owner", ticket, (0,))


@pytest.mark.parametrize("changes", (
    {"pages": "three"}, {"pages": None}, {"pages": 1},
    {"pages": 1000000000}, {"key": "unknown"},
    {"sizes": ((123.0, 400.0),)},
))
def test_forged_ticket_fields_cannot_supply_page_bounds(cache, changes):
    ticket = cache.put("owner", synthetic_preview())
    forged = replace(ticket, **changes)
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opened:
        assert cache.pages("owner", forged, (2,)) is None
        assert opened.call_count == 0
    assert cache.available("owner", ticket)
    assert cache.pages("owner", ticket, (2,))[0][0] == 2


def test_owner_is_verified_before_disclosing_page_bounds(cache):
    ticket = cache.put("alice", synthetic_preview())
    assert cache.pages("bob", ticket, (9000,)) is None
    assert cache.pages("bob", replace(ticket, pages="wrong"), (0,)) is None
    assert cache.pages("alice", ticket, (0,))


@pytest.mark.parametrize("indexes", (
    (3,), (-1,), (True,), ("0",), (0, 1, 2), "0", None,
))
def test_unchanged_valid_ticket_rejects_out_of_range_and_invalid_requests(cache, indexes):
    ticket = cache.put("owner", synthetic_preview())
    with pytest.raises(ValueError, match="at most two"):
        cache.pages("owner", ticket, indexes)
    assert cache.stats()["raster_entries"] == 0
    assert cache.available("owner", ticket)


@pytest.mark.parametrize("dpi", (0, 72, 300, True, "120"))
def test_resolution_limit_still_applies_even_to_invalid_ticket(cache, dpi):
    with pytest.raises(ValueError, match="resolution"):
        cache.pages("owner", None, (0,), dpi=dpi)


def test_valid_cold_and_warm_cache_with_page_dedup_and_other_owner(cache):
    first = cache.put("alice", synthetic_preview())
    second = cache.put("bob", synthetic_preview())
    with patch.object(store.fitz, "open", wraps=store.fitz.open) as opened:
        initial = cache.pages("alice", first, (0, 1), dpi=120)
        assert opened.call_count == 1
        assert len(initial) == 2 and all(raw.startswith(b"\\xff\\xd8") for _, raw in initial)
        opened.reset_mock()
        assert cache.pages("alice", first, (1, 0), dpi=120) == tuple(reversed(initial))
        assert cache.pages("alice", first, (0, 0), dpi=120) == (initial[0],)
        assert cache.pages("alice", second, (0,), dpi=120) is None
        assert opened.call_count == 0
    assert cache.pages("bob", second, (2,), dpi=96)[0][0] == 2
    assert cache.stats()["pdf_entries"] == 2
    assert cache.stats()["raster_bytes"] <= cache.raster_limit
