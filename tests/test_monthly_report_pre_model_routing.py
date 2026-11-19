"""Synthetic A53 pre-model routing controls (no paid service or client files)."""
from dataclasses import asdict, replace
from hashlib import sha256

import pytest

from app.monthly_report_model import ReportPeriod, ReportSource, ResolvedBlock, synthetic_profiles
from app.monthly_report_sources import SourceContent, SourceTable
from app import monthly_report_structured_uploads as structured
from app.monthly_report_pre_model_routing import classify_page, choose_reader_pages


PROFILE = synthetic_profiles()[0]
SITE = PROFILE.facilities[0].title
PERIOD = ReportPeriod(2026, 9)


def file(name, pages, classification="Vendor service", facility=SITE, service_date="2026-09-12", tables=()):
    raw = "\n".join(pages).encode()
    digest = sha256(raw).hexdigest()
    source = ReportSource(id=digest, sha256=digest, filename=name,
                          suffix=".csv" if tables else ".txt", classification=classification,
                          facility=facility, service_date=service_date,
                          page_texts=tuple(pages), selected_pages=tuple(range(1, len(pages) + 1)))
    return SourceContent(source, tuple(tables))


def text_payload(payloads):
    return "\n".join(block.get("text", "") for payload in payloads for block in payload
                     if block.get("type") == "text")


def test_vendor_and_quote_pages_are_independent_and_only_vendor_reaches_activity_reader():
    content = file("mixed.txt", (
        "Vendor service report\nTrane inspected pump P-1; recommended replacement next month.",
        "Proposal / quotation\nQuoted replacement of pump P-1 for $24,000."
    ))
    before = asdict(content)
    first, second = (classify_page(content, n) for n in (1, 2))
    assert first.destinations == ("activity_summary",) and first.page == 1
    assert second.destinations == ("proposals",) and second.page == 2
    assert first.rule and second.rule
    assert choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD) == ((content.source.id, 1),)
    payload = structured.reader_batches(PROFILE, (content,), "activity_summary", period=PERIOD)
    assert "SOURCE " + content.source.id + " PAGE 1" in text_payload(payload)
    assert "SOURCE " + content.source.id + " PAGE 2" not in text_payload(payload)
    assert asdict(content) == before


def test_mbcx_water_utility_work_order_training_and_capital_proposals_do_not_cross_routes():
    pages = ("MBCx Report\nSystem performance tests",
             "Water Treatment Report\nConductivity measured",
             "Utility scorecard\nEnergy kWh",
             "Work Order Summary\nWO #, Finish Date, Status",
             "Training attendance\nSafety briefing",
             "Capital renewal\nReplace aged chiller",
             "Proposal scope\nReplace aged chiller",
             "Vendor service report\nInspected pump")
    content = file("mixed.txt", pages)
    assert [classify_page(content, n).destinations for n in range(1, 9)] == [
        ("mbcx_report",), ("water_reports",), ("utility_analysis",),
        ("work_orders",), ("training",), ("capital_renewal",),
        ("proposals",), ("activity_summary",)]
    assert choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD) == ((content.source.id, 8),)
    assert choose_reader_pages(PROFILE, (content,), "proposals", period=PERIOD) == ((content.source.id, 7),)
    assert choose_reader_pages(PROFILE, (content,), "capital_renewal", period=PERIOD) == ((content.source.id, 6),)


def test_same_page_mixed_headings_are_candidates_until_one_explicit_correction():
    content = file("mixed.txt", ("Vendor service report\nProposal quotation\nInspected pump; quoted repair.",))
    result = classify_page(content, 1)
    assert result.destinations == ("activity_summary", "proposals")
    assert result.ambiguous
    assert choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD) == ()
    receipt = {(content.source.id, 1, content.source.sha256): "activity_summary"}
    assert choose_reader_pages(PROFILE, (content,), "activity_summary",
                               period=PERIOD, corrections=receipt) == ((content.source.id, 1),)
    with pytest.raises(ValueError, match="not a candidate"):
        choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD,
                            corrections={(content.source.id, 1, content.source.sha256): "water_reports"})


