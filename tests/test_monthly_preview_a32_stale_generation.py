"""A32: deterministic obsolete-preview, byte identity and owner-scope regression.

Only generated one-page PDFs and synthetic draft/source records are used.
"""
from concurrent.futures import Future
from dataclasses import replace
from threading import BoundedSemaphore

import pymupdf as fitz
import pytest

from app import monthly_report_section_preview_ui as ui
from app.monthly_report_model import ReportPeriod, ReportSource, synthetic_draft, synthetic_profiles
from app.monthly_report_preview import ReportPreview, section_preview_fingerprint
from app.monthly_report_preview_store import PreviewStore


def _pdf(label):
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), "SYNTHETIC " + label)
        return ReportPreview(doc.tobytes(), 1, label, "September 2026")


class _ControlledWorker:
    def __init__(self):
        self.futures = []

    def submit(self, fn, *args):
        future = Future()
        self.futures.append(future)
        return future


def test_aba_source_replacement_cannot_accept_first_generation(monkeypatch):
    """A -> B -> A before completion: fingerprint equality is NOT freshness."""
    store = PreviewStore()
    worker = _ControlledWorker()
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(ui, "STORE", store)
    monkeypatch.setattr(ui, "_PREVIEW_WORKER", worker)
    monkeypatch.setattr(ui, "_PREVIEW_SLOT", slot)
    monkeypatch.setattr(ui, "DEBOUNCE_SECONDS", 0)
    a = ReportSource("a" * 64, "same.pdf", "a" * 64, ".pdf")
    b = replace(a, sha256="b" * 64)
    original = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    draft_a = replace(original, sources=(a,))
    draft_b = replace(original, sources=(b,))
    state = {
        "owner": "qa-a32-owner", "wanted": {}, "generations": {},
        "queue": {}, "requests": {}, "visible": {"activity": True},
        "ready_after": {}, "cache": {}, "last_good": {}, "running": None,
    }
    try:
        ui._register_preview_request(state, "activity", "A", draft_a, {}, "Activity")
        ui._enqueue_visible(state, "activity")
        ui._advance_preview_queue(state)
        assert len(worker.futures) == 1
        assert state["running"][1] == "A"

        # Actual admission path, same source filename and a returning SHA.
        ui._register_preview_request(state, "activity", "B", draft_b, {}, "Activity")
        ui._enqueue_visible(state, "activity")
        ui._register_preview_request(state, "activity", "A", draft_a, {}, "Activity")
        ui._enqueue_visible(state, "activity")
        assert state["generations"]["activity"] == 3

        stale = store.put(state["owner"], _pdf("OLD A request 1"))
        worker.futures[0].set_result({"ticket": stale, "pages": 1})
        slot.release()  # The production worker releases in finally.
        ui._advance_preview_queue(state)

        assert not store.available(state["owner"], stale), "A#1 must be retired even when A#3 has the same fingerprint"
        assert state["cache"].get("activity", {}).get("ticket") != stale
        assert len(worker.futures) == 2, "The newest A request must actually run"
        fresh = store.put(state["owner"], _pdf("NEW A request 3"))
        worker.futures[1].set_result({"ticket": fresh, "pages": 1})
        slot.release()
        ui._advance_preview_queue(state)
        assert state["cache"]["activity"]["ticket"] == fresh
        assert store.available(state["owner"], fresh)
        assert store.pages(state["owner"], fresh, (0,))[0][1].startswith(bytes.fromhex("ffd8"))
        store.discard(state["owner"], fresh)
        assert store.stats()["pdf_bytes"] == store.stats()["raster_bytes"] == 0
    finally:
        store.close()


def test_same_filename_different_content_changes_section_preview_identity():
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    a = ReportSource("a" * 64, "same.pdf", "a" * 64, ".pdf")
    changed = replace(a, sha256="b" * 64)
    first = section_preview_fingerprint(replace(draft, sources=(a,)), "activity")
    again = section_preview_fingerprint(replace(draft, sources=(a,)), "activity")
    second = section_preview_fingerprint(replace(draft, sources=(changed,)), "activity")
    assert first == again, "Byte-identical duplicates should retain identity"
    assert first != second, "The same filename must not hide changed source bytes"
    assert section_preview_fingerprint(replace(draft, sources=(a,)), "cover") != (
        section_preview_fingerprint(replace(draft, sources=(changed,)), "cover"))
    next_month = replace(draft, period=ReportPeriod(2026, 10))
    assert section_preview_fingerprint(replace(next_month, sources=(a,)), "activity") != first


def test_two_owners_same_filename_retire_only_own_pdf_and_rasters():
    store = PreviewStore()
    try:
        alice = store.put("qa:alice:lease:site-a", _pdf("same.pdf owner A"))
        bob = store.put("qa:bob:lease:site-b", _pdf("same.pdf owner B"))
        old = store.pages("qa:alice:lease:site-a", alice, (0,))
        current = store.pages("qa:bob:lease:site-b", bob, (0,))
        assert old != current
        assert store.pages("qa:bob:lease:site-b", alice, (0,)) is None
        assert store.pages("qa:alice:lease:site-a", bob, (0,)) is None
        store.discard_owner_prefix("qa:alice:")
        assert not store.available("qa:alice:lease:site-a", alice)
        assert store.pages("qa:bob:lease:site-b", bob, (0,)) == current
        assert store.stats()["pdf_entries"] == store.stats()["raster_entries"] == 1
        store.discard("qa:bob:lease:site-b", bob)
        assert store.stats()["pdf_bytes"] == store.stats()["raster_bytes"] == 0
    finally:
        store.close()


def test_source_replacement_retires_old_images_without_discarding_other_owner(monkeypatch):
    store = PreviewStore()
    monkeypatch.setattr(ui, "STORE", store)
    draft = synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9))
    source_a = ReportSource("a" * 64, "same.pdf", "a" * 64, ".pdf")
    source_b = replace(source_a, sha256="b" * 64)
    state = {"owner": "qa:alice:lease:site-a", "wanted": {}, "queue": {},
             "requests": {}, "cache": {}, "last_good": {}, "ready_after": {}}
    try:
        ui._register_preview_request(state, "activity", "A",
                                     replace(draft, sources=(source_a,)), {}, "Activity")
        first = store.put(state["owner"], _pdf("first stale preview"))
        neighbor = store.put("qa:bob:lease:site-b", _pdf("neighbor current preview"))
        assert store.pages(state["owner"], first, (0,))
        neighbor_jpeg = store.pages("qa:bob:lease:site-b", neighbor, (0,))
        state["cache"]["activity"] = {"fingerprint": "A", "ticket": first}
        ui._register_preview_request(state, "activity", "B",
                                     replace(draft, sources=(source_b,)), {}, "Activity")
        assert not store.available(state["owner"], first)
        assert "activity" not in state["last_good"]
        assert "activity" not in state["cache"]
        assert store.pages("qa:bob:lease:site-b", neighbor, (0,)) == neighbor_jpeg
        assert store.stats()["pdf_entries"] == store.stats()["raster_entries"] == 1
    finally:
        store.close()


@pytest.mark.parametrize("bad_prefix", ["", "qa:alice", "qa:"])
def test_unscoped_owner_cache_deletion_is_rejected(bad_prefix):
    store = PreviewStore()
    try:
        ticket = store.put("qa:alice:lease:site-a", _pdf("keep me"))
        with pytest.raises(ValueError):
            store.discard_owner_prefix(bad_prefix)
        assert store.available("qa:alice:lease:site-a", ticket)
    finally:
        store.close()
