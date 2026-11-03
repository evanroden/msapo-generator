"""Warm preview reads keep the original owner, lifecycle and raster contracts."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pymupdf as fitz
import pytest

from app import monthly_report_preview_store as module
from app.monthly_report_preview_store import PreviewStore


def preview(pages=3, label="Synthetic preview"):
    with fitz.open() as document:
        for index in range(pages):
            page = document.new_page(width=612, height=792)
            page.insert_text((40, 40), f"{label} - page {index + 1}")
            page.draw_rect(fitz.Rect(25, 60, 90, 125), fill=(0.2, 0.6, 0.8))
            if index == 1:
                page.set_rotation(90)
        return SimpleNamespace(pdf=document.tobytes(), initial_page=0)


@pytest.fixture
def stored():
    store = PreviewStore()
    ticket = store.put("owner", preview())
    yield store, ticket
    store.close()


def no_open(*args, **kwargs):
    pytest.fail("A cached raster request must not reopen/parse its PDF.")


@pytest.mark.parametrize("dpi", [96, 120, 150])
@pytest.mark.parametrize("indexes", [(0,), (0, 1)])
def test_warm_request_keeps_exact_bytes_and_geometry_without_pdf_open(stored, monkeypatch, dpi, indexes):
    store, ticket = stored
    original = store.pages("owner", ticket, indexes, dpi=dpi)
    before = store.stats()
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, indexes, dpi=dpi) == original
    assert store.stats() == before
    for index, raw in original:
        with Image.open(BytesIO(raw)) as image:
            width, height = ticket.sizes[index]
            assert abs(image.width / image.height - width / height) < 0.003


def test_empty_request_does_not_open_pdf(stored, monkeypatch):
    store, ticket = stored
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, ()) == ()
    assert store.stats()["raster_bytes"] == 0


@pytest.mark.parametrize("indexes", [(0, 1), (1, 0)])
def test_partial_hit_opens_once_and_renders_only_missing_page(stored, monkeypatch, indexes):
    store, ticket = stored
    expected = store.pages("owner", ticket, (0,))
    opens, renders = [], []
    real_open, real_render = module.fitz.open, fitz.Page.get_pixmap
    def opened(*args, **kwargs):
        opens.append(args[0])
        return real_open(*args, **kwargs)
    def rendered(page, *args, **kwargs):
        renders.append(page.number)
        return real_render(page, *args, **kwargs)
    monkeypatch.setattr(module.fitz, "open", opened)
    monkeypatch.setattr(fitz.Page, "get_pixmap", rendered)
    result = store.pages("owner", ticket, indexes)
    assert len(opens) == 1 and renders == [1]
    assert tuple(index for index, _ in result) == indexes
    assert dict(result)[0] == dict(expected)[0]


def test_dpi_change_is_a_miss_and_then_a_warm_hit(stored, monkeypatch):
    store, ticket = stored
    low = store.pages("owner", ticket, (0,), dpi=96)
    high = store.pages("owner", ticket, (0,), dpi=150)
    assert low != high
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, (0,), dpi=96) == low
    assert store.pages("owner", ticket, (0,), dpi=150) == high


def test_warm_touch_preserves_raster_lru_and_exact_accounting(stored):
    store, ticket = stored
    # Size a two-entry budget from actual images instead of assuming JPEG size.
    expected = dict(store.pages("owner", ticket, (0, 1)))
    expected.update(store.pages("owner", ticket, (2,)))
    store.raster_limit = sum(len(raw) for raw in expected.values()) - min(map(len, expected.values()))
    store._rasters.clear()
    store._raster_bytes = 0
    store.pages("owner", ticket, (0, 1))
    store.pages("owner", ticket, (0,))
    store.pages("owner", ticket, (2,))
    assert list(store._rasters) == [(ticket.key, 0, 120), (ticket.key, 2, 120)]
    assert store.stats()["raster_bytes"] == len(expected[0]) + len(expected[2])
    assert store.stats()["raster_bytes"] <= store.raster_limit


def test_rasters_too_large_for_cache_are_still_returned_and_rerendered(monkeypatch):
    store = PreviewStore(raster_bytes=1)
    try:
        ticket = store.put("owner", preview())
        calls = []
        real_open = module.fitz.open
        def opened(*args, **kwargs):
            calls.append(args[0])
            return real_open(*args, **kwargs)
        monkeypatch.setattr(module.fitz, "open", opened)
        first = store.pages("owner", ticket, (0, 1))
        assert store.pages("owner", ticket, (0, 1)) == first
        assert len(calls) == 2
        assert store.stats()["raster_entries"] == store.stats()["raster_bytes"] == 0
    finally:
        store.close()


def test_warm_entries_never_bypass_owner_or_ticket_identity(stored, monkeypatch):
    store, ticket = stored
    store.pages("owner", ticket, (0,))
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("other", ticket, (0,)) is None
    assert store.pages("owner", replace(ticket, initial_page=1), (0,)) is None
    assert store.pages("owner", replace(ticket, sizes=((1, 1),) * ticket.pages), (0,)) is None
    assert store.pages("owner", ticket, (0,))


@pytest.mark.parametrize("retire", ["missing", "expired", "discarded"])
def test_retired_ticket_cannot_serve_warm_rasters(stored, monkeypatch, retire):
    store, ticket = stored
    store.pages("owner", ticket, (0,))
    if retire == "missing":
        store._files[ticket.key].path.unlink()
    elif retire == "expired":
        used = store._files[ticket.key].used
        monkeypatch.setattr(module, "monotonic", lambda: used + store.max_age + 1)
    else:
        store.discard("owner", ticket)
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, (0,)) is None
    assert store.stats()["raster_entries"] == 0
    assert store.stats()["pdf_entries"] == 0


def test_replacement_ticket_cannot_reuse_old_page_bytes(stored, monkeypatch):
    store, ticket = stored
    old = store.pages("owner", ticket, (0,))
    store.discard("owner", ticket)
    replacement = store.put("owner", preview(label="Changed synthetic preview"))
    new = store.pages("owner", replacement, (0,))
    assert replacement.key != ticket.key and new != old
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, (0,)) is None
    assert store.pages("owner", replacement, (0,)) == new


def test_miss_error_closes_document_and_keeps_previous_warm_page(stored, monkeypatch):
    store, ticket = stored
    first = store.pages("owner", ticket, (0,))
    opened = []
    real_open = module.fitz.open
    def tracked(*args, **kwargs):
        document = real_open(*args, **kwargs)
        opened.append(document)
        return document
    def fail_render(*args, **kwargs):
        raise ValueError("Synthetic raster failure")
    with monkeypatch.context() as changes:
        changes.setattr(module.fitz, "open", tracked)
        changes.setattr(fitz.Page, "get_pixmap", fail_render)
        with pytest.raises(ValueError, match="Synthetic raster failure"):
            store.pages("owner", ticket, (0, 1))
    assert len(opened) == 1 and opened[0].is_closed
    monkeypatch.setattr(module.fitz, "open", no_open)
    assert store.pages("owner", ticket, (0,)) == first
    assert store.stats()["raster_entries"] == 1


def test_multiple_visitors_serve_their_own_warm_pages_without_pdf_opens(monkeypatch):
    store = PreviewStore()
    try:
        tickets = [store.put(f"owner-{index}", preview(label=f"Synthetic owner {index}")) for index in range(4)]
        expected = [store.pages(f"owner-{index}", ticket, (0,)) for index, ticket in enumerate(tickets)]
        monkeypatch.setattr(module.fitz, "open", no_open)
        def request(index):
            own = index % 4
            assert store.pages(f"owner-{(own + 1) % 4}", tickets[own], (0,)) is None
            return store.pages(f"owner-{own}", tickets[own], (0,))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(request, range(20)))
        assert results == [expected[index % 4] for index in range(20)]
    finally:
        store.close()


def test_benchmark_records_real_misses_and_warm_hits_without_timing_thresholds():
    from scripts.benchmark_monthly_preview_cache import measure
    result = measure(2, 8, repeats=1, warm_reads=3)
    assert result["cold_pdf_opens"] == 1
    assert result["warm_pdf_opens"] == 0
    assert result["cold_wall"]["samples"] == 1
    assert result["warm_wall"]["samples"] == 3
    assert len(result["raster_sha256"]) == 2
    assert result["cache_stats"]["raster_entries"] == 2
    assert result["cache_stats"]["pdf_bytes"] == result["pdf_bytes"]
