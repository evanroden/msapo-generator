from app import contracts


def test_known_contracts_include_rrh_and_non_rrh():
    assert contracts.is_known_contract(contracts.RRH_CONTRACT)
    assert contracts.is_known_contract("Tulane")
    assert not contracts.is_known_contract(None)
    assert not contracts.is_known_contract("— Select a contract —")


def test_unspecified_site_buckets_are_not_selectable():
    assert "(unspecified site)" not in contracts.sites_for_contract("Clinton")
    assert "(unspecified site)" not in contracts.sites_for_contract("MCH")


def test_case_only_duplicate_sites_are_merged():
    sites = contracts.sites_for_contract("Conway")

    assert "Rehab" in sites
    assert "REHAB" not in sites
    assert len([site for site in sites if site.casefold() == "rehab"]) == 1
