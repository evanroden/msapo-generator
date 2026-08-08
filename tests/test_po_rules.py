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


def test_unknown_route_is_rejected():
    with pytest.raises(ValueError, match="Choose how"):
        classify_po("legacy_epo", "$100")


def test_amount_parser_preserves_threshold_precision():
    assert parse_amount("$25,000.00") == Decimal("25000.00")
    assert parse_amount("24,999.99 USD") == Decimal("24999.99")
    assert parse_amount(None) is None


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


def test_group_a_source_recognizes_complete_equipment_but_not_loose_parts():
    assert group_a_equipment_match("Purchase one new boiler") == "Boiler"
    assert group_a_equipment_match("Long-lead procurement equipment") == "Long-lead Equipment"
    assert group_a_equipment_match(
        "Owner-furnished, contractor-installed equipment"
    ) == "Owner-furnished Equipment"
    assert group_a_equipment_match("Provide chiller gaskets and filters") is None
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
    ],
)
def test_asset_id_preserves_the_full_configured_code(raw, expected):
    assert normalize_asset_id(raw) == expected
