"""Offline guard, fixture and real temporary-store checks. No browser launched."""
from hashlib import sha256
from unittest.mock import Mock

import pytest

from scripts import qa_directory_retention_live as qa

SHA = "d" * 40
TOKEN = "e" * 32


def environment():
    return {"MONTHLY_QA_DIRECTORY_ACCEPTANCE": qa.OPT_IN,
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "evanroden/msapo-generator",
            "GITHUB_REF": "refs/heads/main", "GITHUB_WORKFLOW": "Monthly Isolated Live Acceptance",
            "MONTHLY_QA_EXPECTED_COMMIT": SHA, "MONTHLY_QA_PUBLIC_URL": qa.ORIGIN}


def test_exact_hosted_opt_in_required():
    assert qa.Config.from_environment(environment(), SHA) == qa.Config(SHA)
    for key in environment():
        env = environment()
        env[key] = "incorrect"
        with pytest.raises(qa.SafetyStop):
            qa.Config.from_environment(env, SHA)
    with pytest.raises(qa.SafetyStop):
        qa.Config.from_environment(environment(), "a" * 40)
    with pytest.raises(qa.SafetyStop):
        qa.Config.from_environment({}, SHA)


@pytest.mark.parametrize("suffix", [
    "?workflow=monthly", "?workflow=monthly&monthly_qa=fixtures&monthly_admin=directory",
    "?workflow=monthly&monthly_qa=isolated&monthly_admin=storage",
    "?workflow=monthly&monthly_qa=isolated&monthly_admin=directory&monthly_qa=isolated",
    "?workflow=monthly&monthly_qa=isolated&monthly_admin=directory&unknown=1",
    "?workflow=monthly&monthly_qa=isolated&monthly_admin=directory#fragment",
    "other?workflow=monthly&monthly_qa=isolated&monthly_admin=directory",
])
def test_route_rejects_every_drift(suffix):
    with pytest.raises(qa.SafetyStop):
        qa.validate_route(qa.ORIGIN + "/" + suffix, "directory")


@pytest.mark.parametrize("origin", ["http://msapo-generator.onrender.com", "https://other.example",
                                         "https://msapo-generator.onrender.com.evil.example",
                                         "https://user@msapo-generator.onrender.com"])
def test_origin_is_exact(origin):
    with pytest.raises(qa.SafetyStop):
        qa.validate_route(qa.Config(SHA).address("directory").replace(qa.ORIGIN, origin), "directory")


def test_only_two_admin_routes_and_same_origin_resources():
    config = qa.Config(SHA)
    for kind in ("directory", "storage"):
        url = config.address(kind)
        qa.validate_route(url, kind)
        assert qa.request_allowed(url, kind, top_level=True)
    with pytest.raises(qa.SafetyStop):
        config.address("master")
    with pytest.raises(qa.SafetyStop):
        qa.validate_route(config.address("directory"), "master")
    assert qa.request_allowed(qa.ORIGIN + "/_stcore/upload_file/id", "directory")
    assert not qa.request_allowed(qa.ORIGIN + "/?workflow=monthly", "directory", top_level=True)
    assert not qa.request_allowed("https://external.example/a", "directory")


def test_cookie_must_remain_exact_unique_and_origin_bound():
    cookie = {"name": "epc_device_id", "value": TOKEN, "domain": "msapo-generator.onrender.com", "path": "/"}
    qa.validate_identity([cookie], TOKEN)
    for cookies in ([], [cookie, cookie], [{**cookie, "value": "f" * 32}],
                    [{**cookie, "domain": "other.example"}], [{**cookie, "path": "/other"}]):
        with pytest.raises(qa.SafetyStop):
            qa.validate_identity(cookies, TOKEN)


def test_guard_failure_never_executes_mutation(tmp_path):
    journey = qa.Journey(None, None, TOKEN, qa.Config(SHA), tmp_path)
    journey.guard = Mock(side_effect=qa.SafetyStop("blocked"))
    mutation = Mock()
    with pytest.raises(qa.SafetyStop):
        journey.action("save", mutation)
    mutation.assert_not_called()
    assert journey.events == []


def test_post_action_failure_is_uncertain_not_success_or_retried(tmp_path):
    journey = qa.Journey(None, None, TOKEN, qa.Config(SHA), tmp_path)
    journey.guard = Mock(side_effect=[None, qa.SafetyStop("changed")])
    mutation = Mock()
    with pytest.raises(qa.SafetyStop):
        journey.action("save", mutation)
    mutation.assert_called_once()
    assert journey.events == [{"action": "save", "status": "attempted"}]


