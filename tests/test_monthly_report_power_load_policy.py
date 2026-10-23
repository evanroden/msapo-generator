"""Unit-qualified power loads are technical data, not quote estimates.

These are policy-level synthetic controls; they do not certify browser output
or a genuine retained report. Existing native-output suites cover rendering.
"""
import pytest

from app.monthly_report_content_policy import (
    ambiguous_price_columns,
    contains_price,
    price_column,
    schema_price_columns,
    table_has_pricing,
    table_price_columns,
)


POWER_UNITS = ("W", "kW", "MW")
VALUES = (("Synthetic generator A", "150"), ("Synthetic generator B", "27.5"))


@pytest.mark.parametrize("unit", POWER_UNITS)
@pytest.mark.parametrize("template", [
    "Est. Peak Coincident Load ({unit})",
    "Estimate Peak Coincident Load ({unit})",
    "Est PeakCoincidentLoad ({unit})",
    "Est.\nPeak Coincident\nLoad ( {unit} )",
])
def test_power_load_headings_survive_raw_table_and_schema_gates(unit, template):
    title = template.format(unit=unit)
    columns = ("Equipment", title)
    before = (columns, VALUES)
    assert not price_column(title)
    assert table_price_columns(columns, VALUES) == ()
    assert schema_price_columns(columns, VALUES) == ()
    assert ambiguous_price_columns(columns, VALUES) == ()
    assert not table_has_pricing(columns, VALUES)
    assert (columns, VALUES) == before


@pytest.mark.parametrize("unit", POWER_UNITS)
def test_wrapped_heading_rows_use_the_same_complete_unit_proof(unit):
    columns = ("Equipment", "Est.")
    rows = (("", "Peak Coincident"), ("", f"Load ({unit})"), *VALUES)
    assert price_column("Est.")  # The fragment alone is still ambiguous.
    assert table_price_columns(columns, rows) == ()
    assert schema_price_columns(columns, rows) == ()
    assert not table_has_pricing(columns, rows)
    assert rows[-2:] == VALUES


@pytest.mark.parametrize("unit", ("ton", "tons", "MBH", "w", "kw", "mw"))
def test_existing_units_and_case_variants_remain_supported(unit):
    columns = ("Equipment", f"Est. Peak Coincident Load ({unit})")
    assert not price_column(columns[1])
    assert table_price_columns(columns, VALUES) == ()
    assert not table_has_pricing(columns, VALUES)


@pytest.mark.parametrize("unit", POWER_UNITS)
@pytest.mark.parametrize("wrapped", (False, True))
def test_explicit_currency_schema_cannot_use_the_power_unit_exception(unit, wrapped):
    columns = ("Equipment", "Est." if wrapped else f"Est. Peak Coincident Load ({unit})")
    rows = (("", f"Peak Coincident Load ({unit})"), *VALUES) if wrapped else VALUES
    assert schema_price_columns(columns, rows, kinds=("text", "currency")) == (1,)


@pytest.mark.parametrize("unit", POWER_UNITS)
@pytest.mark.parametrize("value", ("$150", "USD 150", "150 CAD", "Cost: 150", "NTE 150"))
def test_money_values_remain_blocked_under_a_power_load_heading(unit, value):
    columns = ("Equipment", f"Est. Peak Coincident Load ({unit})")
    rows = (("Synthetic generator A", value),)
    assert contains_price(value)
    assert table_has_pricing(columns, rows)


@pytest.mark.parametrize("title", [
    "Estimate",
    "Est. Peak Coincident Load",
    "Est. Peak Coincident Load (USD)",
    "Est. Peak Coincident Load (kWh)",
    "Est. Peak Coincident Load (MWh)",
    "Est. Peak Coincident Load (kW/USD)",
    "Est. Peak Coincident Load ($/kW)",
    "Est. Peak Coincident Load (kW/year)",
    "Est. Peak Coincident Load (unknown)",
    "Est. Peak Coincident Load (kW",
    "Est. Peak Coincident Load (kW) Cost",
    "Cost / Est. Peak Coincident Load (MW)",
    "Est. Peak Coincident Load (W) / Quote Amount",
    "Cost (kW)",
    "Unit Price (MW)",
    "Fee / W",
    "Rate",
])
def test_incomplete_unknown_or_financial_headings_do_not_gain_a_unit_waiver(title):
    columns = ("Equipment", title)
    assert price_column(title)
    assert table_price_columns(columns, VALUES) == (1,)
    assert schema_price_columns(columns, VALUES) == (1,)
    assert table_has_pricing(columns, VALUES)


@pytest.mark.parametrize("unit", POWER_UNITS)
def test_mixed_description_and_price_heading_stays_ambiguous(unit):
    columns = ("Equipment", f"Description / Est. Peak Coincident Load ({unit}) / Cost")
    assert ambiguous_price_columns(columns, VALUES) == (1,)
    assert table_price_columns(columns, VALUES) == ()
    assert table_has_pricing(columns, VALUES)


@pytest.mark.parametrize("unit", POWER_UNITS)
def test_separate_price_column_and_unqualified_total_still_require_correction(unit):
    load = f"Est. Peak Coincident Load ({unit})"
    columns = ("Equipment", load, "Cost")
    rows = (("Synthetic generator A", "150", "9000"),)
    assert table_price_columns(columns, rows) == (2,)
    assert schema_price_columns(columns, rows) == (2,)
    assert table_has_pricing(columns, rows)
    assert table_has_pricing(("Equipment", load), (("Total", "150"),))
