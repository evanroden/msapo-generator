from decimal import Decimal

import pytest

from app.po_rules import (
    EQUIPMENT_ACCOUNT,
    EQUIPMENT_PO,
    MATERIALS_ACCOUNT,
    ONSITE_LABOR,
    ONSITE_RENTAL,
    OUTSIDE_RENTALS_ACCOUNT,
    RENTAL_AGREEMENT,
    SERVICE_AGREEMENT,
    STANDARD_PO_OVER_25K,
    STANDARD_PO_UNDER_25K,
    SUBCONTRACTOR_ACCOUNT,
    THIRD_PARTY_SHIPPING,
    VENDOR_DELIVERY,
    classify_po,
    normalize_asset_id,
    parse_amount,
)


@pytest.mark.parametrize(
    ("route", "amount", "account", "agreement"),
    [
        (ONSITE_LABOR, "$1.00", SUBCONTRACTOR_ACCOUNT, SERVICE_AGREEMENT),
        (ONSITE_RENTAL, "$1.00", OUTSIDE_RENTALS_ACCOUNT, RENTAL_AGREEMENT),
        (THIRD_PARTY_SHIPPING, "$1.00", EQUIPMENT_ACCOUNT, EQUIPMENT_PO),
        (
            VENDOR_DELIVERY,
            "$24,999.99",
            MATERIALS_ACCOUNT,
            STANDARD_PO_UNDER_25K,
        ),
        (
            VENDOR_DELIVERY,
            "$25,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
        (
            VENDOR_DELIVERY,
            "$125,000.00",
            MATERIALS_ACCOUNT,
            STANDARD_PO_OVER_25K,
        ),
    ],
)
def test_classification_matrix_is_exact(route, amount, account, agreement):
    result = classify_po(route, amount)
    assert result.object_account == account
    assert result.agreement_type == agreement


def test_vendor_delivery_requires_a_valid_all_in_total():
    with pytest.raises(ValueError, match="all-in PO/CO amount"):
        classify_po(VENDOR_DELIVERY, "")
    with pytest.raises(ValueError, match="all-in PO/CO amount"):
        classify_po(VENDOR_DELIVERY, "not an amount")


def test_unknown_route_is_rejected():
    with pytest.raises(ValueError, match="Choose how"):
        classify_po("legacy_epo", "$100")


def test_amount_parser_preserves_threshold_precision():
    assert parse_amount("$25,000.00") == Decimal("25000.00")
    assert parse_amount("24,999.99 USD") == Decimal("24999.99")
    assert parse_amount(None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A001234", "001234"),
        ("EEA-CWP-07", "07"),
        ("AHU 3", "3"),
        ("12345", "12345"),
        ("None Applicable", ""),
        ("N/A", ""),
        ("no numeric value", ""),
    ],
)
def test_asset_id_contains_only_the_numeric_identifier(raw, expected):
    assert normalize_asset_id(raw) == expected

