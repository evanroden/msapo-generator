"""RRH expense approval routing: approver on To, asset manager on Cc.

Account guidance received 2026-09-28: every RRH report goes directly to the
configured approver, with the account's asset manager copied "for approval" --
and, from the product owner, the asset manager is not copied on their OWN
report when they file through the tool.

Three things had to be true for that to actually happen, and the first was not:

1. A changed approver has to REACH people. The seed used to prefer the
   approver a device remembered over the configured one, so a new configured
   approver only reached devices that had never filed. Everyone who had filed
   before -- including the product owner -- kept defaulting to the previous
   approver, silently.
2. The Cc has to travel on every delivery route: the Outlook .eml draft, the
   iPhone/iPad share sheet, and the attachment-free mailto fallback.
3. The Cc has to drop out when the filer IS the Cc person, without dropping out
   for someone who merely shares a first-name prefix.

Real names and addresses live in the deployment environment only. This
repository is public; every fixture here uses example.invalid.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from email import message_from_bytes
from pathlib import Path

import pytest
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

import app.expense_ui as expense_ui
from app.eml_builder import build_mailto_url
from app.expense_report import (
    ExpensePackage,
    ExpenseReportDetails,
    approval_cc,
    is_same_person,
)

ROOT = Path(__file__).resolve().parents[1]
RRH = "Rochester Regional Health"

APPROVER_NAME = "Test Approver"
APPROVER_EMAIL = "approver@example.invalid"
CC_NAME = "Chris Example"
CC_EMAIL = "christop.example@example.invalid"  # truncated first name, as issued


def _details(**changes) -> ExpenseReportDetails:
    values = {
        "account": RRH,
        "employee_name": "Test Employee",
        "employee_number": "TEST-1001",
        "employee_home_bu": "695",
        "report_date": date(2026, 9, 28),
        "approver_name": APPROVER_NAME,
        "approver_email": APPROVER_EMAIL,
        "mail_destination": "home",
        "satellite_office": "",
        "employee_signature_confirmed": True,
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


@pytest.fixture
def cc_configured(monkeypatch):
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_CC_NAME", CC_NAME)
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_CC_EMAIL", CC_EMAIL)


# --- who counts as the Cc person ------------------------------------------


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
def test_the_cc_person_is_recognised_as_the_filer(employee):
    assert is_same_person(employee, CC_NAME, CC_EMAIL)


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
def test_a_similar_name_is_not_mistaken_for_the_cc_person(employee):
    """The costly direction. A false match silently drops the Cc from SOMEONE
    ELSE'S report; a missed match only copies the filer on their own."""
    assert not is_same_person(employee, CC_NAME, CC_EMAIL)


# --- the Cc policy ----------------------------------------------------------


def test_another_employees_report_copies_the_cc_person():
    assert approval_cc(_details(), cc_name=CC_NAME, cc_email=CC_EMAIL) == (
        CC_NAME,
        CC_EMAIL,
    )


def test_the_cc_person_is_not_copied_on_their_own_report():
    details = _details(employee_name="Christopher Example")
    assert approval_cc(details, cc_name=CC_NAME, cc_email=CC_EMAIL) is None


def test_the_cc_is_dropped_when_that_person_is_already_the_approver():
    details = _details(approver_name=CC_NAME, approver_email=CC_EMAIL.upper())
    assert approval_cc(details, cc_name=CC_NAME, cc_email=CC_EMAIL) is None


@pytest.mark.parametrize("configured", ["", "   ", "not-an-address", "a b@c.d"])
def test_a_missing_or_malformed_cc_address_adds_no_cc(configured):
    assert approval_cc(_details(), cc_name=CC_NAME, cc_email=configured) is None


# --- every delivery route carries it ----------------------------------------


def test_the_outlook_draft_carries_the_cc(cc_configured):
    message = message_from_bytes(expense_ui._build_expense_eml(_details(), _package()))
    assert message["To"] == APPROVER_EMAIL
    assert message["Cc"] == CC_EMAIL


def test_the_outlook_draft_has_no_cc_on_the_cc_persons_own_report(cc_configured):
    details = _details(employee_name="Chris Example")
    message = message_from_bytes(expense_ui._build_expense_eml(details, _package()))
    assert message["To"] == APPROVER_EMAIL
    assert message["Cc"] is None, "an empty or self Cc header was written"


def test_a_non_rrh_account_never_gets_the_rrh_cc(cc_configured):
    details = _details(account="Tulane")
    message = message_from_bytes(expense_ui._build_expense_eml(details, _package()))
    assert message["Cc"] is None


