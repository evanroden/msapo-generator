"""Explicit retry recovers a failed section file without replaying report edits."""
from io import BytesIO

from streamlit.testing.v1 import AppTest

from app import monthly_report_sources as sources, monthly_report_upload_ui as ui
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from test_monthly_report_section_uploads import APP
from test_monthly_report_sources import pdf_bytes


def _file(name, raw):
    stream = BytesIO(raw)
    stream.name = name
    return stream


def test_retry_recovers_failed_file_and_keeps_sibling_and_manual_content(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    uploads = [_file("good.pdf", pdf_bytes(1)), _file("retry.pdf", pdf_bytes(2))]
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, **kwargs:
                        uploads if label == "Service report files" else [])
    original = sources.ingest
    attempts = []
    def ingest(profile, filename, raw):
        attempts.append(filename)
        if filename == "retry.pdf" and attempts.count(filename) == 1:
            raise OSError("Synthetic transient reader failure")
        return original(profile, filename, raw)
    monkeypatch.setattr(sources, "ingest", ingest)
    app = AppTest.from_string(APP, default_timeout=20)
    manual = ResolvedBlock("equipment_issues", "This month", text="Keep this manual issue.")
    app.session_state["test_blocks"] = {manual.key: manual}
    app.run()
    assert not app.exception
    sibling, = app.session_state["test_sources"]
    retry = next(b for b in app.button if b.label == "Retry unread files")
    assert any("retry.pdf" in w.value for w in app.warning)
    app.run()
    assert attempts == ["good.pdf", "retry.pdf"]
    retry.click().run()
    assert not app.exception
    assert attempts == ["good.pdf", "retry.pdf", "retry.pdf"]
    assert app.session_state["test_sources"][0] == sibling
    assert len(app.session_state["test_sources"]) == 2
    assert [sources.source_bytes(synthetic_profiles()[0], source)
            for source in app.session_state["test_sources"]] == [u.getvalue() for u in uploads]
    assert app.session_state["test_blocks"] == {manual.key: manual}
    assert not app.session_state["test_additions"]
    assert not any(b.label == "Retry unread files" for b in app.button)
    assert not any("Not read:" in w.value for w in app.warning)
    app.run()
    assert attempts == ["good.pdf", "retry.pdf", "retry.pdf"]


def test_failed_selection_can_be_replaced_without_retrying_old_bytes(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    uploads = [_file("bad.pdf", b"broken")]
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, **kwargs:
                        uploads if label == "Service report files" else [])
    app = AppTest.from_string(APP, default_timeout=20).run()
    assert not app.exception
    assert any(b.label == "Retry unread files" for b in app.button)
    uploads[:] = [_file("replacement.pdf", pdf_bytes(1))]
    app.run()
    assert not app.exception
    assert [s.filename for s in app.session_state["test_sources"]] == ["replacement.pdf"]
    assert not any(b.label == "Retry unread files" for b in app.button)
    assert not app.session_state["test_additions"]


def test_retired_retry_cannot_clear_another_selection_or_section(monkeypatch):
    state = {"section_a_read": "new", "section_b_read": "old"}
    monkeypatch.setattr(ui.st, "session_state", state)
    ui._retry_section_upload("section_a", "old")
    assert state == {"section_a_read": "new", "section_b_read": "old"}
    ui._retry_section_upload("section_b", "old")
    assert state == {"section_a_read": "new"}


def test_repeated_failure_requires_deliberate_retry_and_clear_removes_action(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    uploads = [_file("bad.pdf", b"broken")]
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, **kwargs:
                        uploads if label == "Service report files" else [])
    original = sources.ingest_batch
    calls = []
    def ingest(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(sources, "ingest_batch", ingest)
    app = AppTest.from_string(APP, default_timeout=20).run()
    next(b for b in app.button if b.label == "Retry unread files").click().run()
    assert not app.exception
    assert len(calls) == 2
    app.run()
    assert len(calls) == 2
    assert not app.session_state["test_sources"]
    uploads.clear()
    app.run()
    assert not any(b.label == "Retry unread files" for b in app.button)
    assert len(calls) == 2
