"""A first-time filer's name, guessed from the receipts -- low confidence.

Many receipts print the customer's name: a card slip's cardholder line, a hotel
folio's guest, an airline's passenger, a rental's renter. For someone using the
tool for the first time, that is a better start than an empty field -- but it is
a GUESS (a colleague may have paid; a card slip abbreviates), so:

* it only fills an EMPTY field, and only once -- a remembered or typed name
  always wins, and a name the filer changes stays changed;
* while it stands unchanged, the form says plainly that it was guessed and must
  be checked, and the details panel stays open.

Every name here is synthetic.
"""

from __future__ import annotations

from concurrent.futures import Future
from io import BytesIO
from pathlib import Path

import pytest
from dotenv import dotenv_values
from PIL import Image
from streamlit.testing.v1 import AppTest

import app.expense_ui as expense_ui
from app.receipt_analyzer import (
    RECEIPT_PROMPT,
    ReceiptAnalysis,
    guess_employee_name,
    normalize_receipt_response,
    person_name,
)

ROOT = Path(__file__).resolve().parents[1]
WARNING = "Guessed from a name printed on your receipts"


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("EXAMPLE/DANA", "Dana Example"),  # airline passenger
        ("Example, Dana J", "Dana J Example"),  # hotel folio
        ("DANA J EXAMPLE", "Dana J Example"),  # card slip
        ("Ms. Dana Example", "Dana Example"),
        ("dana example", "Dana Example"),
        ("O'Example, Sean", "Sean O'Example"),
        ("Dana Example-Smith", "Dana Example-Smith"),
    ],
)
def test_printed_names_are_normalised(printed, expected):
    assert person_name(printed) == expected


@pytest.mark.parametrize(
    "printed",
    [
        "",
        "Dana",  # one word is not enough to fill a full-name field
        "XXXXXXXXXXXX1234",
        "CARD MEMBER",
        "Valued Guest",
        "dana@example.invalid",
        "Table 12 Server Sam",
        "A B",  # initials only
        "One Two Three Four Five",
    ],
)
def test_anything_that_is_not_plainly_a_name_is_dropped(printed):
    assert person_name(printed) == ""


def test_the_merchants_own_name_is_not_taken_for_the_customer():
    assert person_name("Lakeside Grill", merchant="Lakeside Grill LLC") == ""


def test_the_model_is_asked_for_the_customer_never_the_staff():
    assert "customer_name" in RECEIPT_PROMPT
    assert "never the merchant, cashier, server" in RECEIPT_PROMPT


def test_the_response_carries_the_normalised_name():
    analysis = normalize_receipt_response(
        '{"merchant_name": "Test Hotel", "total_amount": "120.00", '
        '"customer_name": "EXAMPLE/DANA"}'
    )
    assert analysis.customer_name == "Dana Example"
    assert normalize_receipt_response('{"total_amount": "1.00"}').customer_name == ""


def test_the_name_most_receipts_agree_on_wins():
    analyses = [
        ReceiptAnalysis(customer_name="Pat Colleague"),
        ReceiptAnalysis(customer_name="Dana Example"),
        ReceiptAnalysis(),
        ReceiptAnalysis(customer_name="dana example"),
    ]
    assert guess_employee_name(analyses) == "Dana Example"
    assert guess_employee_name([ReceiptAnalysis()]) == ""


# --- the form ---------------------------------------------------------------


def _app(monkeypatch, *, customer_name: str, remembered: dict) -> AppTest:
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)

    def immediate(prepare, read):
        future = Future()
        future.set_result(read(prepare()))
        return future

    monkeypatch.setattr(expense_ui, "start_receipt", immediate)
    monkeypatch.setattr(expense_ui, "prepare_receipt_content", lambda *_: [])
    monkeypatch.setattr(
        expense_ui,
        "analyze_prepared_receipt",
        lambda *_args: ReceiptAnalysis(
            merchant_name="Test Hotel",
            total_amount="120.00",
            customer_name=customer_name,
        ),
    )
    monkeypatch.setattr(
        expense_ui, "remembered_expense_profile", lambda *_args: dict(remembered)
    )
    monkeypatch.setattr(
        expense_ui, "remembered_device_account_manager", lambda *_args: ""
    )
    image = Image.new("RGB", (120, 220), "white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.file_uploader[0].upload("folio.jpg", buffer.getvalue(), "image/jpeg").run()
    app.run()
    return app


def _name(app: AppTest):
    return next(field for field in app.text_input if field.label == "Employee name *")


def _warned(app: AppTest) -> bool:
    return any(WARNING in warning.value for warning in app.warning)


def test_a_first_time_filer_gets_the_receipt_name_with_a_check_this_warning(
    monkeypatch,
):
    app = _app(monkeypatch, customer_name="Dana Example", remembered={})
    assert not app.exception
    assert _name(app).value == "Dana Example"
    assert _warned(app)


def test_correcting_the_guess_clears_the_warning_and_it_never_comes_back(
    monkeypatch,
):
    app = _app(monkeypatch, customer_name="Dana Example", remembered={})
    _name(app).set_value("Dana Q. Example").run()
    assert not _warned(app)
    _name(app).set_value("").run()
    app.run()
    assert _name(app).value == "", "a cleared name was refilled from the receipts"


def test_a_remembered_name_is_never_replaced_by_a_receipt_guess(monkeypatch):
    app = _app(
        monkeypatch,
        customer_name="Pat Colleague",
        remembered={"employee_name": "Dana Example"},
    )
    assert _name(app).value == "Dana Example"
    assert not _warned(app)


def test_no_printed_name_means_no_guess(monkeypatch):
    app = _app(monkeypatch, customer_name="", remembered={})
    assert _name(app).value == ""
    assert not _warned(app)
