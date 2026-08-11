import json
from pathlib import Path

from app import contracts


REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "app" / "data" / "contracts.json"


def test_known_contracts_include_rrh_and_non_rrh():
    assert contracts.is_known_contract(contracts.RRH_CONTRACT)
    assert contracts.is_known_contract("Tulane")
    assert not contracts.is_known_contract(None)
    assert not contracts.is_known_contract("— Select a contract —")


def test_production_registry_cannot_be_replaced_by_an_empty_placeholder():
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    assert len(raw) == 36
    assert sum(len(sites) for sites in raw.values()) == 106
    assert sum(len(rows) for sites in raw.values() for rows in sites.values()) == 11_368
    assert "Tulane" in raw


def test_unspecified_site_buckets_are_not_selectable():
    assert "(unspecified site)" not in contracts.sites_for_contract("Clinton")
    assert "(unspecified site)" not in contracts.sites_for_contract("MCH")


def test_case_only_duplicate_sites_are_merged():
    sites = contracts.sites_for_contract("Conway")

    assert "Rehab" in sites
    assert "REHAB" not in sites
    assert len([site for site in sites if site.casefold() == "rehab"]) == 1
