"""Synthetic source table mapping must never use a monetary column as description."""
import pytest

from app.monthly_report_content_policy import contains_price, price_column, ambiguous_price_columns
from app.monthly_report_model import ReportSource
from app.monthly_report_sources import SourceContent, SourceTable
from app.monthly_report_structured_uploads import mapped_rows, reader_update


def _content(columns, rows):
    report_source = ReportSource("a" * 64, "synthetic.csv", "a" * 64, ".csv",
                                 page_texts=("\n".join(("\t".join(columns), *("\t".join(row) for row in rows))),))
    return SourceContent(report_source, (SourceTable("Synthetic table", columns, rows),))


@pytest.mark.parametrize("heading", (
    "Project Budget", "Proposal Amount", "Proposal Total", "Budget",
    "Fee", "Quote Amount", "Quoted Amount", "Invoice Amount",
))
def test_price_headings_never_behave_as_project_or_proposal_descriptions(heading):
    assert price_column(heading), heading
    assert contains_price(heading + "\n48,500.00")


def test_exact_recommendation_beats_earlier_ambiguous_project_alias():
    source = _content(("Facility", "Priority", "Project Budget", "Recommendation"),
                      (("Synthetic North", "1", "250,000", "Inspect a pump at 45 gpm"),))
    assert mapped_rows(source, "capital_renewal") == (
        ("Synthetic North", "1", "Inspect a pump at 45 gpm"),)


def test_proposal_amount_and_total_do_not_reach_scope_or_status():
    first = _content(("Vendor", "Proposal Amount", "Scope of Work", "Status"),
                     (("Synthetic Vendor", "48,500.00", "Repair a valve", "Pending"),))
    second = _content(("Proposal Total", "Vendor", "Work Description", "Status"),
                      (("12,400", "Synthetic Supplier", "Inspect electrical controls", "Open"),))
    assert mapped_rows(first, "proposals") == (
        ("", "Synthetic Vendor", "Repair a valve", "Pending"),)
    assert mapped_rows(second, "proposals") == (
        ("", "Synthetic Supplier", "Inspect electrical controls", "Open"),)


def test_multiple_descriptions_prefer_specific_scope_of_work_not_general_proposal_alias():
    source = _content(("Proposal Reference", "Work Description", "Status", "Facility"),
                      (("Q-TEST-731", "Replace motor with 2 hp equipment", "Pending", "Synthetic South"),))
    assert mapped_rows(source, "proposals") == (
        ("Synthetic South", "", "Replace motor with 2 hp equipment", "Pending"),)


def test_mixed_price_and_scope_heading_stays_ambiguous_without_deleting_other_rows():
    assert ambiguous_price_columns(("Budget / Recommendation",), (("250,000",),)) == (0,)
    source = _content(("Vendor", "Budget / Recommendation", "Scope of Work", "Status"),
                      (("Synthetic Vendor", "250,000", "Replace fan", "Pending"),))
    assert mapped_rows(source, "proposals") == (
        ("", "Synthetic Vendor", "Replace fan", "Pending"),)


def test_price_only_description_rejected_but_technical_counts_and_identifiers_remain():
    source = _content(("Vendor", "Scope of Work", "Status"),
                      (("Synthetic Vendor", "12,400", "Pending"),
                       ("Synthetic Vendor", "Inspect VAV-TEST-03 at 1.20 psi", "Open"),
                       ("Synthetic Vendor", "Q-TEST-731 confirmed, inspect VAV", "Open")))
    assert mapped_rows(source, "proposals") == (
        ("", "Synthetic Vendor", "Inspect VAV-TEST-03 at 1.20 psi", "Open"),
        ("", "Synthetic Vendor", "Q-TEST-731 confirmed, inspect VAV", "Open"))


def test_reader_drops_bare_money_in_scope_but_retains_legitimate_reference():
    source = _content(("Vendor", "Scope", "Status"), (("Synthetic Vendor", "Q-TEST-731", "Pending"),))
    id = source.source.id
    results, pages = reader_update((source,), "proposals", {
        "visual_pages": [[id, 1]],
        "items": [
            {"source": id, "page": 1, "row": ["", "Synthetic Vendor", "12,400", "Pending"]},
            {"source": id, "page": 1, "row": ["", "Synthetic Vendor", "Q-TEST-731", "Pending"]},
        ]})
    # Source text is explicitly synthetic and native; the rows contain no prices.
    assert results.rows == (("", "Synthetic Vendor", "Q-TEST-731", "Pending"),)
    assert not pages


def test_unpriced_budget_discussion_is_not_a_numeric_leak():
    assert not contains_price("Budget planning is under review; no figures are approved.")
    assert not price_column("Work Description")
