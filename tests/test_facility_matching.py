"""A facility alias must match WHOLE WORDS, not any substring.

Found during the 2026-08-17 review, by testing the matcher against its own
configuration rather than reading it.

The alias "unity hospital" is a substring of "Community Hospital". So
Newark-Wayne Community Hospital -- a real RRH site -- was silently rewritten to
Unity Hospital, and the damage went well past the label:

    site        Newark-Wayne Community Hospital  ->  Unity Hospital
    address     1200 Driving Park Ave, Newark    ->  1555 Long Pond Rd, Rochester
    cost code   01DEAR                           ->  01FEAR
    repair_cap  01DEARC                          ->  None

That last line is the worst of it. repair_cap exists ONLY at Newark-Wayne, so
after the swap the category is not merely miscoded -- it disappears from the
site's valid list entirely. The address is the one printed on the MSAPO form
that goes to the vendor.

Nothing surfaced any of this. The operator saw a confidently identified site.

app.config.facility_key_from_name was already safe for an EXACT name, because it
runs an exact pass first; quote_analyzer._match_facility had no such pass and
went straight to substring aliases. Both now share app.config.alias_matches.
"""

from __future__ import annotations

import pytest

from app.config import (
    FACILITIES,
    alias_matches,
    facility_key_from_name,
    lookup_cost_code,
)
from app.contracts import match_facility
from app.quote_analyzer import _match_facility


def test_community_hospital_does_not_match_unity_hospital():
    """The exact reported failure, at the lowest level."""
    assert not alias_matches("unity hospital", "Newark-Wayne Community Hospital")
    assert alias_matches("unity hospital", "Unity Hospital")


def test_newark_wayne_survives_the_full_resolution_chain():
    name, address = _match_facility(
        "Newark-Wayne Community Hospital", "1200 Driving Park Ave, Newark, NY 14513"
    )

    assert name == "Newark-Wayne Community Hospital"
    assert address == "1200 Driving Park Ave, Newark, NY 14513"

    key = facility_key_from_name(name)
    assert key == "newark_wayne"
    assert lookup_cost_code(key, "repairs") == "01DEAR"
    # repair_cap is a Newark-Wayne-only category; the swap made it vanish.
    assert lookup_cost_code(key, "repair_cap") == "01DEARC"


@pytest.mark.parametrize("key", sorted(FACILITIES))
def test_every_configured_site_resolves_to_itself(key):
    """The matcher is checked against its own configuration. Any site that does
    not round-trip is being silently reassigned to another one."""
    facility = FACILITIES[key]
    assert _match_facility(facility["name"], facility["address"]) == (
        facility["name"],
        facility["address"],
    )


def test_the_two_unity_sites_are_never_confused():
    """They share a name stem, so an alias-only match would let dict order pick.
    The exact-name pass has to run over every site before any alias is tried."""
    assert facility_key_from_name("Unity Hospital") == "unity"
    assert facility_key_from_name("Unity Specialty Hospital") == "unity_specialty"
    assert _match_facility("Unity Specialty Hospital", None)[0] == (
        "Unity Specialty Hospital"
    )


def test_an_unknown_site_is_returned_untouched_rather_than_guessed():
    """Returning the model's own value is the honest answer for an unrecognised
    site. Coercing it to the nearest configured name is what caused this bug."""
    assert _match_facility("Community Hospital", None) == ("Community Hospital", None)
    assert _match_facility("Some Other Clinic", "1 Nowhere Rd") == (
        "Some Other Clinic",
        "1 Nowhere Rd",
    )


def test_aliases_carrying_punctuation_still_match():
    """Several aliases are not bare words -- "st. mary", "canton-potsdam",
    "127 north". This is why alias_matches uses lookarounds rather than \\b,
    which asserts the wrong thing next to a "." or "-"."""
    assert alias_matches("st. mary", "St. Mary's Medical Campus")
    assert alias_matches("canton-potsdam", "Canton-Potsdam Hospital")
    assert alias_matches("127 north", "127 North St, Batavia, NY 14020")
    assert alias_matches("14621", "1425 Portland Ave, Rochester, NY 14621")
    # A ZIP embedded in a longer number is not that ZIP.
    assert not alias_matches("14621", "invoice 1462100 attached")


