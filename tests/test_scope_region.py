"""Routing reads the quoted scope, not the vendor's terms and conditions.

Reported from production: a Trane service quote for chiller oil-pump repair --
mobilize, troubleshoot, repair wiring, start up, demobilize, travel included --
classified as 5301-MATERIALS / ON - STANDARD PO UNDER $25K. The contract
administrator flagged it as 5511, which is correct: it is nothing but labour.

The cause was not the labour rules. It was WHAT THEY READ. That quote extracts
to 45,866 characters of which the proposal is the first 3,563; the other 92% is
standard legal text, and it contains the exact phrases the rules key on:

  * "modifications made by others to Company's equipment" (warranty exclusions)
    tripped the document-level labour disclaimer, silencing the labour signal
    for the whole quote;
  * "the cost of transporting a part requiring service", and thirteen more like
    it, made the parts-purchase guard fire.

Two independent misreads, one cause: the rules were classifying the boilerplate.

The realistic-quote corpus in test_po_rules.py could not have caught this. Its
entries are bare scope text, which is not what OCR hands us in production.

Nothing here is copied from the real document -- the repository forbids
committing real quotes. These fixtures reproduce its STRUCTURE: a short labour
scope followed by long boilerplate carrying the trigger phrases.
"""

from __future__ import annotations

import pytest

from app.po_rules import (
    MATERIALS_PURCHASE,
    ONSITE_LABOR,
    classify_po,
    infer_purchase_route,
    scope_region,
)


LABOR_SCOPE = """
Project Name: CH-3 differential oil pressure
Scope of Service:
Mobilize personnel and equipment
Troubleshoot oil pump not starting
Isolate and lock out unit
Repair burnt and damaged wiring
Return unit to service
Perform startup and verify operation
Demobilize personnel and equipment
Price includes travel
Total Price: $870.00
"""

# The two phrases that actually did the damage, in the sections they came from.
BOILERPLATE = """
TERMS AND CONDITIONS - QUOTED SERVICE
Company will be responsible for the cost of transporting a part requiring
service. Any repairs made will be those selected by Company as suitable for the
repair and may be parts not manufactured by Company.
This warranty excludes damage caused by unauthorized or improper maintenance,
unauthorized or improper parts or material, refrigerant not supplied by
Company, and modifications made by others to Company's equipment.
"""


def test_the_reported_quote_shape_routes_to_labor_not_materials():
    """The end-to-end assertion: what the operator would have been shown."""
    document = LABOR_SCOPE + BOILERPLATE

    assert infer_purchase_route(document) == ONSITE_LABOR
    result = classify_po(infer_purchase_route(document), "870.00")
    assert result.object_account == "5511-SUBCONTRACTOR"
    assert result.agreement_type == "03 - MSAPO (SERVICE)"


def test_the_boilerplate_alone_is_what_flipped_the_answer():
    """Pins the cause, not just the symptom. The scope routes correctly on its
    own; appending the terms is what used to change the answer."""
    assert infer_purchase_route(LABOR_SCOPE) == ONSITE_LABOR
    assert infer_purchase_route(LABOR_SCOPE + BOILERPLATE) == ONSITE_LABOR


@pytest.mark.parametrize(
    "heading",
    [
        "TERMS AND CONDITIONS",
        "Terms & Conditions",
        "STANDARD TERMS OF SALE",
        "General Terms",
        "LIMITED WARRANTY",
        "Limitation of Liability",
        "Indemnification",
    ],
)
def test_each_boilerplate_heading_ends_the_scope(heading):
    document = f"{LABOR_SCOPE}\n{heading}\n{BOILERPLATE}"
    assert heading.lower() not in scope_region(document).lower()
    assert infer_purchase_route(document) == ONSITE_LABOR


def test_a_document_with_no_boilerplate_is_untouched():
    assert scope_region(LABOR_SCOPE) == LABOR_SCOPE


def test_terms_appearing_before_any_scope_do_not_gut_the_document():
    """The cut is conservative in both directions. A quote whose heading lands
    in the first couple of hundred characters keeps everything, because removing
    the remainder would leave nothing to classify."""
    document = "TERMS AND CONDITIONS\n" + LABOR_SCOPE
    assert scope_region(document) == document
    assert infer_purchase_route(document) == ONSITE_LABOR


def test_a_genuine_exclusion_in_the_scope_still_counts():
    """Only legal boilerplate is removed. 'Labor by others' written into the
    PROPOSAL is a real statement about the job and must still suppress the
    labour route -- otherwise this fix would swing the error the other way."""
    document = (
        "Scope of Supply:\n"
        "Furnish one replacement oil pump assembly and service parts.\n"
        "Freight prepaid to site. Labor by others.\n"
        "Total Price: $4,200.00\n"
    ) + BOILERPLATE

    assert infer_purchase_route(document) == MATERIALS_PURCHASE
