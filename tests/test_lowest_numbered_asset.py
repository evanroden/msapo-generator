"""When the scope names an equipment TYPE, resolve to the lowest-numbered unit.

Product direction: the tool was returning no asset at all in exactly the cases
where the type was obvious ("repair the chiller", "boiler teardown"), because
the scorer refuses to break a tie between units of the same type. It should
default to the lowest-numbered unit of that type and let the operator change it.

"Lowest-numbered" means the lowest that EXISTS at the site, not the number one.
United Memorial's chillers are CH-2 and CH-3 -- there is no CH-1 -- so chiller
work there resolves to CH-2. That case is the reason this is a registry lookup
rather than string arithmetic.
"""

from __future__ import annotations

import pytest

from app.assets import assets_for_facility
from app.asset_guess import _tag_sort_key, lowest_numbered_of_type


def _tag_for(rows, uid):
    return next((row["asset"] for row in rows if row["uid"] == uid), None)


def _resolve(site: str, text: str) -> str | None:
    rows = assets_for_facility(site)
    return _tag_for(rows, lowest_numbered_of_type(rows, quote_text=text))


@pytest.mark.parametrize(
    ("site", "text", "expected"),
    [
        # The stated examples, verified against the real registry.
        ("united_memorial", "Replace chiller compressor bearings", "CH-2"),
        ("united_memorial", "Cooling tower repair and cleaning", "CT-1"),
        ("united_memorial", "Steam boiler teardown and reassembly", "B-1"),
        # Rochester General pads its tags, so the comparison must be numeric.
        ("rochester_general", "Centrifugal chiller annual service", "CH-01"),
        ("rochester_general", "Steam boiler tube replacement", "B-01"),
    ],
)
def test_named_equipment_type_resolves_to_the_lowest_existing_unit(site, text, expected):
    assert _resolve(site, text) == expected


def test_united_memorial_has_no_chiller_one():
    """Pins the fact the rule depends on, so a registry change cannot quietly
    invalidate the CH-2 expectation above."""
    tags = {
        row["asset"]
        for row in assets_for_facility("united_memorial")
        if "chiller" in (row.get("equipment") or "").lower()
    }
    assert "CH-1" not in tags
    assert {"CH-2", "CH-3"} <= tags


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Work on the chiller and the cooling tower", "two types are ambiguous"),
        ("General site maintenance", "no type named at all"),
        ("", "no text"),
    ],
)
def test_ambiguous_or_absent_types_resolve_to_nothing(text, reason):
    """Guessing between two named types is worse than leaving it unset -- the
    conservative behaviour that the AS-1 air-separator fix established."""
    assert lowest_numbered_of_type(
        assets_for_facility("united_memorial"), quote_text=text
    ) is None, reason


def test_a_near_miss_type_does_not_capture_the_parent_equipment():
    """"Chiller VFD" and "Cooling Tower Fill" are separate assets. Their head
    nouns differ from their parents' (VFD, FILL vs CHILLER, TOWER), which is
    what keeps "replace the chiller" off the VFD and vice versa."""
    rows = assets_for_facility("united_memorial")
    # Naming the VFD brings both CHILLER and VFD into play -> ambiguous, unset.
    assert lowest_numbered_of_type(rows, quote_text="Replace the chiller VFD") is None
    # The fill likewise never answers a plain cooling-tower request.
    assert _tag_for(rows, lowest_numbered_of_type(rows, quote_text="cooling tower")) == "CT-1"


@pytest.mark.parametrize("word", ["system", "unit", "pump"])
def test_broad_head_nouns_never_choose_the_lowest_unrelated_asset(word):
    rows = [
        {"uid": "A-1", "asset": "A-1", "equipment": f"Heating {word}"},
        {"uid": "A-2", "asset": "A-2", "equipment": f"Cooling {word}"},
    ]

    assert lowest_numbered_of_type(rows, quote_text=f"Inspect the {word}") is None


def test_tags_sort_by_unit_number_not_text():
    """A string sort puts CH-10 before CH-2, which would pick the wrong unit."""
    assert sorted(["CH-10", "CH-2", "CH-1"], key=_tag_sort_key) == ["CH-1", "CH-2", "CH-10"]
    assert sorted(["B-3676", "B-1"], key=_tag_sort_key) == ["B-1", "B-3676"]
    # Zero padding must not change the order either.
    assert sorted(["CH-02", "CH-01"], key=_tag_sort_key) == ["CH-01", "CH-02"]
    # A tag with no number sorts last rather than raising.
    assert sorted(["AHU", "AHU-2"], key=_tag_sort_key) == ["AHU-2", "AHU"]