@pytest.mark.parametrize("drift", ["blocked", "route", "cookie"])
def test_drift_during_assertion_wait_stops_before_action(tmp_path, monkeypatch, drift):
    import sys
    from types import ModuleType
    page, context = Mock(), Mock()
    page.url = qa.Config(SHA).address("directory")
    cookie = {"name": "epc_device_id", "value": TOKEN, "domain": "msapo-generator.onrender.com", "path": "/"}
    context.cookies.return_value = [cookie]
    journey = qa.Journey(page, context, TOKEN, qa.Config(SHA), tmp_path)
    def during_wait():
        if drift == "blocked":
            journey.blocked.append("unexpected")
        elif drift == "route":
            page.url = qa.ORIGIN + "/?workflow=monthly"
        else:
            context.cookies.return_value = [{**cookie, "value": "f" * 32}]
    assertions = Mock()
    assertions.to_be_visible.side_effect = during_wait
    fake = ModuleType("playwright.sync_api")
    fake.expect = Mock(return_value=assertions)
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    mutation = Mock()
    with pytest.raises(qa.SafetyStop):
        journey.action("save", mutation)
    mutation.assert_not_called()
    assert journey.events == []


# Match the native Streamlit JavaScript export, not pandas/Python CSV casing.
HISTORY = f"Site,Aliases,Active,Contacts\r\n{qa.SITE},,true,1\r\n".encode()
CONTACTS = f"Site,Role,Name,Phone,Email\n{qa.SITE},Facility Director,{qa.PERSON},{qa.PHONE},{qa.EMAIL}\n".encode()


def test_downloaded_rows_must_match_independent_expected_values():
    qa.verify_history(HISTORY)
    qa.verify_contacts(CONTACTS)
    for verifier, raw in ((qa.verify_history, HISTORY), (qa.verify_contacts, CONTACTS)):
        for wrong in (raw.replace(qa.SITE.encode(), b"Synthetic Other Site"), raw + raw.splitlines()[-1] + b"\n",
                      b"Only heading\n", b"x" * 65537):
            with pytest.raises(qa.SafetyStop):
                verifier(wrong)


@pytest.mark.parametrize("raw", [b"a,a\n1,2\n", b"a,b\n1\n", b"a\n1,2\n", b",a\nprivate,1\n"])
def test_csv_never_hides_duplicate_columns_or_unexpected_payload(raw):
    with pytest.raises(qa.SafetyStop):
        qa.csv_rows(raw)


def test_generated_workbook_and_real_save_stay_in_temporary_qa_scope(tmp_path, monkeypatch):
    from app import monthly_report_directory as directory
    from app import monthly_report_library as library
    from app import monthly_report_testing as testing
    from app.monthly_report_directory_retention import expire_quietly
    from app.monthly_report_objects import object_path
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    control = tmp_path / "monthly_reports" / "control.txt"
    control.parent.mkdir()
    control.write_bytes(b"synthetic outside-namespace control")
    raw = qa.workbook()
    digest = sha256(raw).hexdigest()
    assert len(raw) < 10000
    with testing.isolated(TOKEN):
        parsed = directory.inspect_workbook(raw)
        assert [(s.name, s.hidden, s.summary) for s in parsed.sheets] == [
            (qa.SHEET, False, False), ("Hidden excluded", True, False),
            ("Inactive excluded", False, False), ("Index", False, True)]
        sheet = parsed.sheets[0]
        sites = directory.matrix_sites(parsed, sheet, *directory.suggest_matrix(sheet))
        assert len(sites) == 1 and sites[0].title == qa.SITE
        assert len(sites[0].contacts) == 1 and sites[0].contacts[0].name == qa.PERSON
        root = library._root()
        assert not root.is_relative_to(control.parent)
        link = root / "directory_sources" / (digest + ".xlsx")
        assert not link.exists()
        state = directory.save_directory("Synthetic Retention 291 test", sites, expected_revision=0,
            actor=qa.ACTOR, confirmed=True, raw=raw, source_sha256=digest, source_sheet=qa.SHEET)
        assert state.revision == 1 and link.read_bytes() == raw
        assert object_path(link).read_bytes() == raw
        history = {p.relative_to(root): p.read_bytes() for p in (root / "directory").rglob("*") if p.is_file()}
        expire_quietly(force=True)
        assert link.read_bytes() == raw
        assert directory.load_directory("Synthetic Retention 291 test", 1) == state
        assert history == {p.relative_to(root): p.read_bytes() for p in (root / "directory").rglob("*") if p.is_file()}
    assert control.read_bytes() == b"synthetic outside-namespace control"
    assert list(control.parent.iterdir()) == [control]


def test_workflow_has_no_new_trigger_and_is_explicitly_disabled_by_default():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / ".github/workflows/monthly-live-qa.yml").read_text()
    assert "workflow_dispatch:" not in source and "schedule:" not in source
    assert "permissions:\n  contents: read" in source
    assert "group: monthly-isolated-live-production\n  cancel-in-progress: false" in source
    assert "if: steps.still-current.outputs.run == 'true' && vars.MONTHLY_QA_DIRECTORY_ACCEPTANCE == 'synthetic-only-v1'" in source
    assert source.count("run: python -m scripts.qa_directory_retention_live") == 1
