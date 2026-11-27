"""Review F15: a supporting file's own title decides its type.

Synthetic text only. A vendor service report that mentions a quote in its
body stays a service report, so its completed work still reaches Activity.
"""
import pytest

from app.monthly_report_model import Facility, ReportProfile, ReportSource
from app.monthly_report_pre_model_routing import title_source_type
from app.monthly_report_sources import suggest_facts

PROFILE = ReportProfile("Synthetic contract", "synthetic", "North Site",
                        (Facility("north", "North Site", ("NS",)),))


def _facts(*lines):
    return suggest_facts(ReportSource("a" * 64, "upload.txt", "b" * 64, ".txt",
                                      page_texts=("\n".join(lines),)), PROFILE)


def test_service_report_that_mentions_a_quote_stays_a_service_report():
    facts = _facts("Service Report", "Vendor: Synthetic Mechanical", "Site: NS",
                   "Service date: 11/04/2026", "Replaced the pump seal.",
                   "Recommend a new fan belt. Quote amount: $1,240.00")
    assert facts.classification == "Vendor service"
    assert facts.confidence == "medium"


def test_quotation_that_mentions_a_service_visit_stays_a_quote():
    facts = _facts("Quotation", "Vendor: Synthetic Motors", "Scope: rewind blower motor found on a service visit",
                   "Quote amount: $6,875.00")
    assert facts.classification == "Proposal / quote"


@pytest.mark.parametrize("lines,expected", [
    (("Water Treatment Report", "Delivered 5 gallons; quote attached"), "Water treatment"),
    (("Quote amount: $500", "Service visit notes"), "Vendor service"),
    (("Service Report", "Quotation"), ""),
    (("Notes from the week", "nothing titled"), ""),
])
def test_title_type_reads_only_anchored_titles(lines, expected):
    assert title_source_type("\n".join(lines))[0] == expected


def test_untitled_mixed_file_still_needs_a_person_to_choose():
    facts = _facts("Notes", "The service visit found a leak.", "A quote will follow.")
    assert facts.classification == "Reference only"


def test_a_title_naming_two_types_still_needs_a_person_to_choose():
    assert _facts("Utility analysis and maintenance report.").classification == "Reference only"
