"""MR-021: a running old preview cannot overwrite the newest source revision.

No artificial pauses, user data, queue-policy changes or cache budget changes.
The real worker is represented by controlled futures at the existing scheduler
boundary so the test controls completion order deterministically.
"""
from concurrent.futures import Future
from threading import BoundedSemaphore

import pymupdf as fitz

from app import monthly_report_section_preview_ui as ui
from app.monthly_report_preview import ReportPreview
from app.monthly_report_preview_store import PreviewStore


def _preview(marker):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "SYNTHETIC " + marker)
        return ReportPreview(pdf.tobytes(), 1, marker, "September 2026")


def test_superseded_inflight_source_revision_does_not_publish_or_leak(monkeypatch):
    outstanding = []
    class DeterministicWorker:
        def submit(self, fn, *args):
            future = Future()
            outstanding.append(future)
            return future

    store = PreviewStore()
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, "STORE", store)
    monkeypatch.setattr(ui, "_PREVIEW_WORKER", DeterministicWorker())
    monkeypatch.setattr(ui, "_PREVIEW_SLOT", slot)
    # Distinct source-occurrence identities and unsaved work form separate
    # immutable queued snapshots. Only the newest request may be displayed.
    old_snapshot = {"source": "sha-old", "unsaved_edit": "Draft A"}
    new_snapshot = {"source": "sha-new", "unsaved_edit": "Draft B"}
    state = {"owner": "qa491-owner",
             "report_identity": ("contract", "site", "month"),
             "wanted": {"activity": "revision-old"},
             "queue": {"activity": ("revision-old", old_snapshot, {}, "Activity")},
             "cache": {}, "last_good": {}, "running": None,
             "requests": {}, "visible": {"activity": True},
             "page_requests": {}, "ready_after": {}}
    try:
        ui._advance_preview_queue(state)
        assert len(outstanding) == 1
        assert state["running_request"][1] is old_snapshot
        assert not slot.acquire(False), "Only one preview render may be admitted"

        # A replacement is requested *while* the old work is still running.
        state["wanted"]["activity"] = "revision-new"
        state["queue"]["activity"] = ("revision-new", new_snapshot, {}, "Activity")
        old_ticket = store.put(state["owner"], _preview("OLD"))
        outstanding[0].set_result({"ticket": old_ticket, "pages": 1})
        # In production _build_preview_entry releases the slot in finally.
        slot.release()
        ui._advance_preview_queue(state)
        assert not store.available(state["owner"], old_ticket)
        assert len(outstanding) == 2
        assert state["running"][1] == "revision-new"
        assert state["running_request"][1] is new_snapshot
        assert state["wanted"]["activity"] == "revision-new"

        latest_ticket = store.put(state["owner"], _preview("NEW"))
        outstanding[1].set_result({"ticket": latest_ticket, "pages": 1})
        slot.release()
        ui._advance_preview_queue(state)
        assert state["running"] is None
        assert not state["queue"]
        assert state["cache"]["activity"]["fingerprint"] == "revision-new"
        assert state["cache"]["activity"]["ticket"] == latest_ticket
        assert store.available(state["owner"], latest_ticket)
        visible = store.pages(state["owner"], latest_ticket, (0,))
        assert len(visible) == 1 and visible[0][1].startswith(b"\xff\xd8")
        assert slot.acquire(False), "No foreground or abandoned render holds the slot"
        slot.release()
        store.discard(state["owner"], latest_ticket)
        stats = store.stats()
        assert stats["pdf_bytes"] == 0 and stats["raster_bytes"] == 0
    finally:
        store.close()
