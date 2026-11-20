"""A47 synthetic regression: printed vendor dates, status and page ownership.

No real client, technician, site or financial records are used here.
Refs #270 #277 #791.
"""
from dataclasses import replace
from hashlib import sha256

import pymupdf as fitz

from app import monthly_report_sources as sources
from app.monthly_report_model import ReportSource, synthetic_profiles
from app.monthly_report_sources import SourceContent
from app.monthly_report_structured_uploads import (
    native_update, reader_notices, reader_sources, reader_update,
)


def vendor_source(*pages, vendor="Synthetic Trane", when="2026-09-10", facility=""):
    raw = "\\f".join(pages).encode()
    digest = sha256(raw).hexdigest()
    source = ReportSource(
        digest, "synthetic-vendor.pdf", digest, ".pdf",
        classification="Vendor service", page_texts=pages,
        selected_pages=tuple(range(1, len(pages) + 1)),
        vendor=vendor, service_date=when, facility=facility,
    )
    return SourceContent(source)


def test_valid_vendor_control_keeps_its_single_page_identity_and_no_duplicates():
    content = vendor_source(
        "Vendor service report\n"
        "Service date: 2026-09-10\n"
        "Inspected synthetic fan EF-42 and found a worn drive belt."
    )
    first = native_update((content,), "activity_summary")
    assert first.text == (
        "2026-09-10 · Synthetic Trane — "
        "Inspected synthetic fan EF-42 and found a worn drive belt."
    )
    assert first.references == (sources.source_reference(content.source, 1),)
    assert native_update((content,), "activity_summary", first) == first
    later, _ = reader_update((content,), "activity_summary", {
        "items": [{"source": content.source.id, "page": 1,
                   "text": "Inspected synthetic fan EF-42 and found a worn drive belt.",
                   "row": [], "include_page": False}],
    }, first)
    assert later == first


def test_wrapped_failed_service_with_separate_status_requires_source_review():
    content = vendor_source(
        "Vendor service report\n"
        "Replaced synthetic actuator SV-18 but the unit\n"
        "would not start.\n"
        "Status: Not completed."
    )
    assert native_update((content,), "activity_summary").text == ""
    assert not reader_sources((content,), "activity_summary")
    assert "status" in " ".join(reader_notices((content,), "activity_summary")).lower()
    assert "would not start." in content.source.page_texts[0]
    assert "Status: Not completed." in content.source.page_texts[0]


def test_planned_visit_with_impossible_date_is_not_certified_or_silently_normalized():
    content = vendor_source(
        "Vendor service report\n"
        "Follow-up visit planned for 2026-02-30; repair remains pending.",
        when="",
    )
    assert not native_update((content,), "activity_summary").text
    assert not reader_sources((content,), "activity_summary")
    assert "date" in " ".join(reader_notices((content,), "activity_summary")).lower()
    assert "2026-02-30" in content.source.page_texts[0]


def test_each_page_keeps_its_own_literal_date_and_vendor_without_bleed():
    content = vendor_source(
        "Vendor service report\nVendor: Synthetic Trane\n"
        "Service date: 09/10/2026\n"
        "Inspected synthetic fan EF-42 and noted belt wear.",
        "Vendor service report\nService date: 2026-09-15\n"
        "Repaired synthetic valve SV-18 and observed no leakage.",
    )
    native = native_update((content,), "activity_summary")
    parts = native.text.split("\n\n")
    assert parts == [
        "09/10/2026 · Synthetic Trane — Inspected synthetic fan EF-42 and noted belt wear.",
        "2026-09-15 — Repaired synthetic valve SV-18 and observed no leakage.",
    ]
    assert native.references == tuple(
        sources.source_reference(content.source, n) for n in (1, 2)
    )
    assert native_update((content,), "activity_summary", native) == native


def test_conflicting_site_page_headers_force_explicit_mapping_not_activity_or_reader():
    content = vendor_source(
        "Vendor service report\nSite: Demo North\n"
        "Inspected synthetic pump on the north site.",
        "Vendor service report\nSite: Demo South\n"
        "Replaced synthetic controller on the south site.",
        facility="",
    )
    block = native_update((content,), "activity_summary")
    assert not block.text and not block.references
    assert not reader_sources((content,), "activity_summary")
    assert "site" in " ".join(reader_notices((content,), "activity_summary")).lower()
    assert "Demo South" in content.source.page_texts[1]


def test_synthetic_pdf_origins_and_original_bytes_survive_page_review(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    pdf = fitz.open()
    for printed_date, statement in (
        ("09/10/2026", "Inspected synthetic fan EF-42 and noted belt wear."),
        ("2026-09-15", "Repaired synthetic valve SV-18 and observed no leakage."),
    ):
        page = pdf.new_page()
        for n, line in enumerate((
            "Vendor service report", "Service date: " + printed_date, statement
        )):
            page.insert_text((40, 45 + 18*n), line, fontsize=10)
    original = pdf.tobytes()
    pdf.close()
    content, _ = sources.ingest(profile, "synthetic-page-ownership.pdf", original)
    assert sources.source_bytes(profile, content.source) == original
    block = native_update((content,), "activity_summary")
    assert "09/10/2026" in block.text
    assert "2026-09-15" in block.text
    assert block.references == tuple(
        sources.source_reference(content.source, n) for n in (1, 2)
    )
    assert native_update((content,), "activity_summary", block) == block


def test_empty_source_has_no_vendor_activity():
    assert not native_update((), "activity_summary").text
    assert not reader_notices((), "activity_summary")


def test_single_page_human_corrected_vendor_date_takes_precedence_over_guess():
    content = vendor_source(
        "Vendor service report\n"
        "Vendor: Synthetic Original\n"
        "Service date: 09/10/2026\n"
        "Inspected synthetic fan EF-42 and noted belt wear.",
        vendor="Reviewed Vendor", when="2026-10-09",
    )
    native = native_update((content,), "activity_summary")
    assert native.text == (
        "2026-10-09 · Reviewed Vendor — "
        "Inspected synthetic fan EF-42 and noted belt wear."
    )
    manually_edited = replace(native, text="Operator's accepted source-linked wording.")
    assert native_update((content,), "activity_summary", manually_edited) == manually_edited
    removed = replace(native, text="")
    assert native_update((content,), "activity_summary", removed) == removed


def test_date_shaped_asset_identifier_is_not_an_impossible_visit_date():
    content = vendor_source(
        "Vendor service report\n"
        "Asset: ID-2026-02-30-X\n"
        "Inspected synthetic fan EF-42 and noted belt wear."
    )
    result = native_update((content,), "activity_summary")
    assert "Inspected synthetic fan EF-42" in result.text
    assert not reader_notices((content,), "activity_summary")


def test_unsafe_vendor_and_safe_sibling_sources_are_isolated():
    blocked = vendor_source(
        "Vendor service report\n"
        "Replaced synthetic actuator SV-18.\n"
        "Status: Not completed."
    )
    good = vendor_source(
        "Vendor service report\n"
        "Inspected synthetic fan EF-42 and noted belt wear."
    )
    expected = native_update((good,), "activity_summary")
    combined = native_update((blocked, good), "activity_summary")
    assert combined == expected
    assert reader_sources((blocked, good), "activity_summary") == (good,)
    assert len(reader_notices((blocked, good), "activity_summary")) == 1
