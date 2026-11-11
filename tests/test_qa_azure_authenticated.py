"""Stage isolation and access guards are pure local tests; no live identity calls."""
import json

from scripts.qa_azure_authenticated import check_origin, isolated, main


GOOD = {"environment": "staging", "smartsheet_api_mode": "disabled", "production_write_access": False,
        "database_target": "stg-db", "database_production": "prod-db",
        "files_target": "stg-files", "files_production": "prod-files",
        "smartsheet_target": "dry-run", "smartsheet_production": "production"}


def test_staging_requires_three_distinct_external_resources_and_no_prod_writes():
    assert isolated(GOOD)
    for key, value in (("environment", "production"), ("smartsheet_api_mode", "live"),
                       ("production_write_access", True), ("database_target", "prod-db"),
                       ("files_target", "prod-files"), ("smartsheet_target", "production")):
        invalid = {**GOOD, key: value}
        assert not isolated(invalid), key
    assert not isolated({**GOOD, "database_target": ""})


def test_https_exact_origin_and_separate_host_are_required():
    assert check_origin("https://stage.example.invalid", "https://production.example.invalid")
    for candidate in ("http://stage.example.invalid", "https://production.example.invalid",
                      "https://stage.example.invalid/hidden", "https://user:pass@stage.example.invalid",
                      "https://stage.example.invalid?bypass=1"):
        assert not check_origin(candidate, "https://production.example.invalid")


def test_preflight_blocks_before_network_access(tmp_path):
    state = tmp_path / "auth.json"
    state.write_text("{}")
    identity = tmp_path / "isolation.json"
    identity.write_text(json.dumps({**GOOD, "production_write_access": True}))
    out = tmp_path / "result.json"
    rc = main(["--origin", "https://stage.example.invalid",
               "--production-origin", "https://production.example.invalid",
               "--sha", "a"*40, "--storage-state", str(state),
               "--isolation-json", str(identity), "--output", str(out)])
    assert rc == 4
    assert json.loads(out.read_text())["status"] == "BLOCKED"
