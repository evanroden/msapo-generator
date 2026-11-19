"""A28: only the current ticket's requested PDF pages reach a section pane.

Synthetic PDF pages are recognizable by their own vector text. No authentic
uploads, report library, browser screenshot or conversion service is used.
"""
from contextlib import nullcontext
from hashlib import sha256
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from app import monthly_report_section_preview_ui as ui
from app.monthly_report_preview_store import PreviewStore


def _preview(count, revision):
    with fitz.open() as pdf:
        for index in range(count):
            page = pdf.new_page(width=612, height=792)
            page.insert_text((48, 64), f"A28 SYNTHETIC {revision} PAGE {index + 1:03d}")
        return SimpleNamespace(pdf=pdf.tobytes(), initial_page=count - 1)


def _render(monkeypatch, store, state):
    emitted = []
    monkeypatch.setattr(ui, "STORE", store)
    monkeypatch.setattr(ui, "_ordered_preview_state", lambda prefix: state)
    monkeypatch.setattr(ui, "_advance_preview_queue", lambda item: None)
    monkeypatch.setattr(ui.st, "container", lambda **kwargs: nullcontext())
    monkeypatch.setattr(ui, "render_view", lambda **kwargs: emitted.append(kwargs))
    ui._render_ordered_preview("activity", "a28", "Activity")
    assert len(emitted) == 1
    return emitted[0]


@pytest.mark.parametrize("count", [2, 24, 120])
def test_first_selected_page_not_page_zero_or_full_inventory(monkeypatch, count):
    store = PreviewStore()
    try:
        raw = _preview(count, "revision-new")
        original = sha256(raw.pdf).hexdigest()
        ticket = store.put("a28-owner", raw)
        assert ticket.initial_page == count - 1
        state = {
            "owner": "a28-owner", "wanted": {"activity": "revision-new"},
            "cache": {"activity": {"fingerprint": "revision-new", "ticket": ticket}},
            "queue": {}, "running": None, "last_good": {},
            "requests": {}, "visible": {"activity": True}, "page_requests": {},
        }
        decoded = []
        original_pixmap = fitz.Page.get_pixmap

        def observed(page, *args, **kwargs):
            decoded.append(page.number)
            return original_pixmap(page, *args, **kwargs)

        monkeypatch.setattr(fitz.Page, "get_pixmap", observed)
        first = _render(monkeypatch, store, state)
        assert tuple(index for index, _ in first["images"]) == (count - 1,)
        assert decoded == [count - 1], "No unrequested page may be decoded for first paint"
        assert first["ticket"] == ticket and first["status"] == f"Current · {count} pages"
        assert first["acknowledged_viewport"] is None
        with fitz.open(stream=raw.pdf, filetype="pdf") as pdf:
            assert f"PAGE {count:03d}" in pdf[count - 1].get_text()
        assert sha256(raw.pdf).hexdigest() == original
        assert store.stats()["raster_entries"] == 1

        # The browser now asks for an adjacent page. No other thumbnail is made.
        state["page_requests"]["activity"] = {
            "generation": "revision-new", "ticket_key": ticket.key,
            "visible": True, "pages": (count - 2, count - 1), "dpi": 120,
        }
        second = _render(monkeypatch, store, state)
        assert tuple(index for index, _ in second["images"]) == (count - 2, count - 1)
        assert decoded == [count - 1, count - 2], "Already decoded pages must be warm"
        assert second["acknowledged_viewport"]["generation"] == "revision-new"
        assert second["images"][1][1] == first["images"][0][1]
        assert store.stats()["raster_entries"] == 2
    finally:
        store.close()


