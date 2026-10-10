"""Fresh technical vendor documents are reviewed and printed in Activity."""
from dataclasses import replace

from app import monthly_report_sources as sources
from app.monthly_report_content_policy import page_fingerprint, page_allowed
from app.monthly_report_model import default_sections, ResolvedBlock, synthetic_profiles
from app.monthly_report_section_uploads import (CLASSIFICATION_DESTINATIONS,
    prepare_section_pages, source_destinations, section_contents)
from test_monthly_report_sources import pdf_bytes


def test_vendor_technical_page_is_new_activity_output_not_onsite_call(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-trane.pdf", pdf_bytes(1))
    reviewed = replace(content.source, classification="Vendor service")
    reviewed = replace(reviewed, client_page_reviews=((1, page_fingerprint(reviewed, 1)),))
    assert page_allowed(reviewed, 1)
    content = replace(content, source=reviewed)
    assert CLASSIFICATION_DESTINATIONS["Vendor service"] == "improvements"
    assert source_destinations((content,), {}, {})[reviewed.id] == {"improvements"}
    added = prepare_section_pages(profile, (content,), "improvements", {})
    assert "improvements" in added and "vendor_reports" not in added
    assert len(added["improvements"].asset_hashes) == 1
    assert added["improvements"].references == (sources.source_reference(reviewed, 1),)
    assert "improvements" in [b.key for s in default_sections() if s.key == "activity" for b in s.blocks]
    assert "service_calls" in [b.key for s in default_sections() if s.key == "maintenance" for b in s.blocks]


def test_legacy_vendor_pages_are_not_moved_or_cloned_automatically(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    content, _ = sources.ingest(profile, "synthetic-vendor.pdf", pdf_bytes(1))
    reviewed = replace(content.source, classification="Vendor service")
    reviewed = replace(reviewed, client_page_reviews=((1, page_fingerprint(reviewed, 1)),))
    content = replace(content, source=reviewed)
    legacy, = sources.prepare_pages(profile, (content,), ((reviewed.id, "vendor_reports"),))
    owners = source_destinations((content,), {}, {"vendor_reports": legacy})
    assert owners[reviewed.id] == {"vendor_reports"}
    assert section_contents((content,), "improvements", {}, {"vendor_reports": legacy}) == ()
    assert section_contents((content,), "vendor_reports", {}, {"vendor_reports": legacy}) == (content,)


def test_priced_vendor_pages_still_require_exclusion(monkeypatch, tmp_path):
    import fitz
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50,50), "Trane inspected a pump. Invoice amount $12,345.67.")
        content, _ = sources.ingest(profile, "synthetic-priced-vendor.pdf", pdf.tobytes())
    priced = replace(content.source, classification="Vendor service",
                     selected_pages=(1,),
                     client_page_reviews=((1, page_fingerprint(content.source, 1)),))
    content = replace(content, source=priced)
    assert not page_allowed(priced, 1)
    try:
        prepare_section_pages(profile, (content,), "improvements", {})
    except ValueError:
        pass
    else:
        raise AssertionError("A priced original vendor page was accepted")
