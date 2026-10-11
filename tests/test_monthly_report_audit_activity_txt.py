"""October 10 audit §9.1, original ambiguity-preserving activity.txt regression."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from app import monthly_report_sources as sources, monthly_report_structured_uploads as structured
from app.monthly_report_model import ResolvedBlock, synthetic_profiles
from test_monthly_report_ui import monthly

AUDIT_SOURCE = Path(__file__).resolve().parent / "fixtures" / "rrh_audit_activity_v1.txt"


def _source(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return sources.ingest(synthetic_profiles()[0], "activity.txt", AUDIT_SOURCE.read_bytes())[0]


def test_exact_audit_txt_ingests_and_places_vendor_work_but_not_other_section_claims(monkeypatch, tmp_path):
    content = _source(monkeypatch, tmp_path)
    assert content.source.filename == "activity.txt"
    assert "RRH Tester – UX Review 2026-10-09" in content.source.page_texts[0]
    original = ResolvedBlock("activity_summary", "This month", text="Keep manually accepted note.")
    result = structured.native_update((content,), "activity_summary", original)
    assert "Keep manually accepted note." in result.text
    assert "Completed strainer cleaning and leak inspection" in result.text
    assert "Example Mechanical QA Services replaced two filter-bank inserts" in result.text
    for not_activity in ("45-minute lockout/tagout", "pH 8.2", "awaiting\nclient response",
                         "66.7%", "Open at month-end"):
        assert not_activity not in result.text
    assert result.references == (sources.source_reference(content.source, 1),)


def test_reupload_preserves_deliberate_deletions_or_corrections(monkeypatch, tmp_path):
    content = _source(monkeypatch, tmp_path)
    initial = structured.native_update((content,), "activity_summary")
    current = replace(initial, source="This month", text="Deliberately corrected site summary.")
    again = structured.native_update((content,), "activity_summary", current)
    assert again.text == current.text and again.references == current.references
    revised = AUDIT_SOURCE.read_bytes() + b"\n2026-09-29 | WO-TEST-1004 | PM label\nCompleted generator test inspection.\n"
    changed, _ = sources.ingest(synthetic_profiles()[0], "activity.txt", revised)
    assert changed.source.id != content.source.id
    next_block = structured.native_update((changed,), "activity_summary", again)
    assert "Completed generator test inspection." in next_block.text
    assert next_block.text.startswith(current.text)
    assert "45-minute" not in next_block.text
    assert structured.native_update((changed,), "activity_summary", next_block).text == next_block.text


def test_audit_activity_upload_has_manual_offline_reader_path(monkeypatch, tmp_path):
    from app import monthly_report_upload_ui as ui, monthly_report_ai as ai
    app = monthly(monkeypatch, tmp_path)
    stream = BytesIO(AUDIT_SOURCE.read_bytes())
    stream.name = "activity.txt"
    previous = ui.st.file_uploader
    monkeypatch.setattr(ui.st, "file_uploader",
        lambda label,*args,**kwargs:
        [stream] if label == "Upload activity reports and supporting files"
        else previous(label,*args,**kwargs))
    monkeypatch.setattr(ai, "ANTHROPIC_API_KEY", "")
    app.run()
    assert not app.exception
    editor = next(w for w in app.text_area if w.label == "Activity summary")
    assert "Example Mechanical QA Services replaced" in editor.value
    assert "pH 8.2" not in editor.value
    assert not any("Expecting value:" in w.value for w in app.error)
    editor.set_value("My corrected September Activity.").run()
    assert not app.exception
    app.run()
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "My corrected September Activity.")
