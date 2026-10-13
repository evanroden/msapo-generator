"""Grounded native Activity identity; no invented dates, sites, completion or price."""
from dataclasses import replace
from io import BytesIO

from docx import Document

from app import monthly_report_sources as sources
from app import monthly_report_structured_uploads as structured
from app.monthly_report_model import ReportSource, ResolvedBlock, synthetic_profiles
from app.monthly_report_sources import SourceContent


def sample(text, *, suffix=".txt", vendor="", when="", identity="a"):
    digest = identity * 64
    report = ReportSource(digest, "vendor-evidence" + suffix, digest, suffix,
                          page_texts=(text,), vendor=vendor, service_date=when)
    return SourceContent(report)


def test_dated_txt_events_keep_each_actual_date_vendor_and_status():
    body = (
        "2026-09-04 | WO-1 | Vendor service\n"
        "Inspected air handler. Replacement was recommended, not completed.\n"
        "2026-09-09 | TRAIN-1 | Training Summary\n"
        "Completed a synthetic course.\n"
        "2026-09-20 | WO-2 | Vendor service\n"
        "Tightened a drive belt. Follow-up is pending.\n"
    )
    content = sample(body, vendor="Trane")
    result = structured.native_update((content,), "activity_summary")
    assert "2026-09-04 · Trane — Inspected air handler" in result.text
    assert "2026-09-20 · Trane — Tightened a drive belt" in result.text
    assert "Replacement was recommended, not completed." in result.text
    assert "Follow-up is pending." in result.text
    assert "Completed a synthetic course" not in result.text
    assert result.references == (sources.source_reference(content.source, 1),)
    assert structured.native_update((content,), "activity_summary", result) == result


def test_docx_source_labeled_vendor_and_date_survive_native_ingestion(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    doc = Document()
    doc.add_paragraph("Vendor: Trane")
    doc.add_paragraph("Service date: 2026-09-12")
    doc.add_paragraph("Inspected fan motor. Repair remains pending.")
    original = BytesIO()
    doc.save(original)
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "vendor-report.docx", original.getvalue())
    assert content.source.vendor == "Trane"
    assert content.source.service_date == "2026-09-12"
    result = structured.native_update((content,), "activity_summary")
    assert "2026-09-12 · Trane — Inspected fan motor." in result.text
    assert "Repair remains pending." in result.text
    assert sources.source_bytes(profile, content.source) == original.getvalue()


def test_invalid_header_date_stays_unknown_even_if_source_has_another_date():
    body = "2026-99-99 | WO-1 | Vendor service\nInspected a synthetic motor.\n"
    content = sample(body, vendor="Trane", when="2026-09-15")
    result = structured.native_update((content,), "activity_summary")
    assert "Trane — Inspected a synthetic motor." in result.text
    assert "2026-99-99" not in result.text
    assert "2026-09-15" not in result.text


def test_metadata_correction_never_restores_edited_or_deleted_source_text():
    content = sample("Inspected AHU-7 and recorded belt wear.",
                     vendor="Trane", when="2026-09-10")
    initial = structured.native_update((content,), "activity_summary")
    assert "2026-09-10 · Trane — Inspected AHU-7" in initial.text
    corrected = replace(content, source=replace(content.source,
                                                service_date="2026-09-12", facility="demo"))
    assert corrected.source.fingerprint != content.source.fingerprint
    manually_edited = replace(initial, text="Operator's deliberately edited wording.")
    assert structured.native_update((corrected,), "activity_summary", manually_edited) == manually_edited
    cleared = replace(initial, text="")
    assert structured.native_update((corrected,), "activity_summary", cleared) == cleared


def test_changed_bytes_under_same_filename_are_a_distinct_source():
    old = sample("Inspected AHU-7.", identity="a")
    latest = sample("Replaced drive belts on AHU-7.", identity="b",
                    vendor="Trane", when="2026-09-20")
    first = structured.native_update((old,), "activity_summary")
    next_block = structured.native_update((latest,), "activity_summary", first)
    assert "Inspected AHU-7." in next_block.text
    assert "2026-09-20 · Trane — Replaced drive belts" in next_block.text
    assert len(next_block.references) == 2


def test_unknown_vendor_date_remain_uninvented_and_price_bearing_vendor_is_excluded():
    plain = sample("Inspected the pump on site.", vendor="", when="")
    assert structured.native_update((plain,), "activity_summary").text == "Inspected the pump on site."
    priced = sample("Inspected the pump on site.", vendor="Vendor fee $150",
                    when="2026-09-18")
    text = structured.native_update((priced,), "activity_summary").text
    assert text == "2026-09-18 — Inspected the pump on site."
    assert "$150" not in text
