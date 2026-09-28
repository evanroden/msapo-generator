"""Expense approval routing: account director on To, the filer's manager on Cc.

Guidance received 2026-09-28: whenever anyone files an expense report, it goes
to the ENFRA DIRECTOR of their contract -- not the contract administrator, who
is what the tool used to address -- with the filer's own MANAGER copied.

That splits routing into two different kinds of data:

* The director is per CONTRACT, so it is deployment configuration
  (EXPENSE_ACCOUNT_DIRECTORS_JSON) and outranks anything a device remembers --
  otherwise a returning filer keeps the administrator they used last time.
* The manager is per EMPLOYEE, so it is entered in the form and remembered on
  the filer's device like their employee number.

Every approver remembered before this change is an administrator. Those rows are
migrated in place but never offered or seeded as the director.

Real names and addresses live in the deployment environment only. This
repository is public; every fixture here uses example.invalid.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from decimal import Decimal
from email import message_from_bytes
from pathlib import Path

import pytest
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

import app.config as config
import app.expense_ui as expense_ui
import app.memory as memory
from app import contracts
from app.eml_builder import build_mailto_url
from app.expense_report import (
    ExpensePackage,
    ExpenseReportDetails,
    approval_cc,
    is_same_person,
    validate_expense_report,
)

ROOT = Path(__file__).resolve().parents[1]
RRH = "Rochester Regional Health"
TOKEN = hashlib.sha256(RRH.encode("utf-8")).hexdigest()[:10]

DIRECTOR_NAME = "Test Director"
DIRECTOR_EMAIL = "director@example.invalid"
MANAGER_NAME = "Chris Example"
MANAGER_EMAIL = "christop.example@example.invalid"  # truncated first name, as issued


def _details(**changes) -> ExpenseReportDetails:
    values = {
        "account": RRH,
        "employee_name": "Test Employee",
        "employee_number": "TEST-1001",
        "employee_home_bu": "695",
        "report_date": date(2026, 9, 28),
        "approver_name": DIRECTOR_NAME,
        "approver_email": DIRECTOR_EMAIL,
        "mail_destination": "home",
        "satellite_office": "",
        "employee_signature_confirmed": True,
        "manager_name": MANAGER_NAME,
        "manager_email": MANAGER_EMAIL,
    }
    values.update(changes)
    return ExpenseReportDetails(**values)


def _package() -> ExpensePackage:
    return ExpensePackage(
        basename="Test_Expense_Report",
        workbook_bytes=b"PK",
        pdf_bytes=b"%PDF-1.7 synthetic",
        total=Decimal("31.25"),
        receipt_count=1,
    )


# --- the per-contract director map --------------------------------------------


def test_the_director_map_is_keyed_by_account_forgiving_case_and_spacing():
    directors, problems = config._parse_account_directors(
        json.dumps({"Tulane": {"name": " Test  Director ", "email": DIRECTOR_EMAIL}})
    )
    assert problems == []
    assert directors[config._account_match_key("  tulane ")] == (
        "Test Director",
        DIRECTOR_EMAIL,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("{not json", "not valid JSON"),
        ('["Tulane"]', "must be a JSON object"),
        ('{"Tulane": {"name": "Test Director"}}', "'Tulane' needs a name and a valid email"),
        ('{"Tulane": {"name": "", "email": "d@example.invalid"}}', "needs a name"),
        ('{"Tulane": "d@example.invalid"}', "needs a name"),
    ],
)
def test_a_malformed_director_map_is_reported_never_raised(raw, expected):
    directors, problems = config._parse_account_directors(raw)
    assert directors == {}
    assert any(expected in problem for problem in problems)


def test_an_unknown_account_key_is_reported_as_a_likely_typo(monkeypatch):
    directors, _ = config._parse_account_directors(
        json.dumps(
            {
                "Rochester Regional": {"name": "A B", "email": "a@example.invalid"},
                "Tulane": {"name": "C D", "email": "c@example.invalid"},
            }
        )
    )
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTORS", directors)
    monkeypatch.setattr(config, "_ACCOUNT_DIRECTOR_PROBLEMS", [])
    problems = config.director_config_problems(contracts.contract_names())
    assert problems == [
        "EXPENSE_ACCOUNT_DIRECTORS_JSON names an account the tool does not "
        "know: 'rochester regional'."
    ]


def test_the_retired_administrator_variables_are_no_longer_read():
    """A value left behind in a deployment must not keep routing reports to
    the contract administrator."""
    source = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    assert 'getenv("RRH_APPROVER' not in source
    assert not hasattr(config, "RRH_APPROVER_NAME")


# --- who counts as the filer ------------------------------------------------------


@pytest.mark.parametrize(
    "employee",
    [
        "Chris Example",
        "CHRIS EXAMPLE",
        "Chris A. Example",  # middle initial ignored
        "Christopher Example",  # matched through the mailbox's "christop"
        "christopher j example",
    ],
)
def test_a_manager_filing_is_recognised_as_the_filer(employee):
    assert is_same_person(employee, MANAGER_NAME, MANAGER_EMAIL)


@pytest.mark.parametrize(
    "employee",
    [
        "Christina Example",  # "chris" is a prefix of her name; "christop" is not
        "Christian Example",
        "Chris Example-Smith",
        "Test Employee",
        "Example",
        "",
    ],
)
def test_a_similar_name_is_not_mistaken_for_the_manager(employee):
    """The costly direction: a false match silently drops the Cc."""
    assert not is_same_person(employee, MANAGER_NAME, MANAGER_EMAIL)


# --- the Cc policy -------------------------------------------------------------


def test_the_filers_manager_is_copied():
    assert approval_cc(_details()) == (MANAGER_NAME, MANAGER_EMAIL)


def test_nobody_is_copied_on_their_own_report():
    assert approval_cc(_details(employee_name="Christopher Example")) is None


def test_a_manager_who_is_also_the_director_is_not_copied_twice():
    details = _details(manager_email=DIRECTOR_EMAIL.upper())
    assert approval_cc(details) is None


@pytest.mark.parametrize("entered", ["", "   ", "not-an-address", "a b@c.d"])
def test_a_missing_or_malformed_manager_address_adds_no_cc(entered):
    assert approval_cc(_details(manager_email=entered)) is None


def test_the_manager_is_required_and_checked():
    problems = validate_expense_report(
        _details(manager_name="", manager_email=""), [], mileage_items=[]
    )
    assert "enter your manager's name" in problems
    assert "enter your manager's email" in problems

    problems = validate_expense_report(
        _details(manager_email="not-an-address"), [], mileage_items=[]
    )
    assert "enter a valid manager email" in problems


def test_validation_names_the_director_not_the_administrator():
    problems = validate_expense_report(
        _details(approver_name="", approver_email=""), [], mileage_items=[]
    )
    assert "enter the account director's name" in problems
    assert not any("administrator" in problem for problem in problems)


# --- every delivery route carries it -------------------------------------------


def test_the_outlook_draft_goes_to_the_director_with_the_manager_on_cc():
    message = message_from_bytes(expense_ui._build_expense_eml(_details(), _package()))
    assert message["To"] == DIRECTOR_EMAIL
    assert message["Cc"] == MANAGER_EMAIL


def test_the_outlook_draft_has_no_cc_on_the_managers_own_report():
    details = _details(employee_name="Chris Example")
    message = message_from_bytes(expense_ui._build_expense_eml(details, _package()))
    assert message["To"] == DIRECTOR_EMAIL
    assert message["Cc"] is None, "an empty or self Cc header was written"


def test_every_account_copies_the_manager_not_only_rrh():
    details = _details(account="Tulane")
    message = message_from_bytes(expense_ui._build_expense_eml(details, _package()))
    assert message["Cc"] == MANAGER_EMAIL


def test_the_attachment_free_mailto_carries_the_cc():
    url = build_mailto_url(to=DIRECTOR_EMAIL, subject="s", body="b", cc=MANAGER_EMAIL)
    assert url.endswith(f"&cc={MANAGER_EMAIL}")
    assert "&cc=" not in build_mailto_url(to=DIRECTOR_EMAIL, subject="s", body="b")


def test_a_cc_cannot_inject_another_mailto_field():
    """Encoded like the recipient, so "&subject=" inside a bad address stays
    part of the address instead of rewriting the message."""
    url = build_mailto_url(
        to=DIRECTOR_EMAIL, subject="s", body="b", cc="x@y.z&subject=changed"
    )
    assert "subject=changed" not in url


def test_the_iphone_share_payload_carries_the_cc():
    payload = expense_ui._ios_mail_share_payload(
        to=DIRECTOR_EMAIL,
        cc=MANAGER_EMAIL,
        subject="s",
        body="b",
        attachments=[("expense.pdf", b"%PDF-1.7")],
    )
    assert payload["to"] == DIRECTOR_EMAIL
    assert payload["cc"] == MANAGER_EMAIL


def test_the_iphone_share_sheet_tells_the_employee_to_add_the_cc():
    """Web Share cannot set recipients and the clipboard holds one string, so
    the Cc is spelled out in the status line. That line is longer, so the frame
    must size to its content -- a fixed 112px iframe clips the bottom of the
    instruction with no error."""
    source = (expense_ui._IOS_MAIL_SHARE_FRONTEND / "index.html").read_text(
        encoding="utf-8"
    )
    assert "current.cc" in source
    assert "to Cc" in source
    assert "document.body.scrollHeight" in source
    assert "{height: 112}" not in source, "the frame height is fixed again"
    assert "overflow-wrap: anywhere" in source
    # Executable lines only: a comment in the component warns AGAINST innerHTML
    # by name, and deleting that warning to satisfy a test would be backwards.
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )
    assert "innerHTML" not in code


# --- the operator can see the routing before sending ---------------------------


def test_the_send_step_names_director_and_manager():
    caption, warning = expense_ui._approval_routing_note(_details())
    assert f"{DIRECTOR_NAME} (account director)" in caption
    assert f"{MANAGER_NAME} (your manager) on Cc" in caption
    assert warning == ""


def test_the_send_step_explains_a_deliberately_missing_cc():
    caption, _ = expense_ui._approval_routing_note(
        _details(employee_name="Christopher Example")
    )
    assert "No Cc" in caption
    caption, _ = expense_ui._approval_routing_note(
        _details(manager_email=DIRECTOR_EMAIL)
    )
    assert "also your manager" in caption


# --- device memory: migrated, and administrators never come back --------------

_LEGACY_PROFILE_TABLE = """
CREATE TABLE device_expense_profiles (
    device_hash TEXT NOT NULL, account_key TEXT NOT NULL,
    employee_name TEXT NOT NULL, employee_number TEXT NOT NULL,
    employee_home_bu TEXT NOT NULL, approver_name TEXT NOT NULL,
    approver_email TEXT NOT NULL, mail_destination TEXT NOT NULL,
    satellite_office TEXT NOT NULL, allocation_kind TEXT NOT NULL,
    job_number TEXT NOT NULL, service_center TEXT NOT NULL,
    account_cost_type TEXT NOT NULL, cost_code_or_wo_type TEXT NOT NULL,
    work_order_number TEXT NOT NULL, company_number TEXT NOT NULL,
    department_number TEXT NOT NULL, ou_number TEXT NOT NULL,
    gl_account_number TEXT NOT NULL, last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, account_key)
);
CREATE TABLE expense_approvers (
    account_key TEXT NOT NULL, approver_key TEXT NOT NULL,
    display_name TEXT NOT NULL, email TEXT NOT NULL,
    use_count INTEGER NOT NULL DEFAULT 0, last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account_key, approver_key, email)
);
CREATE TABLE expense_approver_events (
    account_key TEXT NOT NULL, context_id TEXT NOT NULL,
    approver_key TEXT NOT NULL, email TEXT NOT NULL,
    recorded_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account_key, context_id)
);
"""


@pytest.fixture
def legacy_database(tmp_path, monkeypatch):
    """A deployed database from before 2026-09-28, holding one administrator."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "_INITIALIZED_DATABASES", {})
    database = tmp_path / "epc_memory.db"
    device = memory._device_hash("browser-a")
    with sqlite3.connect(database) as connection:
        connection.executescript(_LEGACY_PROFILE_TABLE)
        connection.execute(
            "INSERT INTO device_expense_profiles VALUES "
            "(?,?,'Test Employee','TEST-1001','695','Old Administrator',"
            "'admin@example.invalid','home','','job','','','01AMA','5490',"
            "'','','','','',1)",
            (device, "rochester regional health"),
        )
        connection.execute(
            "INSERT INTO expense_approvers VALUES "
            "('rochester regional health','old administrator',"
            "'Old Administrator','admin@example.invalid',5,1)"
        )
    return database


