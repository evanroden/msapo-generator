"""Annual work-order site checks require one real facility, not union membership."""
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
from docx import Document

from app.monthly_report_annual_work_order_grid import (
    annual_grid_candidate, annual_grid_matches_profile, annual_site_month_table,
)
from app.monthly_report_import import inspect_docx
from app.monthly_report_model import Facility, ReportPeriod, ReportProfile, ReportTable
from app.monthly_report_start_import import analyze_starting_report, automatic_section_plans


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
HEAD = ("Category", "Site", "Metric", "Unit", *MONTHS)
PERIOD = ReportPeriod(2026, 9)
NUMBERS = ("0", "", "2", "0", "", "6", "", "8", "9", "", "", "")


def profile(reverse=False):
    first = Facility("north", "West Plant", ("West Facility",))
    second = Facility("east", "North", ("Eastern Campus",))
    return ReportProfile("Synthetic independent work-order contract", "grid-collision",
                         "Synthetic facility set", (second, first) if reverse else (first, second),
                         scope_type="multi_site")


def table(*sites):
    return ReportTable(HEAD, tuple(("Work Order Status", site, "Received", "count", *NUMBERS)
                                   for site in sites))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("label", ["North", " north ", "NORTH", " North  ", "nOrTh"])
def test_key_title_collision_never_proves_annual_site_scope(reverse, label):
    p = profile(reverse)
    original = table(label, "West Plant")
    assert not annual_grid_matches_profile(original, p)
    assert original.rows[0][1] == label
    assert original.rows[0][4:] == NUMBERS


@pytest.mark.parametrize("label", ["east", " EAST ", "Eastern Campus", " West Plant ", "West Facility"])
def test_unique_key_title_or_alias_is_accepted(label):
    assert annual_grid_matches_profile(table(label), profile())


def test_multiple_rows_must_each_have_one_unambiguous_owner():
    p = profile()
    assert annual_grid_matches_profile(table("West Plant", "east"), p)
    assert not annual_grid_matches_profile(table("West Plant", "North"), p)
    assert not annual_grid_matches_profile(table("West Plant", "Unrelated Site"), p)
    assert not annual_grid_matches_profile(table("West Plant", ""), p)
    assert not annual_grid_matches_profile(table(), p)


def test_repeated_labels_within_same_facility_are_not_a_collision():
    p = profile()
    first, second = p.facilities
    changed = replace(first, aliases=(*first.aliases, "West Plant", "west plant", "north"))
    revised = replace(p, facilities=(changed, second))
    assert annual_grid_matches_profile(table("West Plant", "east"), revised)
    assert not annual_grid_matches_profile(table("North"), revised)


def test_shared_aliases_are_ambiguous_even_when_each_site_is_in_the_profile():
    p = profile()
    first, second = p.facilities
    p = replace(p, facilities=(
        replace(first, aliases=(*first.aliases, "Shared Machinery")),
        replace(second, aliases=(*second.aliases, "shared machinery")),
    ))
    assert not annual_grid_matches_profile(table("Shared Machinery", "West Plant"), p)
    assert annual_grid_matches_profile(table("West Plant", "Eastern Campus"), p)


def test_blank_and_nonstring_aliases_never_establish_membership():
    p = profile()
    first, second = p.facilities
    p = replace(p, facilities=(replace(first, aliases=("", "  ", None, 42)), second))
    assert not annual_grid_matches_profile(table("42"), p)
    assert not annual_grid_matches_profile(table("none"), p)
    assert annual_grid_matches_profile(table("West Plant", "east"), p)


@dataclass(frozen=True)
class ImportedTable:
    rows: tuple
    kind: str = "table"
    section: str = "activity"
    merged_title_rows: frozenset = frozenset({1})


def grouped_item():
    return ImportedTable((
        ("Site", "Metric", "Unit", *MONTHS),
        ("Work Order Status", *("",) * 14),
        ("North", "Received", "count", *NUMBERS),
        ("West Plant", "Received", "count", *NUMBERS),
    ))


def test_original_month_cells_remain_reviewable_when_site_identity_collides():
    item = grouped_item()
    assert annual_grid_candidate(item)
    annual = annual_site_month_table(item)
    assert annual is not None
    assert annual.rows[0][1] == "North"
    assert annual.rows[0][4:] == NUMBERS
    assert annual.rows[1][1] == "West Plant"
    assert not annual_grid_matches_profile(annual, profile())
    # No import or site correction is synthesized by this admission check.
    assert item.rows[2][0] == "North"
    assert item.rows[2][3:] == NUMBERS


def test_real_word_source_goes_to_existing_review_instead_of_auto_approval(tmp_path):
    p = profile()
    document = Document()
    document.add_heading(p.title, 0)
    document.add_paragraph("Monthly Report · September 2026")
    document.add_heading("2 Monthly Activity Summary", 1)
    grid = document.add_table(rows=4, cols=15)
    for index, cells in enumerate(grouped_item().rows):
        if index == 1:
            grid.rows[index].cells[0].merge(grid.rows[index].cells[-1]).text = cells[0]
        else:
            for cell, value in zip(grid.rows[index].cells, cells):
                cell.text = value
    path = tmp_path / "synthetic-ambiguous-annual-grid.docx"
    document.save(path)
    original = path.read_bytes()
    inspection = inspect_docx(path)
    item = next(item for item in inspection.items
                if item.kind == "table"
                and any("Received" in cell for row in item.rows for cell in row))
    annual = annual_site_month_table(item)
    assert annual is not None and annual.rows[0][1] == "North"
    analysis = analyze_starting_report(inspection, p, PERIOD, confirmed_sites=p.facilities)
    plans = automatic_section_plans(inspection, analysis, profile=p, period=PERIOD)
    assert not plans["activity"]["approved"]
    assert any("annual work-order grid's sites" in question
               for question in plans["activity"]["questions"])
    assert item.id not in plans["activity"]["selected"]
    assert path.read_bytes() == original
