from app.config import (
    FACILITY_SHORT_NAMES,
    MANUAL_COST_CODE_SITES,
    SITE_COST_CODE_LETTERS,
    facility_key_from_name,
    lookup_cost_code,
    valid_categories_for_site,
)


def test_unity_specialty_is_selectable_without_inventing_a_cost_code():
    assert facility_key_from_name("Unity Specialty Hospital") == "unity_specialty"
    assert FACILITY_SHORT_NAMES["unity_specialty"] == "Unity Specialty"
    assert valid_categories_for_site("unity_specialty")
    assert "unity_specialty" not in SITE_COST_CODE_LETTERS
    assert lookup_cost_code("unity_specialty", "repairs") is None


def test_every_rrh_site_has_an_automatic_or_explicit_manual_cost_code_decision():
    configured = set(FACILITY_SHORT_NAMES)
    automatic = set(SITE_COST_CODE_LETTERS)

    assert configured == automatic | set(MANUAL_COST_CODE_SITES)
    assert automatic.isdisjoint(MANUAL_COST_CODE_SITES)
    assert MANUAL_COST_CODE_SITES == {"unity_specialty"}