def test_an_existing_profile_is_still_recalled_after_the_migration(legacy_database):
    """The silent failure this guards: a SELECT naming a column the deployed
    table lacks returns {} and every device forgets every profile."""
    profile = memory.remembered_expense_profile("browser-a", RRH)
    assert profile["employee_number"] == "TEST-1001"
    assert profile["manager_name"] == ""
    assert profile["approver_role"] == "", "a legacy administrator looked like a director"
    with sqlite3.connect(legacy_database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(device_expense_profiles)")
        }
    assert {"manager_name", "manager_email", "approver_role"} <= columns


def test_a_remembered_administrator_is_never_offered_as_the_director(legacy_database):
    assert memory.expense_approvers(RRH) == []
    assert memory.record_expense_approver(
        account=RRH,
        approver_name=DIRECTOR_NAME,
        approver_email=DIRECTOR_EMAIL,
        context_id="report-1",
    ) == 1
    assert memory.expense_approvers(RRH) == [(DIRECTOR_NAME, DIRECTOR_EMAIL)]


def test_the_manager_and_director_marker_round_trip(legacy_database):
    assert memory.record_expense_profile(
        device_token="browser-a",
        account=RRH,
        values={
            "employee_name": "Test Employee",
            "approver_name": DIRECTOR_NAME,
            "approver_email": DIRECTOR_EMAIL,
            "approver_role": "director",
            "manager_name": MANAGER_NAME,
            "manager_email": MANAGER_EMAIL,
        },
    )
    profile = memory.remembered_expense_profile("browser-a", RRH)
    assert (profile["manager_name"], profile["manager_email"]) == (
        MANAGER_NAME,
        MANAGER_EMAIL,
    )
    assert profile["approver_role"] == "director"


