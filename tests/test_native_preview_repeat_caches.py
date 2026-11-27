"""Repeat section previews reuse content-addressed proofs, never stale ones."""
from types import SimpleNamespace

import pytest

from app import monthly_report_native_art_review as art
from app import monthly_report_native_layout as layout


def _view(original="o" * 64, rendition=b"rendition", receipt="r" * 64):
    return SimpleNamespace(
        original_inspection=SimpleNamespace(sha256=original),
        rendition_inspection=SimpleNamespace(sha256="n" * 64),
        rendition_bytes=rendition, receipt_sha256=receipt)


def test_physical_scan_runs_once_per_verified_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(art, "Document", lambda stream: stream)
    monkeypatch.setattr(art, "_physical_inventory",
                        lambda document, inspection, wanted: calls.append(1) or {"a": ("x",)})
    pair = ((SimpleNamespace(id="a"), SimpleNamespace(id="b")),)
    first = art._physical_pair(b"raw", _view(), pair)
    assert art._physical_pair(b"raw", _view(), pair) == first
    assert len(calls) == 2  # original and rendition, once
    art._physical_pair(b"raw", _view(rendition=b"changed"), pair)
    art._physical_pair(b"raw", _view(receipt="s" * 64), pair)
    assert len(calls) == 6


def test_cached_physical_scan_still_meets_the_budget(monkeypatch):
    monkeypatch.setattr(art, "Document", lambda stream: stream)
    monkeypatch.setattr(art, "_physical_inventory",
                        lambda document, inspection, wanted: {"a": ("x", "y")})
    pair = ((SimpleNamespace(id="a"), SimpleNamespace(id="b")),)
    art._physical_pair(b"raw", _view(), pair)
    monkeypatch.setattr(art, "MAX_REPRESENTATIONS", 1)
    with pytest.raises(art.CompatibilityError, match="budget"):
        art._physical_pair(b"raw", _view(), pair)


def test_scan_errors_are_not_cached(monkeypatch):
    monkeypatch.setattr(art, "Document", lambda stream: stream)
    state = {"fail": True}

    def scan(document, inspection, wanted):
        if state["fail"]:
            raise art.CompatibilityError("scan failed")
        return {"a": ("x",)}
    monkeypatch.setattr(art, "_physical_inventory", scan)
    pair = ((SimpleNamespace(id="a"), SimpleNamespace(id="b")),)
    with pytest.raises(art.CompatibilityError):
        art._physical_pair(b"raw", _view(), pair)
    state["fail"] = False
    assert art._physical_pair(b"raw", _view(), pair)[0] == {"a": ("x",)}


def test_view_image_digest_keys_on_content_not_path(monkeypatch):
    reads = []
    monkeypatch.setattr(layout._source_image_digest, "__wrapped__",
                        lambda path, identity, item, line_art, preserve=None:
                        reads.append(path) or f"{identity}-{item}-{line_art}-{preserve}")
    first = layout._view_image_digest("/tmp/a/rendition.docx", "id-1", "item", False)
    assert layout._view_image_digest("/tmp/b/rendition.docx", "id-1", "item", False) == first
    assert reads == ["/tmp/a/rendition.docx"]
    layout._view_image_digest("/tmp/b/rendition.docx", "id-2", "item", False)
    layout._view_image_digest("/tmp/b/rendition.docx", "id-1", "item", True)
    layout._view_image_digest("/tmp/b/rendition.docx", "id-1", "item", True, True)
    layout._view_image_digest("/tmp/b/rendition.docx", "id-1", "other", False)
    assert len(reads) == 5
