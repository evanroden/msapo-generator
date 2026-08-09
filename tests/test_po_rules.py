from decimal import Decimal

import pytest

from app.equipment_policy import group_a_equipment_match
from app.po_rules import (
    EQUIPMENT_ACCOUNT,
    EQUIPMENT_PO,
    EQUIPMENT_PURCHASE,
    MATERIALS_ACCOUNT,
    MATERIALS_PURCHASE,
    ONSITE_LABOR,
    ONSITE_RENTAL,
    OUTSIDE_RENTALS_ACCOUNT,
    RENTAL_AGREEMENT,
    SERVICE_AGREEMENT,
    STANDARD_PO_OVER_25K,
    STANDARD_PO_UNDER_25K,
    SUBCONTRACTOR_ACCOUNT,
    classify_po,
    infer_purchase_route,
    normalize_asset_id,
    parse_amount,
)


@pytest.mark.parametrize(
    ("route", "amount", "account", "agreement"),
    [
        (ONSITE_LABOR, "$1.00", SUBCONTRACTOR_ACCOUNT, SERVICE_AGREEMENT),
        (ONSITE_RENTAL, "$1.00", OUTSIDE_RENTALS_ACCOUNT, RENTAL_AGREEMENT),
        (EQUIPMENT_PURCHASE, "$1.00", EQUIPMENT_ACCOUNT, EQUIPMENT_PO),
        (
            MATERIALS_PURCHASE,
            "$24,999.99",
            MATERIALS_ACCOUNT,
            STANDARD_PO_UNDER_25K,
        ),
        (
            MATERIALS_PURCHASE,
            "$25,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
        (
            MATERIALS_PURCHASE,
            "$125,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
    ],
)
def test_ashley_classification_matrix_is_exact(route, amount, account, agreement):
    result = classify_po(route, amount)
    assert result.object_account == account
    assert result.agreement_type == agreement


def test_materials_purchase_requires_a_valid_all_in_total():
    with pytest.raises(ValueError, match="all-in PO/CO amount"):
        classify_po(MATERIALS_PURCHASE, "")
    with pytest.raises(ValueError, match="all-in PO/CO amount"):
        classify_po(MATERIALS_PURCHASE, "not an amount")


@pytest.mark.parametrize(
    "route", [ONSITE_LABOR, ONSITE_RENTAL, EQUIPMENT_PURCHASE, MATERIALS_PURCHASE]
)
@pytest.mark.parametrize("amount", ["", "$0.00", "-$1.00", "1e3", "12.345"])
def test_every_route_requires_a_strictly_positive_valid_total(route, amount):
    with pytest.raises(ValueError, match=r"greater than \$0.00"):
        classify_po(route, amount)


def test_unknown_route_is_rejected():
    with pytest.raises(ValueError, match="Choose how"):
        classify_po("legacy_epo", "$100")


def test_amount_parser_preserves_threshold_precision():
    assert parse_amount("$25,000.00") == Decimal("25000.00")
    assert parse_amount("24,999.99 USD") == Decimal("24999.99")
    assert parse_amount(None) is None
    assert parse_amount("1e3") is None
    assert parse_amount("$12.345") is None
    assert parse_amount("USD 1,234.50") == Decimal("1234.50")


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Technician will repair chiller CH-1 onsite", ONSITE_LABOR),
        ("Four-week rental chiller with delivery", ONSITE_RENTAL),
        ("Purchase one new 500-ton chiller", EQUIPMENT_PURCHASE),
        ("Supply replacement chiller gaskets and filters", MATERIALS_PURCHASE),
        ("Water-softener salt delivery", MATERIALS_PURCHASE),
    ],
)
def test_route_fallback_guesses_more_without_using_delivery_method(quote, expected):
    assert infer_purchase_route(quote) == expected


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Installation excluded. Supply one new chiller.", EQUIPMENT_PURCHASE),
        ("No vendor labor. Purchase one new boiler.", EQUIPMENT_PURCHASE),
        ("Rental by others. Supply water-softener salt.", MATERIALS_PURCHASE),
        ("Rental not included; technician will repair the pump onsite.", ONSITE_LABOR),
        ("Installation and labor excluded. Supply one new chiller.", EQUIPMENT_PURCHASE),
        ("Rental equipment is excluded. Supply water-softener salt.", MATERIALS_PURCHASE),
        ("Installation is not part of the quoted scope. Supply one new boiler.", EQUIPMENT_PURCHASE),
    ],
)
def test_fallback_does_not_route_from_negated_or_excluded_work(quote, expected):
    assert infer_purchase_route(quote) == expected


def test_group_a_source_recognizes_complete_equipment_but_not_loose_parts():
    assert group_a_equipment_match("Purchase one new boiler") == "Boiler"
    assert group_a_equipment_match("Long-lead procurement equipment") == "Long-lead Equipment"
    assert group_a_equipment_match(
        "Owner-furnished, contractor-installed equipment"
    ) == "Owner-furnished Equipment"
    assert group_a_equipment_match("Provide chiller gaskets and filters") is None
    assert group_a_equipment_match("Supply replacement chiller gaskets") is None
    assert group_a_equipment_match("Supply one chiller and spare gaskets") == "Chiller"
    assert (
        group_a_equipment_match("Provide chiller parts and purchase one new boiler")
        == "Chiller"
    )
    assert group_a_equipment_match("Box delivered by third-party carrier") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A001234", "A001234"),
        ("EEA-CWP-07", "EEA-CWP-07"),
        ("AHU 3", "AHU 3"),
        ("12345", "12345"),
        ("  EEA-CWP-07   NORTH  ", "EEA-CWP-07 NORTH"),
        ("None Applicable", ""),
        ("N/A", ""),
        ("— Choose an asset or No asset —", ""),
    ],
)
def test_asset_id_preserves_the_full_configured_code(raw, expected):
    assert normalize_asset_id(raw) == expected