def test_wrong_site_month_and_unreadable_unknown_never_gain_false_placement():
    content = file("mixed.txt", ("Vendor service report\nSite: Other Hospital\nInspected pump.",))
    assert choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD) == ()
    foreign = file("foreign.txt", ("Vendor service report\nInspected pump.",),
                   facility="Outside contract hospital")
    assert choose_reader_pages(PROFILE, (foreign,), "activity_summary", period=PERIOD) == ()
    stale = replace(content, source=replace(content.source, page_texts=("Vendor service report\nInspected pump.",),
                                             service_date="2026-08-03"))
    assert choose_reader_pages(PROFILE, (stale,), "activity_summary", period=PERIOD) == ()
    unknown = file("scan.txt", ("",), classification="Reference only")
    assert not classify_page(unknown, 1).destinations


def test_native_mapped_proposal_table_avoids_paid_request_and_keeps_rows():
    table = SourceTable("Proposals", ("Facility", "Vendor", "Scope", "Status"),
                        ((SITE, "Example Vendor", "Inspect boiler", "Pending"),))
    content = file("proposals.csv", ("Facility\tVendor\tScope\tStatus\n" + "\t".join(table.rows[0]),),
                   classification="Proposal / quote", tables=(table,))
    native = structured.native_update((content,), "proposals")
    assert native.rows and native.rows[0][2] == "Inspect boiler"
    assert structured.reader_batches(PROFILE, (content,), "proposals", period=PERIOD) == ()
    assert content.tables[0].rows[0][3] == "Pending"


def test_accepted_pages_skipped_without_dropping_unaccepted_sibling():
    content = file("two.txt", ("Vendor service report\nInspected AHU A.", "Vendor service report\nInspected AHU B."))
    assert choose_reader_pages(PROFILE, (content,), "activity_summary", period=PERIOD,
                               accepted_pages={(content.source.id, 1)}) == ((content.source.id, 2),)
    assert structured.reader_batches(PROFILE, (content,), "activity_summary",
                                     period=PERIOD, accepted_pages={(content.source.id, 1)})


def test_missing_malformed_and_duplicate_inputs_are_conservative():
    assert choose_reader_pages(PROFILE, (), "activity_summary", period=PERIOD) == ()
    content = file("safe.txt", ("Vendor service report\nInspected equipment.",))
    assert choose_reader_pages(PROFILE, (content, content), "activity_summary", period=PERIOD) == ((content.source.id, 1),)
    damaged = replace(content, source=replace(content.source, page_texts=("Different bytes",)))
    with pytest.raises(ValueError, match="Conflicting"):
        choose_reader_pages(PROFILE, (content, damaged), "activity_summary", period=PERIOD)
    with pytest.raises(ValueError, match="Unknown reader destination"):
        choose_reader_pages(PROFILE, (content,), "vendor_reports", period=PERIOD)


def test_cached_mixed_reader_result_cannot_append_wrong_section_sibling():
    content = file("mixed.txt", (
        "Vendor service report\\nInspected pump P-7.",
        "Water treatment report\\nConductivity measured at tower.",
        "MBCx report\\nControl sequence monitored.",
        "Proposal quotation\\nReplacement recommended."
    ))
    before = asdict(content)
    answer = {"items": [
        {"source": content.source.id, "page": 1, "text": "Inspected pump P-7.", "row": []},
        {"source": content.source.id, "page": 2, "text": "Conductivity measured at tower.", "row": []},
        {"source": content.source.id, "page": 3, "text": "Control sequence monitored.", "row": []},
        {"source": content.source.id, "page": 4, "text": "Replacement recommended.", "row": []},
    ]}
    result, pages = structured.reader_update((content,), "activity_summary", answer)
    assert "Inspected pump P-7." in result.text
    for text in ("Conductivity measured", "Control sequence", "Replacement recommended"):
        assert text not in result.text
    assert result.references == (structured.sources.source_reference(content.source, 1),)
    assert not pages
    assert asdict(content) == before
