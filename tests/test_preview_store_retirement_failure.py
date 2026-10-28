"""Failed removal keeps owned PDF bytes bounded while retiring private views."""
from pathlib import Path
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from app.monthly_report_preview_store import PreviewStore
from test_expense_preview_cleanup import preview_model


def pdf_bytes(label):
    with fitz.open() as document:
        document.new_page(width=200, height=200).insert_text((15, 30), label)
        return document.tobytes()


@pytest.fixture
def removal_failure(monkeypatch):
    state = SimpleNamespace(blocked=set(), attempts={})
    unlink = Path.unlink
    def remove(path, *args, **kwargs):
        state.attempts[path] = state.attempts.get(path, 0) + 1
        if path in state.blocked:
            raise PermissionError("Synthetic temporary deletion failure")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", remove)
    yield state
    state.blocked.clear()


def test_failed_unlink_retires_view_and_rasters_but_keeps_owned_disk_accounting(removal_failure):
    store = PreviewStore()
    removed_raw, kept_raw = pdf_bytes("Synthetic removed receipt"), pdf_bytes("Synthetic kept receipt")
    removed = store.put("removed-owner", SimpleNamespace(pdf=removed_raw))
    kept = store.put("kept-owner", SimpleNamespace(pdf=kept_raw))
    removed_path, kept_path = (store._files[ticket.key].path for ticket in (removed, kept))
    store.pages("removed-owner", removed, (0,), dpi=96)
    kept_images = store.pages("kept-owner", kept, (0,), dpi=96)
    removal_failure.blocked.add(removed_path)
    try:
        store.discard("removed-owner", removed)
        assert removed_path.read_bytes() == removed_raw
        assert not store.available("removed-owner", removed)
        assert store.pages("removed-owner", removed, (0,), dpi=96) is None
        assert all(key[0] != removed.key for key in store._rasters)
        assert store.stats()["pdf_bytes"] == len(removed_raw) + len(kept_raw)
        assert store.stats()["raster_entries"] == 1
        assert kept_path.read_bytes() == kept_raw
        assert store.pages("kept-owner", kept, (0,), dpi=96) == kept_images
        removal_failure.blocked.clear()
        assert store.stats()["pdf_bytes"] == len(kept_raw)
        assert not removed_path.exists() and kept_path.read_bytes() == kept_raw
        assert store.stats()["pdf_entries"] == 1
    finally:
        removal_failure.blocked.clear()
        store.close()


def test_pending_deletion_cannot_bypass_disk_budget_or_spin_eviction(removal_failure):
    raw = pdf_bytes("Synthetic bounded cache")
    store = PreviewStore(disk_bytes=len(raw), max_entries=1)
    ticket = store.put("owner", SimpleNamespace(pdf=raw))
    path = store._files[ticket.key].path
    removal_failure.blocked.add(path)
    try:
        store.discard("owner", ticket)
        before = removal_failure.attempts[path]
        with pytest.raises(OSError, match="temporary files"):
            store.put("new-owner", SimpleNamespace(pdf=raw))
        assert 1 <= removal_failure.attempts[path] - before <= 2
        assert list(Path(store._directory.name).iterdir()) == [path]
        assert store.stats()["pdf_bytes"] == len(raw)
        removal_failure.blocked.clear()
        replacement = store.put("new-owner", SimpleNamespace(pdf=raw))
        assert replacement != ticket and not path.exists()
        assert store.available("new-owner", replacement)
        assert store.stats()["pdf_bytes"] == len(raw)
    finally:
        removal_failure.blocked.clear()
        store.close()


def test_failed_expiry_retires_only_expired_ticket_and_retries_once_per_scan(removal_failure, monkeypatch):
    from app import monthly_report_preview_store as previews
    now = [0.0]
    monkeypatch.setattr(previews, "monotonic", lambda: now[0])
    store = PreviewStore(max_age=10)
    first = store.put("first-owner", SimpleNamespace(pdf=pdf_bytes("Synthetic expired")))
    first_path = store._files[first.key].path
    store.pages("first-owner", first, (0,), dpi=96)
    now[0] = 5
    kept = store.put("kept-owner", SimpleNamespace(pdf=pdf_bytes("Synthetic active")))
    removal_failure.blocked.add(first_path)
    try:
        now[0] = 11
        store.stats()
        before = removal_failure.attempts[first_path]
        assert not store.available("first-owner", first)
        assert removal_failure.attempts[first_path] == before + 1
        assert store.available("kept-owner", kept)
        assert all(key[0] != first.key for key in store._rasters)
        removal_failure.blocked.clear()
        store.stats()
        assert not first_path.exists() and store.available("kept-owner", kept)
    finally:
        removal_failure.blocked.clear()
        store.close()


def test_receipt_removal_survives_failed_delete_without_reviving_old_callbacks(preview_model, removal_failure):
    from app import expense_ui
    harness = preview_model
    removed = harness.render(pdf_bytes("Synthetic removed"))
    kept = harness.render(pdf_bytes("Synthetic kept"))
    harness.state["expense_receipt_files"] = [
        ("removed.pdf", removed.raw, "application/pdf"),
        ("kept.pdf", kept.raw, "application/pdf"),
    ]
    removed_path, kept_path = (harness.materialize(item) for item in (removed, kept))
    removal_failure.blocked.add(removed_path)
    expense_ui._remove_receipt_from_draft(removed.digest)
    assert removed.key not in removed.owner["entries"]
    assert harness.state["expense_receipt_files"] == [("kept.pdf", kept.raw, "application/pdf")]
    view_count = len(harness.views)
    harness.request(removed)
    removed.surface()
    assert len(harness.views) == view_count
    assert not harness.store.available(removed.owner["owner"], removed.entry["ticket"])
    assert kept_path.read_bytes() == kept.raw
    assert harness.store.available(kept.owner["owner"], kept.entry["ticket"])
    assert harness.store.stats()["pdf_bytes"] == len(removed.raw) + len(kept.raw)
    removal_failure.blocked.clear()
    harness.store.stats()
    assert not removed_path.exists() and kept_path.read_bytes() == kept.raw


def test_close_clears_accounting_after_directory_cleanup_recovers(monkeypatch):
    store = PreviewStore()
    ticket = store.put("owner", SimpleNamespace(pdf=pdf_bytes("Synthetic close")))
    path = store._files[ticket.key].path
    directory = Path(store._directory.name)
    unlink = Path.unlink
    def fail_once(target, *args, **kwargs):
        if target == path:
            monkeypatch.setattr(Path, "unlink", unlink)
            raise PermissionError("Synthetic one-time deletion failure")
        return unlink(target, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_once)
    store.close()
    assert not directory.exists()
    assert store.stats() == {"pdf_bytes": 0, "raster_bytes": 0, "pdf_entries": 0, "raster_entries": 0}
