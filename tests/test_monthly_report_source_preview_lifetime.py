"""The displayed source page survives the next native review transition."""
from base64 import b64decode
from io import BytesIO
from pathlib import PurePosixPath
from types import SimpleNamespace

from PIL import Image
import pytest

from streamlit import runtime
from streamlit.elements.lib.image_utils import image_to_url
from streamlit.elements.lib.layout_utils import LayoutConfig
from streamlit.runtime import media_file_manager
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage

from app import monthly_report_upload_ui as ui
from test_monthly_report_section_uploads import button
from test_monthly_report_sources import pdf_bytes
from test_monthly_report_water_auto_include import _water_app


@pytest.mark.parametrize("route", ["section", "manager"])
def test_prior_source_thumbnail_stays_readable_after_next_page_retires_media(monkeypatch, tmp_path, route):
    captured = []
    original_image = ui.st.image

    def observe(image, *args, **kwargs):
        if kwargs.get("width") == 650:
            captured.append(image)
        return original_image(image, *args, **kwargs)

    monkeypatch.setattr(ui.st, "image", observe)
    raw = pdf_bytes(2)
    if route == "section":
        app = _water_app(monkeypatch, tmp_path, raw)
        first = captured[-1]
        button(app, "Include page and continue").click().run()
        assert next(w for w in app.selectbox if w.label == "Page to review").value == 2
        assert "water_reports" not in app.session_state["test_blocks"]
    else:
        from test_monthly_report_upload_ui import app_with_library, upload, select
        app, _ = app_with_library(monkeypatch, tmp_path)
        upload(monkeypatch, "synthetic.pdf", raw)
        app.run()
        button(app, "Read monthly files").click().run()
        first = captured[-1]
        select(app, "Preview page / item").set_value(2).run()
    assert not app.exception
    second = captured[-1]
    assert first != second

    # Use the pinned runtime's actual image conversion, media manager and
    # orphan cleanup. A delayed read of the first delivered image must work
    # after the next full render replaces its coordinate with page two.
    storage = MemoryMediaFileStorage("/media")
    manager = media_file_manager.MediaFileManager(storage)
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "exists", lambda: True)
        patch.setattr(runtime, "get_instance", lambda: SimpleNamespace(media_file_mgr=manager))
        patch.setattr(media_file_manager, "_get_session_id", lambda: "source-preview")
        first_url = image_to_url(first, LayoutConfig(width=650), False, "RGB", "auto", "review-page")
        manager.clear_session_refs("source-preview")
        second_url = image_to_url(second, LayoutConfig(width=650), False, "RGB", "auto", "review-page")
        manager.remove_orphaned_files()
        assert first_url != second_url
        if first_url.startswith("data:image/"):
            delivered = b64decode(first_url.split(",", 1)[1], validate=True)
        else:
            delivered = storage.get_file(PurePosixPath(first_url).stem).content
    with Image.open(BytesIO(delivered)) as image:
        image.load()
        assert image.width > 0 and image.height > 0


@pytest.mark.parametrize("extension", ["png", "jpg"])
def test_native_thumbnail_uses_only_the_exact_bounded_prepared_bytes(extension):
    from app.monthly_report_docx import ReportImage
    from app.monthly_report_source_preview import source_thumbnail_uri
    output = BytesIO()
    Image.new("RGB", (650, 840), "white").save(output, "PNG" if extension == "png" else "JPEG")
    prepared = ReportImage(output.getvalue(), extension, 650, 840)
    url = source_thumbnail_uri(prepared)
    assert b64decode(url.split(",", 1)[1], validate=True) == prepared.data
    assert len(url) < 3 * 1024 * 1024


@pytest.mark.parametrize("change", ["empty", "large_bytes", "large_width", "large_height", "invalid_size", "unsupported"])
def test_invalid_prepared_thumbnail_has_an_actionable_error(change):
    from dataclasses import replace
    from app.monthly_report_docx import ReportImage
    from app.monthly_report_source_preview import source_thumbnail_uri
    image = ReportImage(b"prepared bytes", "png", 650, 840)
    changes = {"empty": {"data": b""}, "large_bytes": {"data": b"x" * (2 * 1024 * 1024 + 1)},
               "large_width": {"width": 1057}, "large_height": {"height": 1057},
               "invalid_size": {"width": "650"}, "unsupported": {"extension": "svg"}}
    with pytest.raises(ValueError, match="Re-upload a smaller, readable copy"):
        source_thumbnail_uri(replace(image, **changes[change]))