def test_the_attachment_free_mailto_carries_the_cc():
    url = build_mailto_url(to=APPROVER_EMAIL, subject="s", body="b", cc=CC_EMAIL)
    assert url.endswith(f"&cc={CC_EMAIL}")
    assert "&cc=" not in build_mailto_url(to=APPROVER_EMAIL, subject="s", body="b")


def test_a_cc_cannot_inject_another_mailto_field():
    """Encoded like the recipient, so "&subject=" inside a bad address stays
    part of the address instead of rewriting the message."""
    url = build_mailto_url(
        to=APPROVER_EMAIL, subject="s", body="b", cc="x@y.z&subject=changed"
    )
    assert "subject=changed" not in url


def test_the_iphone_share_payload_carries_the_cc():
    payload = expense_ui._ios_mail_share_payload(
        to=APPROVER_EMAIL,
        cc=CC_EMAIL,
        subject="s",
        body="b",
        attachments=[("expense.pdf", b"%PDF-1.7")],
    )
    assert payload["to"] == APPROVER_EMAIL
    assert payload["cc"] == CC_EMAIL


def test_the_iphone_share_sheet_tells_the_employee_to_add_the_cc():
    """Web Share cannot set recipients and the clipboard holds one string, so
    the Cc is spelled out in the status line. That line is now longer, so the
    frame must size to its content -- a fixed 112px iframe clips the bottom of
    the instruction with no error."""
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


# --- the operator can see the routing before sending ------------------------


def test_the_send_step_names_the_cc(cc_configured):
    caption, warning = expense_ui._approval_routing_note(_details())
    assert "Test Approver" in caption
    assert CC_NAME in caption
    assert warning == ""


def test_the_send_step_explains_a_deliberately_missing_cc(cc_configured):
    caption, _ = expense_ui._approval_routing_note(
        _details(employee_name="Christopher Example")
    )
    assert "No Cc" in caption


def test_a_broken_cc_configuration_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_CC_NAME", CC_NAME)
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_CC_EMAIL", "christop.example")
    _, warning = expense_ui._approval_routing_note(_details())
    assert "RRH_APPROVER_CC_EMAIL" in warning


def test_no_cc_configured_means_no_cc_mentioned(monkeypatch):
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_CC_EMAIL", "")
    caption, warning = expense_ui._approval_routing_note(_details())
    assert "Cc" not in caption
    assert warning == ""


# --- the configured approver actually reaches returning users ---------------


def _expense_app(monkeypatch, *, remembered: dict, name: str, email: str) -> AppTest:
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_NAME", name)
    monkeypatch.setattr(expense_ui, "RRH_APPROVER_EMAIL", email)
    monkeypatch.setattr(
        expense_ui, "remembered_expense_profile", lambda *_args: dict(remembered)
    )
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    return app


def _approver_fields(app: AppTest) -> tuple[str, str]:
    name = next(
        field
        for field in app.selectbox
        if field.label == "Contract administrator / approver name *"
    )
    email = next(
        field
        for field in app.text_input
        if field.label == "Contract administrator / approver email *"
    )
    return name.value, email.value


PREVIOUS = {"approver_name": "Previous Approver", "approver_email": "prev@example.invalid"}


def test_a_configured_rrh_approver_outranks_the_remembered_one(monkeypatch):
    """The reason the guidance would not have taken effect. A device that filed
    before remembered its last approver, and that memory used to win."""
    app = _expense_app(
        monkeypatch, remembered=PREVIOUS, name=APPROVER_NAME, email=APPROVER_EMAIL
    )
    assert not app.exception
    assert _approver_fields(app) == (APPROVER_NAME, APPROVER_EMAIL)


def test_incomplete_configuration_keeps_the_remembered_approver(monkeypatch):
    """A half-set deployment must not mix a configured name with a remembered
    address -- that would address one person's report to another."""
    app = _expense_app(monkeypatch, remembered=PREVIOUS, name=APPROVER_NAME, email="")
    assert _approver_fields(app) == ("Previous Approver", "prev@example.invalid")


def test_the_remembered_approver_still_offered_as_a_choice(monkeypatch):
    """Configuration sets the default; it does not take the choice away."""
    monkeypatch.setattr(
        expense_ui,
        "expense_approvers",
        lambda account: [("Previous Approver", "prev@example.invalid")],
    )
    app = _expense_app(
        monkeypatch, remembered=PREVIOUS, name=APPROVER_NAME, email=APPROVER_EMAIL
    )
    selector = next(
        field
        for field in app.selectbox
        if field.label == "Contract administrator / approver name *"
    )
    assert "Previous Approver" in selector.options
