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


def radio_controls(monkeypatch, tmp_path, *, option_count=1, group_count=1, input_count=1,
                   visible=True, enabled=True, settles=True):
    """Model the native artifact's covered input and visible associated option."""
    import sys
    from types import ModuleType
    page, group, options, option, radio = (Mock() for _ in range(5))
    checked = []
    page.get_by_role.side_effect = lambda role, **kwargs: group if role == "radiogroup" else radio
    option.get_by_role.return_value = radio
    group.get_by_test_id.return_value = options
    options.filter.return_value = option
    radio.check.side_effect = TimeoutError("Styled radio option intercepts the hidden input")
    option.click.side_effect = lambda: checked.append(True) if settles else None
    class Assertions:
        def __init__(self, target):
            self.target = target
        def to_have_count(self, count):
            counts = {id(group): group_count, id(option): option_count, id(radio): input_count}
            assert counts[id(self.target)] == count, "Radio target is ambiguous or missing"
        def to_be_visible(self):
            assert self.target is option and visible, "Radio option is hidden"
        def to_be_enabled(self):
            assert self.target is radio and enabled, "Radio is disabled"
        def to_be_checked(self):
            assert self.target is radio and checked, "Native label press did not select the radio"
    fake = ModuleType("playwright.sync_api")
    fake.expect = Assertions
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    item = qa.Journey(page, None, TOKEN, qa.Config(SHA), tmp_path)
    item.guard = Mock()
    return item, group, options, option, radio


def test_radio_uses_associated_native_option_not_covered_input(monkeypatch, tmp_path):
    item, group, options, option, radio = radio_controls(monkeypatch, tmp_path)
    item.radio("Review saved directory")
    item.page.get_by_role.assert_any_call("radiogroup", name="Directory task", exact=True)
    option.get_by_role.assert_called_once_with("radio", name="Review saved directory", exact=True)
    group.get_by_role.assert_not_called()  # The has locator must not retain an ancestor group.
    group.get_by_test_id.assert_called_once_with("stRadioOption")
    options.filter.assert_called_once_with(has=radio)
    option.click.assert_called_once_with()  # Native actionable pointer, no force/JS/keyboard fallback.
    radio.check.assert_not_called()
    assert item.guard.call_count == 3  # Before operation, after readiness waits, after native selection.
    assert item.events == [{"action": "Review saved directory", "status": "completed"}]


@pytest.mark.parametrize("options", [{"option_count": 0}, {"option_count": 2}, {"enabled": False},
                                     {"group_count": 2}, {"input_count": 2}, {"visible": False}])
def test_radio_requires_unique_visible_enabled_option(monkeypatch, tmp_path, options):
    item, _, _, option, radio = radio_controls(monkeypatch, tmp_path, **options)
    with pytest.raises(AssertionError):
        item.radio("Review saved directory")
    option.click.assert_not_called()
    radio.check.assert_not_called()
    assert item.events == [{"action": "Review saved directory", "status": "attempted"}]


def test_radio_rechecks_guard_after_waits_before_native_press(monkeypatch, tmp_path):
    item, _, _, option, radio = radio_controls(monkeypatch, tmp_path)
    item.guard.side_effect = [None, qa.SafetyStop("Synthetic route drift")]
    with pytest.raises(qa.SafetyStop):
        item.radio("Review saved directory")
    option.click.assert_not_called()
    radio.check.assert_not_called()
    assert item.events == [{"action": "Review saved directory", "status": "attempted"}]


def test_radio_unsettled_press_is_not_retried_or_successful(monkeypatch, tmp_path):
    item, _, _, option, radio = radio_controls(monkeypatch, tmp_path, settles=False)
    with pytest.raises(AssertionError, match="did not select"):
        item.radio("Review saved directory")
    option.click.assert_called_once_with()
    radio.check.assert_not_called()
    assert item.events == [{"action": "Review saved directory", "status": "attempted"}]


class WorksheetGateReached(Exception):
    """Stop the unit model before the next native mutation."""


def worksheet_gate(monkeypatch, tmp_path, *, value=qa.SHEET, count=1, visible=True):
    """Exercise the real run's read-only worksheet gate against native UI shape."""
    import sys
    from types import ModuleType
    page, wrapper, combo = Mock(), Mock(), Mock()
    page.get_by_test_id.side_effect = lambda name: wrapper if name == "stSelectbox" else Mock()
    wrapper.filter.return_value = wrapper
    page.get_by_role.side_effect = lambda role, **kwargs: combo if (
        role == "combobox" and kwargs.get("name") == "Contract worksheet") else Mock()
    class Assertions:
        def __init__(self, target):
            self.target = target
        def to_have_count(self, expected):
            if self.target is combo:
                assert count == expected, "Worksheet target is missing or ambiguous"
        def to_be_visible(self):
            if self.target is combo:
                assert visible, "Worksheet is not visible"
        def to_contain_text(self, expected):
            assert self.target is wrapper and expected in "Contract worksheet", "Wrapper has label text, not input value"
        def to_have_value(self, expected):
            assert self.target is combo and value == expected, "Unexpected worksheet value"
    fake = ModuleType("playwright.sync_api")
    fake.expect = Assertions
    monkeypatch.setitem(sys.modules, "playwright", ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    item = qa.Journey(page, None, TOKEN, qa.Config(SHA), tmp_path)
    # This models only the assertion. It does not claim upload/browser execution.
    for method in ("guard", "radio", "snapshot", "action", "button"):
        setattr(item, method, Mock())
    def fill(label, value):
        if label == "Contract name":
            raise WorksheetGateReached()
    item.fill = Mock(side_effect=fill)
    return item, combo


def test_worksheet_asserts_native_input_value_not_wrapper_text(monkeypatch, tmp_path):
    item, combo = worksheet_gate(monkeypatch, tmp_path)
    with pytest.raises(WorksheetGateReached):
        item.run(b"synthetic", "Synthetic contract")
    item.page.get_by_role.assert_any_call("combobox", name="Contract worksheet", exact=True)
    combo.click.assert_not_called()
    combo.fill.assert_not_called()
    assert item.fill.call_args_list[-1].args == ("Contract name", "Synthetic contract")


@pytest.mark.parametrize("options", [
    {"value": ""}, {"value": "Synthetic Other Sites"}, {"value": qa.SHEET + " extra"},
    {"count": 0}, {"count": 2}, {"visible": False},
])
def test_wrong_or_unavailable_worksheet_stops_before_contract_mutation(monkeypatch, tmp_path, options):
    item, combo = worksheet_gate(monkeypatch, tmp_path, **options)
    with pytest.raises(AssertionError):
        item.run(b"synthetic", "Synthetic contract")
    item.fill.assert_called_once_with("Directory editor name", qa.ACTOR)
    combo.click.assert_not_called()
    combo.fill.assert_not_called()