@pytest.mark.parametrize("count", [2, 24, 120])
def test_old_revision_viewport_never_drives_new_ticket(monkeypatch, count):
    store = PreviewStore()
    try:
        old_raw = _preview(count, "old")
        old_ticket = store.put("a28-owner", old_raw)
        new_raw = _preview(count, "new")
        new_ticket = store.put("a28-owner", new_raw)
        state = {
            "owner": "a28-owner", "wanted": {"activity": "new"},
            "cache": {"activity": {"fingerprint": "new", "ticket": new_ticket}},
            "queue": {}, "running": None, "last_good": {},
            "requests": {}, "visible": {"activity": True},
            "page_requests": {"activity": {
                "generation": "old", "ticket_key": old_ticket.key,
                "visible": True, "pages": (0,), "dpi": 96,
            }},
        }
        fresh = _render(monkeypatch, store, state)
        assert fresh["ticket"] == new_ticket
        assert fresh["images"][0][0] == count - 1
        assert fresh["acknowledged_viewport"] is None, "Do not ACK an old revision"
        assert fresh["status"].startswith("Current")

        # The placeholder's page-zero request is not a request for the new PDF.
        state["page_requests"]["activity"] = {
            "generation": "new", "ticket_key": None,
            "visible": True, "pages": (0,), "dpi": 96,
        }
        provisional = _render(monkeypatch, store, state)
        assert provisional["images"][0][0] == count - 1
        assert provisional["acknowledged_viewport"] is None

        # An old ticket remains accessible only for an explicitly stale view.
        state["cache"].clear()
        state["last_good"]["activity"] = {"ticket": old_ticket}
        stale = _render(monkeypatch, store, state)
        assert stale["ticket"] == old_ticket
        assert stale["stale"] is True
        assert "older preview" in stale["status"]
        assert stale["acknowledged_viewport"] is None
        assert stale["images"][0][0] == count - 1
        assert sha256(old_raw.pdf).hexdigest() != sha256(new_raw.pdf).hexdigest()
        store.discard("a28-owner", old_ticket)
        assert not store.available("a28-owner", old_ticket)
        assert store.available("a28-owner", new_ticket)
    finally:
        store.close()


def test_malformed_and_foreign_tickets_never_produce_current_pages(monkeypatch):
    store = PreviewStore()
    try:
        with pytest.raises(ValueError, match="budget"):
            store.put("a28-owner", SimpleNamespace(pdf=b"not a PDF", initial_page=0))
        ticket = store.put("a28-owner", _preview(2, "new"))
        assert store.pages("wrong-owner", ticket, (0,)) is None
        with pytest.raises(ValueError, match="existing preview pages"):
            store.pages("a28-owner", ticket, (2,))
        assert store.stats()["raster_entries"] == 0
    finally:
        store.close()


def test_viewport_callback_tags_revision_and_rejects_late_old_page(monkeypatch):
    state = {
        "wanted": {"activity": "rev-current"},
        "visible": {}, "page_requests": {}, "requests": {},
        "queue": {}, "cache": {}, "last_good": {},
    }
    browser = {
        "viewport": {
            "generation": "rev-current", "visible": True,
            "pages": (17, 18), "dpi": 120, "ticketKey": "a"*32,
        }
    }
    monkeypatch.setattr(ui, "_ordered_preview_state", lambda prefix: state)
    monkeypatch.setattr(ui.st, "session_state", {"widget": browser})
    ui._viewport_changed("a28", "activity", "widget")
    assert state["page_requests"]["activity"] == {
        "generation": "rev-current", "visible": True,
        "pages": (17, 18), "dpi": 120, "ticket_key": "a"*32,
    }
    assert ui._current_page_request(state, "activity") is None
    assert ui._current_page_request(state, "activity", SimpleNamespace(key="a"*32))["pages"] == (17, 18)
    state["wanted"]["activity"] = "rev-later"
    assert ui._current_page_request(state, "activity") is None
    # The late browser event belongs to the previous revision; no new ACK.
    ui._viewport_changed("a28", "activity", "widget")
    assert state["page_requests"]["activity"]["generation"] == "rev-current"
    assert state["wanted"]["activity"] == "rev-later"
    browser["viewport"] = {
        "generation": "rev-later", "visible": True, "pages": (1,),
        "dpi": 120, "ticketKey": "../../not-a-hex-ticket",
    }
    ui._viewport_changed("a28", "activity", "widget")
    assert state["page_requests"]["activity"]["generation"] == "rev-current"
