"""Shared-template UI uses disposable synthetic storage and invented DOCX."""
from io import BytesIO
from pathlib import Path

from docx import Document
from streamlit.testing.v1 import AppTest

from app import monthly_report_shared_testing_ui as shared_ui
from app import monthly_report_shared_templates_ui as ui
from app.monthly_report_shared_templates import MAX_TEMPLATE_BYTES, SharedReportTemplates


def original():
    document = Document()
    document.add_paragraph("Invented report template")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


class Upload:
    def __init__(self, raw):
        self.raw = raw
        self.size = len(raw)
        self.name = "Synthetic report.docx"

    def getvalue(self):
        return self.raw


def test_pending_upload_preserves_report_state_and_clears_only_completed_upload(tmp_path, monkeypatch):
    raw = original()
    upload_key = "_shared_template_file_0"
    state = {upload_key: Upload(raw), "report_draft": object(), "report_editor": "kept"}
    draft = state["report_draft"]
    monkeypatch.setattr(ui.st, "session_state", state)
    ui._queue_upload(upload_key)
    first = dict(state[ui._PENDING])
    ui._queue_upload("another")
    assert state[ui._PENDING] == first
    shared_ui._process_pending(None, "unused-token", tmp_path)
    assert state["report_draft"] is draft and state["report_editor"] == "kept"
    assert ui._PENDING not in state and upload_key not in state
    assert state["_shared_template_generation"] == 1
    assert SharedReportTemplates(tmp_path).download(state["_shared_template_selection"]) == raw
    assert {p.name for p in tmp_path.iterdir()} == {"_enfra_shared_report_templates_v1"}


def test_oversized_upload_refused_before_read_preserves_retry_and_report(tmp_path, monkeypatch):
    class TooLarge:
        size = MAX_TEMPLATE_BYTES + 1
        def getvalue(self):
            raise AssertionError("Oversized upload must not be materialized")
    key = "_shared_template_file_0"
    state = {key: TooLarge(), "report_editor": "kept"}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui._queue_upload(key)
    shared_ui._process_pending(None, "unused-token", tmp_path)
    assert "512 MiB" in state["_shared_fixture_error"]
    assert key in state and "_shared_template_generation" not in state
    assert state["report_editor"] == "kept" and ui._PENDING not in state
    assert not tuple(tmp_path.iterdir())


def test_new_browser_lists_stored_original_and_only_prepare_reads_large_bytes(tmp_path, monkeypatch):
    raw = original()
    receipt = SharedReportTemplates(tmp_path).upload(raw, "Synthetic report.docx")
    script = f'''from app.monthly_report_shared_templates_ui import render
render({str(tmp_path)!r})
'''
    calls = []
    download = SharedReportTemplates.download
    def observed(self, identity):
        calls.append(identity)
        return download(self, identity)
    monkeypatch.setattr(SharedReportTemplates, "download", observed)
    app = AppTest.from_string(script).run()
    assert not app.exception and not calls
    assert app.button(key="_shared_template_save").disabled
    assert "Synthetic report.docx" in app.selectbox[0].options[0]
    assert app.get("file_uploader")[0].proto.max_upload_size_mb == 512
    key = "_shared_template_prepare_" + receipt.bundle_id + "_" + receipt.archive_sha256[:16]
    app.button(key=key).click().run()
    assert not app.exception and calls == [receipt.bundle_id]
    app.run()
    assert not app.exception and calls == [receipt.bundle_id]
    second_browser = AppTest.from_string(script).run()
    assert not second_browser.exception
    assert second_browser.selectbox[0].value == receipt.bundle_id
    assert not second_browser.get("download_button")
