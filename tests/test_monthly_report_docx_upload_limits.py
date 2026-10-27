"""Shared DOCX staging and upload guidance use the enforced route byte cap."""
from io import BytesIO
from types import SimpleNamespace

import pytest

from app import monthly_report_import_ui as ui
from app.monthly_report_upload_limits import MIB, byte_limit_label


class Upload(BytesIO):
    def __init__(self, raw, *, reported_size=None):
        super().__init__(raw)
        self.size = len(raw) if reported_size is None else reported_size
        self.name = "synthetic.docx"


@pytest.mark.parametrize("size", [31, 32])
def test_stage_below_and_at_byte_limit_preserves_original(tmp_path, monkeypatch, size):
    monkeypatch.setattr(ui, "MAX_DOCX_BYTES", 32)
    monkeypatch.setattr(ui.library, "_root", lambda: tmp_path)
    seen = []
    marker = object()
    def inspect(path):
        seen.append(path.read_bytes())
        return marker
    monkeypatch.setattr(ui, "inspect_docx", inspect)
    original = b"x" * size
    uploaded = Upload(original)
    temporary, path, result = ui._stage(uploaded)
    try:
        assert result is marker
        assert seen == [original] and path.read_bytes() == original
        assert uploaded.getvalue() == original and uploaded.tell() == 0
    finally:
        temporary.cleanup()
    assert not list((tmp_path / "imports").iterdir())


def test_oversize_metadata_uses_actual_cap_before_read_or_directory_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_DOCX_BYTES", 32)
    monkeypatch.setattr(ui.library, "_root", lambda: tmp_path)
    uploaded = Upload(b"x" * 33)
    def unexpected(*args):
        pytest.fail("Oversize metadata must be rejected before reading or parsing.")
    monkeypatch.setattr(uploaded, "read", unexpected)
    monkeypatch.setattr(ui, "inspect_docx", unexpected)
    with pytest.raises(ValueError, match="32 bytes import limit") as error:
        ui._stage(uploaded)
    assert "keep the original unchanged" in str(error.value)
    assert uploaded.getvalue() == b"x" * 33
    assert not (tmp_path / "imports").exists()


def test_streamed_oversize_rejects_understated_metadata_and_cleans_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_DOCX_BYTES", 32)
    monkeypatch.setattr(ui.library, "_root", lambda: tmp_path)
    uploaded = Upload(b"x" * 33, reported_size=31)
    monkeypatch.setattr(ui, "inspect_docx", lambda path: pytest.fail("Oversize stream reached parser."))
    with pytest.raises(ValueError, match="32 bytes import limit"):
        ui._stage(uploaded)
    assert uploaded.getvalue() == b"x" * 33 and uploaded.tell() == 0
    assert not list((tmp_path / "imports").iterdir())


def test_parser_rejection_retains_original_and_its_specific_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "MAX_DOCX_BYTES", 32)
    monkeypatch.setattr(ui.library, "_root", lambda: tmp_path)
    def reject(path):
        raise ValueError("Synthetic expanded-content budget exceeded.")
    monkeypatch.setattr(ui, "inspect_docx", reject)
    uploaded = Upload(b"synthetic")
    with pytest.raises(ValueError, match="expanded-content budget exceeded"):
        ui._stage(uploaded)
    assert uploaded.getvalue() == b"synthetic" and uploaded.tell() == 0
    assert not list((tmp_path / "imports").iterdir())


def test_native_import_uploader_and_help_follow_actual_limits(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ui, "MAX_DOCX_BYTES", 2*MIB)
    monkeypatch.setattr(ui, "MAX_EXPANDED_BYTES", 7*MIB)
    monkeypatch.setattr(ui, "MAX_MEMBER_BYTES", 3*MIB)
    monkeypatch.setattr(ui, "MAX_XML_BYTES", MIB)
    monkeypatch.setattr(ui, "MAX_XML_TOTAL", 2*MIB)
    monkeypatch.setattr(ui, "MAX_NORMALIZED_BYTES", 4*MIB)
    app = AppTest.from_string('''
from types import SimpleNamespace
from app.monthly_report_import_ui import render_import
profile = SimpleNamespace(contract="synthetic", key="upload-limit")
render_import(SimpleNamespace(profile=profile), lambda key, value: key)
''').run()
    assert not app.exception
    uploader, = app.get("file_uploader")
    assert uploader.proto.max_upload_size_mb == 2
    assert "7 MiB expanded DOCX" in uploader.proto.help
    assert "3 MiB per embedded file" in uploader.proto.help
    assert "1 MiB per XML part and 2 MiB total XML" in uploader.proto.help
    assert "4 MiB budget" in uploader.proto.help
    assert any("Up to 2 MiB per DOCX" in caption.value for caption in app.caption)
    first_id = uploader.id
    app.run()
    assert not app.exception and app.get("file_uploader")[0].id == first_id


def test_template_storage_guidance_does_not_promise_import_capability(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from app import monthly_report_shared_templates_ui as templates
    monkeypatch.setattr(templates, "MAX_TEMPLATE_BYTES", 5*MIB)
    monkeypatch.setattr(templates, "MAX_DOCX_BYTES", 2*MIB)
    monkeypatch.setattr(templates, "SharedReportTemplates",
                        lambda root: SimpleNamespace(list=lambda: ()))
    app = AppTest.from_string('''
from app.monthly_report_shared_templates_ui import render
render("synthetic-unused-root")
''').run()
    assert not app.exception
    uploader, = app.get("file_uploader")
    assert uploader.proto.max_upload_size_mb == 5
    assert any("5 MiB" in c.value and "storage, not report import (up to 2 MiB" in c.value
               for c in app.caption)
    assert any("does not update the company master or any report" in c.value for c in app.caption)


def test_template_oversize_error_uses_storage_cap_without_consuming_upload(monkeypatch, tmp_path):
    from app import monthly_report_shared_templates_ui as templates
    uploaded = Upload(b"x" * 33)
    state = {"file": uploaded, "_shared_template_selection": "retained-selection"}
    monkeypatch.setattr(templates.st, "session_state", state)
    monkeypatch.setattr(templates, "MAX_TEMPLATE_BYTES", 32)
    monkeypatch.setattr(templates, "SharedReportTemplates",
                        lambda root: pytest.fail("Oversize file reached template storage."))
    with pytest.raises(ValueError, match="32 bytes upload limit"):
        templates.save_pending(tmp_path, "file")
    assert state == {"file": uploaded, "_shared_template_selection": "retained-selection"}
    assert uploaded.getvalue() == b"x" * 33
