"""Binding processing limits remain actionable without discarding a review."""
from io import BytesIO
from zipfile import ZipFile

import pytest

from app import monthly_report_compatibility_view as view
from app import monthly_report_section_ui as ui
from test_monthly_report_source_frame_logo_role import source
from test_monthly_report_start_import import report_file, start_app


@pytest.mark.parametrize("budget, label", [
    ("MAX_VIEW_SOURCE_BYTES", "source byte budget"),
    ("MAX_VIEW_EXPANDED_BYTES", "capability package expansion budget"),
    ("MAX_VIEW_XML_BYTES", "capability XML byte budget"),
    ("MAX_VIEW_MEDIA_BYTES", "capability cumulative media byte budget"),
    ("MAX_VIEW_XML_NODES", "capability XML complexity budget"),
    ("MAX_VIEW_PARTS", "capability package part budget"),
    ("MAX_VIEW_XML_DEPTH", "capability XML depth budget"),
])
def test_binding_budget_names_exact_limit_before_inspection_and_recovers(tmp_path, monkeypatch, budget, label):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    successful = view.rederive_compatibility_view(path)
    real_inspect = view.inspect_docx
    with monkeypatch.context() as limited:
        limited.setattr(view, budget, 1)
        limited.setattr(view, "inspect_docx", lambda *a: pytest.fail("budget must precede inspection"))
        with pytest.raises(view.CompatibilityError) as refused:
            view.rederive_compatibility_view(path, successful.receipt_bytes)
        error = refused.value
        assert getattr(error, "budget", None) == label
        assert error.limit == 1 and error.observed > error.limit
        assert "limit is 1" in str(error)
    assert view.inspect_docx is real_inspect
    assert view.rederive_compatibility_view(path, successful.receipt_bytes) == successful
    assert path.read_bytes() == original


def test_primary_cleanup_failure_does_not_strand_successful_replacement(monkeypatch, tmp_path):
    path = report_file(tmp_path, activity=("September 2026 previous content.",))
    app = start_app(monkeypatch, tmp_path, path)
    stage_key = next(k for k in app.session_state.filtered_state if k.endswith("_stage"))
    previous = app.session_state[stage_key]
    cleanup = previous[0].cleanup
    def cannot_remove():
        raise OSError("synthetic previous directory busy")
    monkeypatch.setattr(previous[0], "cleanup", cannot_remove)
    replacement = report_file(tmp_path, activity=("September 2026 replacement content.",))
    upload = BytesIO(replacement.read_bytes())
    upload.name, upload.size = replacement.name, len(upload.getvalue())
    real_upload = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader", lambda label, *a, **kw: upload if label == "Starting report" else real_upload(label, *a, **kw))
    try:
        app.run()
        assert not app.exception
        assert app.session_state[stage_key][2].sha256 != previous[2].sha256
        assert not any(k.endswith("_failed_digest") for k in app.session_state.filtered_state)
        assert any("temporary review could not be removed" in w.value for w in app.warning)
        assert any(b.label == "Continue to this month’s updates" and not b.disabled for b in app.button)
        app.run()
        assert not app.exception
        assert any(b.label == "Continue to this month’s updates" and not b.disabled for b in app.button)
    finally:
        monkeypatch.setattr(previous[0], "cleanup", cleanup)
        cleanup()


def test_expanded_native_budget_ui_preserves_review_and_names_recovery(monkeypatch, tmp_path):
    path = source(tmp_path, divergent=True)
    original = path.read_bytes()
    with ZipFile(path) as archive:
        expanded = sum(item.file_size for item in archive.infolist())
    monkeypatch.setattr(view, "MAX_VIEW_EXPANDED_BYTES", expanded - 1)
    app = start_app(monkeypatch, tmp_path, path)
    warnings = " ".join(w.value for w in app.warning)
    assert "package expansion budget" in warnings and "limit is" in warnings
    assert "not evidence that the artwork is damaged" in warnings
    assert "independent template" in warnings
    assert path.read_bytes() == original
    assert not app.exception