def test_an_implausible_manager_address_is_not_remembered(legacy_database):
    assert not memory.record_expense_profile(
        device_token="browser-a",
        account=RRH,
        values={"employee_name": "Test Employee", "manager_email": "not-an-address"},
    )


def test_the_migration_is_idempotent(legacy_database):
    memory.remembered_expense_profile("browser-a", RRH)
    memory._INITIALIZED_DATABASES.clear()
    assert memory.remembered_expense_profile("browser-a", RRH)["employee_number"] == (
        "TEST-1001"
    )


# --- the form: configured director wins, administrators are not seeded ---------


def _expense_app(monkeypatch, *, remembered: dict, director) -> AppTest:
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(expense_ui, "account_director", lambda _account: director)
    monkeypatch.setattr(expense_ui, "director_config_problems", lambda _known: [])
    monkeypatch.setattr(
        expense_ui, "remembered_expense_profile", lambda *_args: dict(remembered)
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    return app


def _field(app: AppTest, label: str):
    for field in [*app.selectbox, *app.text_input]:
        if field.label == label:
            return field
    raise AssertionError(f"{label} not rendered")


def _director_fields(app: AppTest) -> tuple[str, str]:
    return (
        _field(app, "ENFRA account director *").value or "",
        _field(app, "ENFRA account director email *").value or "",
    )


LEGACY = {
    "approver_name": "Old Administrator",
    "approver_email": "admin@example.invalid",
    "approver_role": "",
    "manager_name": "",
    "manager_email": "",
}
CONFIRMED = {
    "approver_name": "Remembered Director",
    "approver_email": "remembered.director@example.invalid",
    "approver_role": "director",
    "manager_name": MANAGER_NAME,
    "manager_email": MANAGER_EMAIL,
}


def test_the_configured_director_outranks_anything_remembered(monkeypatch):
    app = _expense_app(
        monkeypatch, remembered=CONFIRMED, director=(DIRECTOR_NAME, DIRECTOR_EMAIL)
    )
    assert not app.exception
    assert _director_fields(app) == (DIRECTOR_NAME, DIRECTOR_EMAIL)
    assert any("routing setup" in caption.value for caption in app.caption)


def test_a_remembered_administrator_is_not_seeded_as_the_director(monkeypatch):
    """The reason the change would not have taken effect for anyone who has
    filed before: their device remembers the administrator."""
    app = _expense_app(monkeypatch, remembered=LEGACY, director=None)
    assert not app.exception
    assert _director_fields(app) == ("", "")
    assert any("not the contract administrator" in c.value for c in app.caption)


def test_a_remembered_director_is_seeded_when_none_is_configured(monkeypatch):
    app = _expense_app(monkeypatch, remembered=CONFIRMED, director=None)
    assert _director_fields(app) == (
        "Remembered Director",
        "remembered.director@example.invalid",
    )


def test_the_manager_is_recalled_from_this_device(monkeypatch):
    app = _expense_app(
        monkeypatch, remembered=CONFIRMED, director=(DIRECTOR_NAME, DIRECTOR_EMAIL)
    )
    assert _field(app, "Your manager's name (Cc) *").value == MANAGER_NAME
    assert _field(app, "Your manager's email (Cc) *").value == MANAGER_EMAIL


def test_an_empty_manager_is_highlighted_as_needing_a_value(monkeypatch):
    app = _expense_app(
        monkeypatch, remembered={}, director=(DIRECTOR_NAME, DIRECTOR_EMAIL)
    )
    styles = "\n".join(
        str(block.value) for block in app.markdown if "st-key-" in str(block.value)
    )
    assert f"st-key-expense_manager_name_{TOKEN}" in styles
    assert f"st-key-expense_manager_email_{TOKEN}" in styles
