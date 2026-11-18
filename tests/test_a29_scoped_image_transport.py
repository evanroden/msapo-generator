"""A29: bounded image media URLs replace duplicate inline preview payloads.

The comparison is deterministic serialized application payload, not a claim of
network timing, Chromium paint or 512-MiB performance. Native media/owner
registration is exercised with Streamlit's real in-memory media manager.
"""
import re
from base64 import b64encode
from contextlib import nullcontext
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from streamlit.runtime import media_file_manager
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.runtime.media_file_storage import MediaFileStorageError
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

from app import monthly_report_picture_group as picture_group
from app import monthly_report_preview_view as view
from app.monthly_report_docx import ReportImage
from app.monthly_report_preview_store import PreviewTicket
from app.monthly_report_source_preview import source_thumbnail_bytes, source_thumbnail_uri


def jpeg(index):
    output = BytesIO()
    Image.new("RGB", (350, 430), (index * 19 % 255, index * 67 % 255, index * 113 % 255)).save(
        output, "JPEG", quality=87)
    return output.getvalue()


@pytest.fixture
def native(monkeypatch):
    storage = MemoryMediaFileStorage("/media")
    manager = MediaFileManager(storage)
    runtime = SimpleNamespace(media_file_mgr=manager)
    monkeypatch.setattr(media_file_manager, "_get_session_id", lambda: "a29-synthetic-session")
    monkeypatch.setattr(picture_group.Runtime, "instance", lambda: runtime)
    monkeypatch.setattr(picture_group.config, "get_option", lambda name: "reports")
    monkeypatch.setattr(view.st, "container", lambda **kwargs: nullcontext())
    delivered = []
    monkeypatch.setattr(view, "_preview_component", lambda runtime:
                        lambda **kwargs: delivered.append(kwargs))
    return manager, storage, delivered


@pytest.mark.parametrize("page_count", (2, 24, 96))
def test_native_preview_bytes_stable_and_bounded_across_full_rerenders(native, page_count):
    manager, storage, delivered = native
    ticket = PreviewTicket("a29-ticket-" + str(page_count), page_count,
                           ((612., 792.),) * page_count, 0)
    images = ((0, jpeg(1)), (1, jpeg(2)))
    original_digests = tuple(sha256(data).hexdigest() for _, data in images)
    for attempt in range(3):
        if attempt:
            manager.clear_session_refs("a29-synthetic-session")
        view.render_view(key="monthly_a29", generation="rev-1", title="Synthetic only",
                         ticket=ticket, images=images, view_scope="owner-a|site-a|month-a",
                         on_change=lambda: None)
        payload = delivered[-1]["data"]
        assert payload["ready"] and len(payload["sizes"]) == page_count
        assert len(payload["pages"]) == 2
        assert [page["index"] for page in payload["pages"]] == [0, 1]
        assert all(set(page) == {"index", "url"} for page in payload["pages"])
        assert all(page["url"].startswith("/reports/media/") for page in payload["pages"])
        assert all("data:image" not in str(page) for page in payload["pages"])
        manager.remove_orphaned_files()
        for page, (_, raw) in zip(payload["pages"], images):
            media_id = page["url"].rsplit("/", 1)[1].split(".")[0]
            assert storage.get_file(media_id).content == raw
        assert tuple(sha256(raw).hexdigest() for _, raw in images) == original_digests
    # Only two images were requested in the current viewport, irrespective
    # of PDF page count. No large repeated base64 image is in component data.
    native_pages = json.dumps(delivered[-1]["data"]["pages"]).encode()
    former_pages = json.dumps([{"index": i, "image": b64encode(raw).decode("ascii")}
                               for i, raw in images]).encode()
    assert len(native_pages) < len(former_pages) // 10
    assert delivered[0]["data"]["pages"] == delivered[1]["data"]["pages"] == delivered[2]["data"]["pages"]


def test_owner_and_ticket_change_rotate_coordinates_and_media(native, monkeypatch):
    manager, storage, delivered = native
    ticket = PreviewTicket("ticket-a", 2, ((612., 792.),) * 2, 0)
    coordinates = []
    actual = view._media_url

    def observe(raw, mime, coordinate):
        coordinates.append(coordinate)
        return actual(raw, mime, coordinate)

    monkeypatch.setattr(view, "_media_url", observe)
    images = ((0, jpeg(9)),)
    view.render_view(key="key", generation="revision-a", title="Synthetic",
                     ticket=ticket, images=images, view_scope="owner-a|site-a|2026-09",
                     on_change=lambda: None)
    first = delivered[-1]["data"]["pages"][0]["url"]
    manager.clear_session_refs("a29-synthetic-session")
    replacement = ((0, jpeg(10)),)
    view.render_view(key="key", generation="revision-b", title="Synthetic",
                     ticket=replace(ticket, key="ticket-b"), images=replacement,
                     view_scope="owner-b|site-b|2026-10", on_change=lambda: None)
    later = delivered[-1]["data"]["pages"][0]["url"]
    assert first != later
    assert "owner-a|site-a|2026-09:ticket-a" in coordinates[0]
    assert "owner-b|site-b|2026-10:ticket-b" in coordinates[1]
    manager.remove_orphaned_files()
    with pytest.raises(MediaFileStorageError):
        storage.get_file(first.rsplit("/", 1)[1].split(".")[0])
    assert storage.get_file(later.rsplit("/", 1)[1].split(".")[0]).content == replacement[0][1]


@pytest.mark.parametrize("mode", ("missing", "stale"))
def test_unavailable_or_stale_ticket_does_not_publish_image_bytes(native, mode):
    _, _, delivered = native
    ticket = PreviewTicket("private", 2, ((612., 792.),) * 2, 0)
    view.render_view(key="key", generation="stale", title="Synthetic",
                     ticket=None if mode == "missing" else ticket, stale=mode == "stale",
                     images=((0, jpeg(1)),), on_change=lambda: None)
    pages = delivered[-1]["data"]["pages"]
    if mode == "missing":
        assert pages == []
    else:
        # A stale ticket keeps its last-good page inspectable (labelled not
        # ready), as main's preview contract requires, but still only as a
        # scoped media URL: no image bytes or base64 in the payload.
        assert delivered[-1]["data"]["ready"] is False
        assert [sorted(page) for page in pages] == [["index", "url"]]
        assert re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)*media/[a-f0-9]{32}\.jpe?g", pages[0]["url"])


@pytest.mark.parametrize("kind", ("png", "jpg"))
def test_source_gallery_native_transport_retains_exact_prepared_pixels(kind):
    output = BytesIO()
    Image.new("RGB", (160, 220), "blue").save(output, "PNG" if kind == "png" else "JPEG")
    image = ReportImage(output.getvalue(), kind, 160, 220)
    assert source_thumbnail_bytes(image) == image.data
    assert source_thumbnail_uri(image).startswith("data:image/")


@pytest.mark.parametrize("change", (
    {"data": b""}, {"data": b"x" * (2 * 1024 * 1024 + 1)},
    {"extension": "svg"}, {"width": -1}, {"height": 1057},
    {"width": 1056.0},
))
def test_source_gallery_rejects_unbounded_or_malformed_prepared_image(change):
    image = ReportImage(b"synthetic", "jpg", 160, 220)
    with pytest.raises(ValueError, match="smaller, readable copy"):
        source_thumbnail_bytes(replace(image, **change))
