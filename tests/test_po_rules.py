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
def test_approved_classification_matrix_is_exact(route, amount, account, agreement):
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


@pytest.mark.parametrize(
    "quote",
    [
        (
            "Installation by others. Vendor technician will perform startup "
            "and commissioning onsite."
        ),
        "Rigging by others. Vendor will provide two days of onsite startup labor.",
    ],
)
def test_disclaimer_in_one_clause_does_not_cancel_affirmative_vendor_labor(quote):
    assert infer_purchase_route(quote) == ONSITE_LABOR


def test_group_a_source_recognizes_complete_equipment_but_not_loose_parts():
    assert group_a_equipment_match("Purchase one new boiler") == "Boiler"
    assert group_a_equipment_match("Long-lead procurement equipment") == "Long-lead Equipment"
    assert group_a_equipment_match(
        "Owner-furnished, contractor-installed equipment"
    ) == "Owner-furnished Equipment"
    assert group_a_equipment_match("Provide chiller gaskets and filters") is None
    assert group_a_equipment_match("Supply replacement chiller gaskets") is None
    assert group_a_equipment_match("Supply one chiller and spare gaskets") == "Chiller"
    assert group_a_equipment_match("Purchase one new chilled water pump") == "Pump"
    assert group_a_equipment_match("Purchase one new oil pump") is None
    assert (
        group_a_equipment_match("Provide chiller parts and purchase one new boiler")
        == "Chiller"
    )
    assert group_a_equipment_match("Box delivered by third-party carrier") is None


@pytest.mark.parametrize(
    "quote",
    [
        "Purchase one new 500-ton chiller. Freight and spare filters included.",
        "Provide chiller parts and purchase one new boiler.",
    ],
)
def test_parts_in_a_mixed_quote_do_not_veto_a_complete_group_a_purchase(quote):
    assert infer_purchase_route(quote) == EQUIPMENT_PURCHASE


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


# --- Routing corpus: the misclassifications that sent quotes to the wrong
# --- Object Account and Agreement Type in production.

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Onsite labour, correctly detected before and after.
        ("Technician will be onsite to replace pump seals and commission the unit.",
         "onsite_labor"),
        ("Vendor technician performs annual inspection and service of the boiler.",
         "onsite_labor"),
        # Rental keeps priority over the equipment noun it mentions.
        ("Emergency rental chiller brought onsite and hooked up for the duration.",
         "onsite_rental"),
        ("Rental scissor lift provided for the duration of the repair.",
         "onsite_rental"),
        # A complete Group A item with no vendor labour.
        ("Supply and deliver one replacement air handling unit. Installation by others.",
         "equipment_purchase"),
        ("Furnish one new centrifugal chiller, freight included. No installation.",
         "equipment_purchase"),
        # REGRESSION: a labour word used as a noun modifier names a product.
        # "repair kits" and "service parts" both routed to 5511-SUBCONTRACTOR.
        ("Quote for pipe fittings and valve repair kits, shipped to site.",
         "materials_purchase"),
        ("Supply replacement service parts for the boiler. Labor by others.",
         "materials_purchase"),
        # REGRESSION: parts FOR a Group A item are materials, not the item.
        # "boiler" alone previously carried this to 5302-EQUIPMENT.
        ("Replacement gaskets and bearings for the chiller, shipped.",
         "materials_purchase"),
        # A disclaimer in a LATER sentence still negates the labour signal.
        ("Ship 40 replacement filters and 12 gaskets. No labor included.",
         "materials_purchase"),
        ("Provide maintenance contract documentation only; no onsite labor.",
         "materials_purchase"),
        ("Deliver 6 drums of water treatment chemical. Customer to apply.",
         "materials_purchase"),
        # "part of" is an idiom, not a component -- this must stay equipment.
        ("Installation is not part of the quoted scope. Supply one new boiler.",
         "equipment_purchase"),
    ],
)
def test_route_inference_over_a_realistic_quote_corpus(text, expected):
    """Every route reachable, and the two false-labour patterns pinned.

    Object Account and Agreement Type derive entirely from this answer, and a
    wrong answer is invisible downstream: it simply appears in Smartsheet as a
    confident 5511-SUBCONTRACTOR / 03 - MSAPO (SERVICE).
    """
    assert infer_purchase_route(text) == expected
