"""Synthetic flattened Word headings must not erase equipment recommendations."""

from dataclasses import asdict, replace

from app.monthly_report_checks import preflight
from app.monthly_report_content_policy import (
    ambiguous_price_columns, price_column, price_free_table,
    table_has_pricing, table_price_columns,
)
from app.monthly_report_import import ImportItem
from app.monthly_report_model import (
    BlockSpec, ColumnSpec, ReportPeriod, ReportTable, ResolvedBlock, SectionSpec,
    synthetic_draft, synthetic_profiles,
)
from app.monthly_report_sections import table_without_prices


MIXED = ("Equipment description Replacement timing Cost Condition", "", "", "")
VALUES = (("Synthetic pump", "Unknown", "950", "Casing worn"),)


def test_import_retains_every_cell_when_price_header_is_flattened():
    item = ImportItem("synthetic-table", "table", "word/document.xml", 1, 1,
                      "capital", "capital_renewal", rows=(MIXED, *VALUES))
    before = asdict(item)
    table, removed = table_without_prices(item)
    assert removed == ()
    assert table.rows == VALUES
    assert ambiguous_price_columns(table.columns, table.rows) == (0,)
    assert table_has_pricing(table.columns, table.rows)
    assert asdict(item) == before


def test_saved_table_currency_annotation_cannot_override_mixed_heading():
    spec = BlockSpec("capital_renewal", "table", columns=tuple(
        ColumnSpec(f"column_{n}", title, "currency" if n == 0 else "text")
        for n, title in enumerate(MIXED)
    ))
    block = ResolvedBlock("capital_renewal", "Last month", rows=VALUES,
                          extra_tables=(ReportTable(MIXED, VALUES),))
    before = asdict(block)
    updated_spec, updated, removed = price_free_table(spec, block)
    assert removed == () and updated.rows == VALUES
    assert updated.extra_tables[0].rows == VALUES
    assert len(updated_spec.columns) == 4
    assert asdict(block) == before
    assert not price_column(MIXED[0], "currency")


def test_populated_ambiguous_table_is_blocked_until_headers_are_corrected():
    spec = BlockSpec("capital_renewal", "table", columns=tuple(
        ColumnSpec(f"column_{n}", title) for n, title in enumerate(MIXED)
    ))
    block = ResolvedBlock("capital_renewal", "Last month", rows=VALUES)
    draft = replace(
        synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)),
        sections=(SectionSpec("capital", "9", "Priority Capital Renewal List", (spec,)),),
        blocks=(block,),
    )
    assert any(check.blocking and check.code == "pricing" for check in preflight(draft))
    confirmed = replace(spec, columns=(
        ColumnSpec("asset", "Equipment description"),
        ColumnSpec("timing", "Replacement timing"),
        ColumnSpec("cost", "Cost", "currency"),
        ColumnSpec("condition", "Condition"),
    ))
    clean_spec, clean_block, removed = price_free_table(confirmed, block)
    assert removed == ("Cost",)
    assert clean_block.rows == (("Synthetic pump", "Unknown", "Casing worn"),)
    clean = replace(draft, sections=(replace(draft.sections[0], blocks=(clean_spec,)),), blocks=(clean_block,))
    assert not any(check.code == "pricing" for check in preflight(clean))


def test_unpopulated_mixed_schema_is_preserved_without_claiming_it_contains_prices():
    assert ambiguous_price_columns(MIXED) == (0,)
    assert table_price_columns(MIXED, ()) == ()
    assert not table_has_pricing(MIXED, ())
    assert not table_has_pricing(MIXED, (("", "", "", ""),))


def test_clear_price_columns_and_split_headers_are_still_removed():
    assert table_price_columns(("Equipment description", "Cost", "Condition"),
                               (("Synthetic pump", "950", "Casing worn"),)) == (1,)
    assert table_price_columns(("Equipment", "Unit"),
                               (("", "Price"), ("Synthetic pump", "950"))) == (1,)
    assert price_column("Estimated equipment replacement cost")
    assert price_column("Amount")
