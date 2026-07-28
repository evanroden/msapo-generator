from app.config import (
    FACILITY_SHORT_NAMES,
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