# --- A generic site label is not evidence on its own -----------------------


def test_an_unknown_hospital_is_left_unresolved_not_billed_to_conway():
    """The registry really does name Conway sites "Hospital", "Rehab" and
    "Oncology", and an EAMC site "Valley". Matching one inside a LONGER unknown
    name routed the PO to a different customer's account, and the routing
    snapshot then reported routing as complete -- so the contract control stayed
    in the collapsed panel and the operator never saw it.

    Product decision 2026-08-17: precision over recall. Unresolved surfaces the
    control in the visible "Needs You" panel; a wrong contract does not surface
    at all.
    """
    for name in (
        "Mercy Hospital",
        "St. Joseph Hospital",
        "Green Valley Medical",
        "Community Rehab Center",
    ):
        assert match_facility(name) == (None, None), name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Hospital", ("Conway", "Hospital")),
        ("Rehab", ("Conway", "Rehab")),
        ("Oncology", ("Conway", "Oncology")),
        ("Valley", ("EAMC", "Valley")),
    ],
)
def test_a_generic_site_still_resolves_when_it_is_the_whole_field(name, expected):
    """The recall this trade costs is exactly one click, and only here: the site
    is still matched when the facility field names it and nothing else."""
    assert match_facility(name) == expected


def test_generic_words_in_quote_prose_do_not_route_anything():
    """The quote-text pass was the worse half. A vendor named "Valley
    Mechanical", or a line reading "the chiller is inoperable" -- UNO has a site
    labelled INOPERABLE -- was enough to pick a contract."""
    assert match_facility(None, "Quote from Valley Mechanical Inc") == (None, None)
    assert match_facility(None, "the chiller is inoperable") == (None, None)
    assert match_facility(None, "work performed at the hospital") == (None, None)


@pytest.mark.parametrize(
    "quote",
    [
        "Quote from Beacon Mechanical for Mercy Hospital",
        "Prepared by Shaw Services for Mercy Hospital",
        "Technician will travel from Lexington to Mercy Hospital",
        "Ship through Newport Freight to Mercy Hospital",
        "Tulane controls supplied the panel for Mercy Hospital",
        "UNO Mechanical prepared this proposal for Mercy Hospital",
    ],
)
def test_one_word_registry_sites_do_not_route_from_incidental_quote_prose(quote):
    """A vendor, origin, or carrier name is not the service destination."""
    assert match_facility("Mercy Hospital", quote) == (None, None)


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("Site: Opelika", ("EAMC", "Opelika")),
        ("Work at Lexington", ("Baptist KY", "Lexington")),
        ("Deliver to Newport", ("Unity Health", "Newport")),
    ],
)
def test_one_word_registry_sites_still_route_with_destination_context(quote, expected):
    assert match_facility(None, quote) == expected


def test_one_word_registry_site_still_resolves_from_exact_facility_field():
    assert match_facility("Beacon") == ("Beacon", "Beacon")


def test_place_names_and_zips_still_decide_alone():
    """Deliberately NOT in _GENERIC_SITE_WORDS. These are the aliases that make
    ordinary address text resolve, and they are distinctive enough to trust."""
    assert match_facility(None, "work at 127 North St, Batavia, NY 14020") == (
        "Rochester Regional Health",
        "UMMC",
    )
    assert match_facility(None, "site: Opelika")[0] == "EAMC"


def test_a_real_site_further_along_the_haystack_still_wins():
    """A rejected generic match must SKIP, not abort the scan -- otherwise one
    incidental "hospital" would suppress the real site named beside it."""
    assert match_facility("Newark-Wayne Community Hospital") == (
        "Rochester Regional Health",
        "Newark Wayne",
    )
