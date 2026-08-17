"""Routing reads the quoted scope, not the vendor's terms and conditions.

Found while checking a real Trane service quote for chiller oil-pump repair --
mobilize, troubleshoot, repair wiring, start up, demobilize, travel included.
It is nothing but labour, and infer_purchase_route returned 5301-MATERIALS /
ON - STANDARD PO UNDER $25K for it.

No wrong PO resulted: the submitted account was already 5511, and the analyzer's
own guess -- which outranks this fallback -- was never in doubt on a scope this
blatant. What the bad fallback DOES do is disagree with the analyzer on nearly
every real vendor quote, and that disagreement is what route_uncertain uses to
decide whether to interrupt the operator. See
docs/COMMIT_NOTES_2026-08-14_SCOPE_REGION_ROUTING.md section 1.1.

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
    """The end-to-end assertion for the fallback path -- what the operator sees
    when the analyzer returns no usable route, and what route_uncertain compares
    the analyzer against when it does."""
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


# --- Regression: a heading must OWN ITS LINE -------------------------------
#
# The first version of scope_region cut at the first keyword match anywhere past
# 200 characters. "limited warranty" is one of the keywords and is also ordinary
# vendor prose, so a proposal mentioning its own warranty mid-body lost every
# line below it -- including the scope. Measured, not theorised: the case in
# test_an_in_proposal_warranty_line_does_not_truncate_the_scope routed to
# 5302-EQUIPMENT / OR - EQUIPMENT PO instead of 5511-SUBCONTRACTOR, silently,
# because the labour verbs were discarded with the tail.


def test_an_in_proposal_warranty_line_does_not_truncate_the_scope():
    """The exact case that regressed. The vendor header deliberately carries NO
    labour keyword ("Equipment Proposal", not "Service Quote") -- otherwise the
    header alone keeps the labour signal alive above the cut and hides the bug."""
    document = (
        "Carrier Corporation -- Equipment Proposal 88214\n"
        "Site Name: United Memorial Medical Center\n"
        "Attn: Accounts Payable, Rochester NY 14610\n"
        "Project Name: CH-3 differential oil pressure fault\n"
        "Unit: CVHE045 centrifugal chiller, serial L21E01632\n"
        "This proposal carries our standard limited warranty of one year.\n"
        "Scope of Work:\n"
        "Mobilize technicians and equipment to the site.\n"
        "Troubleshoot the oil pump that is not starting.\n"
        "Repair burnt and damaged wiring. Perform startup.\n"
        "Demobilize. Price includes travel.\n"
        "Total Price: $870.00\n"
    )

    assert scope_region(document) == document, "prose keyword truncated the scope"
    assert infer_purchase_route(document) == ONSITE_LABOR
    assert classify_po(infer_purchase_route(document), "870.00").object_account == (
        "5511-SUBCONTRACTOR"
    )


def test_a_long_sentence_beginning_with_the_keyword_is_not_a_heading():
    """Owning the start of the line is not enough -- a heading is also SHORT."""
    document = (
        "Vendor Proposal 12\n"
        + "Detail line.\n" * 14
        + "Limited warranty does not extend to parts supplied by others, and "
        "Company shall have no obligation whatsoever.\n"
        "Scope of Work: Mobilize technicians, troubleshoot, repair the wiring.\n"
    )
    assert scope_region(document) == document


def test_a_numbered_or_bulleted_heading_still_counts():
    """Real documents number their sections. Requiring a bare line start would
    miss "1. TERMS AND CONDITIONS" and reinstate the original misread."""
    for prefix in ("1. ", "  ", "- ", "#  ", "(a) "):
        document = (
            "Vendor Proposal 12\n"
            + "Detail line.\n" * 14
            + f"{prefix}TERMS AND CONDITIONS\n"
            "Company is responsible for transporting a part requiring service.\n"
        )
        kept = scope_region(document)
        assert "TERMS AND CONDITIONS" not in kept, prefix
        assert "Detail line." in kept, prefix


def test_an_early_prose_match_does_not_hide_a_real_heading_below_it():
    """The scan continues past a prose match. Stopping at the first keyword --
    matched or rejected -- would let one mid-body warranty sentence disable
    boilerplate trimming for the whole rest of the document."""
    document = (
        "Vendor Proposal 12\n"
        + "Detail line.\n" * 10
        + "We provide a limited warranty of one year on all supplied parts.\n"
        "Scope of Work: Mobilize technicians and troubleshoot the unit.\n"
        "TERMS AND CONDITIONS\n"
        "Company shall not be obligated to repair parts damaged by others.\n"
    )
    kept = scope_region(document)
    assert "Scope of Work" in kept
    assert "TERMS AND CONDITIONS" not in kept


def test_text_with_no_line_breaks_is_never_cut():
    """Some OCR paths collapse a document to one line. There is then no way to
    tell a heading from prose, so the conservative answer is to cut nothing:
    returning too much text is wrong-but-visible, while cutting real scope
    produces a confident answer from a partial proposal."""
    document = (
        "Vendor Proposal 88214 for chiller repair. " * 6
        + "TERMS AND CONDITIONS Company is responsible for a part requiring service."
    )
    assert "\n" not in document
    assert scope_region(document) == document
