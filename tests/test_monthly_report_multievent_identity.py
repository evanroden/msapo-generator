"""Avoid assigning a whole-document vendor/date to unrelated Activity events.

Synthetic DOCX/TXT evidence only; exact originals, references and operator
edits stay authoritative. This does not infer per-event facts or owner approval.
"""
from dataclasses import replace
from io import BytesIO

from docx import Document

from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import ReportSource, synthetic_profiles
from app.monthly_report_sources import SourceContent


def _ingest_docx(monkeypatch, tmp_path, paragraphs):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    for passage in paragraphs:
        doc.add_paragraph(passage)
    body = BytesIO()
    doc.save(body)
    raw = body.getvalue()
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "vendor-events.docx", raw)
    return profile, raw, content


def test_real_docx_with_two_vendors_and_service_dates_does_not_misattribute_events(
        monkeypatch, tmp_path):
    profile, raw, content = _ingest_docx(monkeypatch, tmp_path, (
        "Vendor: Trane",
        "Service date: 2026-09-04",
        "Inspected synthetic cooling pump. Repair remains pending.",
        "Vendor: Johnson Controls",
        "Service date: 2026-09-18",
        "Calibrated synthetic control panel. Further inspection was recommended.",
    ))
    # The original source suggestion may select only its first header; it is
    # retained for source review but must not be copied to unrelated events.
    assert content.source.vendor == "Trane"
    assert content.source.service_date == "2026-09-04"
    original_identity = content.source.id
    result = structured.native_update((content,), "activity_summary")
    assert "Inspected synthetic cooling pump." in result.text
    assert "Calibrated synthetic control panel." in result.text
    assert "2026-09-04 · Trane —" not in result.text
    assert "2026-09-18 · Johnson Controls —" not in result.text
    assert "Trane —" not in result.text
    assert "2026-09-04 —" not in result.text
    assert len(result.references) == 2
    assert all(ref.startswith(original_identity + ":") for ref in result.references)
    assert sources.source_bytes(profile, content.source) == raw
    assert structured.native_update((content,), "activity_summary", result) == result


def test_two_dates_with_one_explicit_vendor_suppress_date_only(monkeypatch, tmp_path):
    _, _, content = _ingest_docx(monkeypatch, tmp_path, (
        "Vendor: Trane",
        "Service date: 2026-09-04",
        "Inspected compressor. Follow-up scheduled on 10/01/2026.",
    ))
    assert content.source.vendor == "Trane"
    result = structured.native_update((content,), "activity_summary")
    assert "Trane — Inspected compressor." in result.text
    assert "2026-09-04 · Trane" not in result.text
    assert "10/01/2026" in result.text


def test_two_vendor_labels_with_one_date_suppress_vendor_only():
    from app.monthly_report_structured_uploads import _non_table_activity_identity
    source = ReportSource("a" * 64, "synthetic.docx", "a" * 64, ".docx",
                          vendor="Trane", service_date="2026-09-12",
                          page_texts=("Vendor: Trane", "Vendor: Johnson Controls",
                                      "Service date: 2026-09-12",
                                      "Inspected controller."))
    content = SourceContent(source)
    guarded = _non_table_activity_identity(source)
    assert guarded.vendor == ""
    assert guarded.service_date == "2026-09-12"
    assert source.vendor == "Trane"
    result = structured.native_update((content,), "activity_summary")
    assert result.text == "2026-09-12 — Inspected controller."


def test_repeated_one_date_and_same_vendor_keep_verified_source_identity():
    source = ReportSource("a" * 64, "synthetic.docx", "a" * 64, ".docx",
                          vendor="Trane", service_date="2026-09-12",
                          page_texts=("Vendor: Trane", "Service date: 2026-09-12",
                                      "Vendor: Trane", "Completed date: 09/12/2026",
                                      "Inspected chiller."))
    content = SourceContent(source)
    result = structured.native_update((content,), "activity_summary")
    assert result.text == "2026-09-12 · Trane — Inspected chiller."


def test_invalid_second_date_does_not_hide_verified_single_date():
    source = ReportSource("a" * 64, "synthetic.docx", "a" * 64, ".docx",
                          vendor="Trane", service_date="2026-09-12",
                          page_texts=("Vendor: Trane", "Service date: 2026-09-12",
                                      "Wrong date: 2026-99-99",
                                      "Inspected synthetic pump."))
    result = structured.native_update((SourceContent(source),), "activity_summary")
    assert result.text == "2026-09-12 · Trane — Inspected synthetic pump."


def test_operator_deleted_source_action_remains_deleted_after_source_date_correction():
    source = ReportSource("a" * 64, "synthetic.docx", "a" * 64, ".docx",
                          vendor="Trane", service_date="2026-09-04",
                          page_texts=("Vendor: Trane", "Service date: 2026-09-04",
                                      "Serviced synthetic motor.",
                                      "Service date: 2026-09-19",
                                      "Inspected synthetic pump."))
    content = SourceContent(source)
    initial = structured.native_update((content,), "activity_summary")
    corrected = replace(content, source=replace(source, service_date="2026-09-22"))
    manually_deleted = replace(initial, text="Reviewed and kept another note.")
    assert structured.native_update((corrected,), "activity_summary", manually_deleted) == manually_deleted


def test_dated_multi_event_txt_still_uses_each_header_and_not_one_global_date():
    body = ("2026-09-04 | WO-01 | Vendor service\n"
            "Inspected fan motor. Replacement remains pending.\n"
            "2026-09-18 | WO-02 | Vendor service\n"
            "Calibrated controller. Further follow-up recommended.\n")
    source = ReportSource("a" * 64, "vendor-evidence.txt", "a" * 64, ".txt",
                          vendor="Trane", service_date="2026-09-04",
                          page_texts=(body,))
    result = structured.native_update((SourceContent(source),), "activity_summary")
    assert "2026-09-04 · Trane — Inspected fan motor" in result.text
    assert "2026-09-18 · Trane — Calibrated controller" in result.text


def test_completed_date_is_metadata_but_completed_work_still_prints():
    source = ReportSource("a" * 64, "synthetic.docx", "a" * 64, ".docx",
                          service_date="2026-09-12",
                          page_texts=("Service date: 2026-09-12",
                                      "Completed date: 09/12/2026",
                                      "Completed synthetic pump inspection.",
                                      "Completed valve repair on 2026-09-12."))
    result = structured.native_update((SourceContent(source),), "activity_summary")
    assert "Completed date:" not in result.text
    assert "Service date:" not in result.text
    assert "2026-09-12 — Completed synthetic pump inspection." in result.text
    assert "Completed valve repair on 2026-09-12." in result.text
    assert len(result.references) == 2
