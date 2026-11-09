"""Synthetic catalog identity collisions must not become ambiguous site choices.

Only catalog titles/temporary in-memory directory views; no saved reports or
actual contract records are accessed or altered.
"""

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_site_catalog as catalog
from app.monthly_report_model import Facility


def setup_catalog(monkeypatch, names):
    sentinel = object()
    calls = []
    monkeypatch.setattr(catalog.contracts, "sites_for_contract", lambda contract: list(names))
    monkeypatch.setattr(directory, "load_directory", lambda contract: sentinel)

    def available(originals, state):
        calls.append((tuple(originals), state))
        return tuple(originals)

    monkeypatch.setattr(directory, "available_sites", available)
    return calls, sentinel


@pytest.mark.parametrize("names", (
    ("North Plant/A", "North Plant-A"),
    ("North Plant_A", "North Plant-A"),
    ("N" * 65 + "-west", "N" * 65 + "-east"),
    ("Synthetic North", "Synthetic North"),
    ("Synthetic North", "SYNTHETIC NORTH"),
))
def test_colliding_site_keys_are_refused_before_directory_merging(monkeypatch, names):
    calls, _ = setup_catalog(monkeypatch, names)
    with pytest.raises(ValueError, match="same report site key"):
        catalog.site_options("Synthetic Contract")
    assert calls == [], "No ambiguous catalog keys should reach directory merging"


def test_distinct_existing_catalog_keys_and_order_are_unchanged(monkeypatch):
    names = ("North Plant/A", "North Plant B", "South Block 02")
    calls, sentinel = setup_catalog(monkeypatch, names)
    result = catalog.site_options("Synthetic Contract")
    assert result == (
        Facility("north-plant-a", "North Plant/A"),
        Facility("north-plant-b", "North Plant B"),
        Facility("south-block-02", "South Block 02"),
    )
    assert calls == [(result, sentinel)]


def test_long_but_unique_slug_remains_identical_to_prior_key(monkeypatch):
    names = ("North/Plant " + "A" * 80, "South-Plant")
    calls, _ = setup_catalog(monkeypatch, names)
    result = catalog.site_options("Synthetic Contract")
    assert result[0].key == ("north-plant-" + "a" * 80)[:60]
    assert result[0].title == names[0]
    assert result[1].key == "south-plant"
    assert len(calls) == 1


def test_empty_catalog_keeps_empty_result(monkeypatch):
    calls, sentinel = setup_catalog(monkeypatch, ())
    assert catalog.site_options("Synthetic Contract") == ()
    assert calls == [((), sentinel)]


def test_saved_directory_is_only_read_and_forwarded(monkeypatch):
    names = ("Synthetic East",)
    calls, sentinel = setup_catalog(monkeypatch, names)
    result = catalog.site_options("Synthetic Contract")
    assert calls[0][1] is sentinel
    assert result == (Facility("synthetic-east", "Synthetic East"),)


def test_rrh_owner_confirmed_keys_and_aliases_are_not_rebuilt(monkeypatch):
    monkeypatch.setattr(catalog, "FACILITIES", {
        "united_memorial": {"name": "Synthetic Memorial"},
        "rochester_general": {"name": "Synthetic General"},
        "st_marys": {"name": "Synthetic St. Mary's"},
        "unity_specialty": {"name": "Synthetic Unity"},
    })
    calls, sentinel = setup_catalog(monkeypatch, ())
    results = catalog.site_options(catalog.contracts.RRH_CONTRACT)
    by_key = {site.key: site for site in results}
    assert set(by_key) == {"united_memorial", "rochester_general", "unity_specialty"}
    assert by_key["united_memorial"].aliases == ("UMMC",)
    assert by_key["rochester_general"].aliases == ("RGH",)
    assert by_key["unity_specialty"].aliases == ("Synthetic St. Mary's",)
    assert len(calls) == 1 and calls[0][1] is sentinel
