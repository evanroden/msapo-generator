"""Synthetic receipt suggestions and exact split accounting (no live model)."""

import json
from decimal import Decimal

import pytest

from app import expense_ui
from app.expense_report import EXPENSE_SECTION_ENTERTAINMENT, EXPENSE_SECTION_MISC
from app.receipt_analyzer import RECEIPT_PROMPT, normalize_receipt_response


@pytest.fixture
def state(monkeypatch):
    session = {}
    monkeypatch.setattr(expense_ui.st, "session_state", session)
    return session


def _analysis(**values):
    return normalize_receipt_response(json.dumps(values))


def test_actual_tip_and_service_charge_reconcile_and_do_not_become_items():
    analysis = _analysis(
        merchant_name="Test Cafe",
        total_amount="31.75",
        tax_amount=None,
        tip_amount="5.00",
        service_charge="2.00",
        receipt_type="Meal",
        line_items=[
            {"description": "Lunch", "amount": "21.50"},
            {"description": "Drink", "amount": "3.25"},
            {"description": "Suggested tip", "amount": "5.00"},
        ],
    )
    assert analysis.tip_amount == "5.00"
    assert analysis.service_charge == "2.00"
    assert len(analysis.line_items) == 2
    notes = expense_ui._receipt_charge_notes(analysis)
    assert "Detected items: $24.75" in notes
    assert "Includes a $5.00 tip" in notes
    assert "Includes a $2.00 service charge" in notes
    assert "Final charged total: $31.75" in notes
    assert not any("Not itemised" in note for note in notes)
    assert Decimal(analysis.total_amount) == sum(
        (Decimal(item.amount) for item in analysis.line_items), Decimal("0")
    ) + Decimal(analysis.tip_amount) + Decimal(analysis.service_charge)
    assert all(key in RECEIPT_PROMPT for key in ("tip_amount", "service_charge", "receipt_type"))


def test_no_tip_read_shows_remaining_charge_without_changing_total():
    analysis = _analysis(
        total_amount="29.75",
        receipt_type="Meal",
        line_items=[
            {"description": "Meal", "amount": "21.50"},
            {"description": "Drink", "amount": "3.25"},
        ],
    )
    assert analysis.total_amount == "29.75"
    assert "Not itemised: $5.00" in expense_ui._receipt_charge_notes(analysis)
    assert expense_ui._tax_split_amounts(analysis) is None


def test_entertainment_is_suggested_with_reason_but_not_a_new_section(state):
    analysis = _analysis(
        total_amount="24.75",
        receipt_type="Meal",
        expense_section_guess="entertainment",
        expense_section_reason="Client guests identified on receipt",
        suggested_description="Meal expense",
    )
    assert analysis.receipt_type == "Meal"
    assert "Suggested: Meal · Entertainment" in expense_ui._receipt_section_suggestion(analysis)
    assert "Client guests identified" in expense_ui._receipt_section_suggestion(analysis)
    expense_ui._seed_receipt_fields("synthetic", analysis)
    assert state["expense_section_synthetic"] == EXPENSE_SECTION_ENTERTAINMENT
    assert state["expense_description_synthetic"] == "Meal expense"

    # An explicit choice beats even a delayed reading, then survives the mirror.
    state["expense_section_synthetic"] = EXPENSE_SECTION_MISC
    expense_ui._mark_receipt_section_edited("synthetic")
    state["expense_ai_seeded_synthetic"] = False
    expense_ui._seed_receipt_fields("synthetic", analysis)
    assert state["expense_section_synthetic"] == EXPENSE_SECTION_MISC
    expense_ui.preserve_expense_draft_state()
    state.pop("expense_section_synthetic")
    state.pop("expense_section_edited_synthetic")
    expense_ui.restore_expense_draft_state()
    assert state["expense_section_synthetic"] == EXPENSE_SECTION_MISC
    assert state["expense_section_edited_synthetic"] is True


@pytest.mark.parametrize("kind", ["Lodging", "Meal", "Parking", "Fuel", "Other"])
def test_recognised_type_does_not_change_official_section(kind):
    analysis = _analysis(
        total_amount="10.00", receipt_type=kind, expense_section_guess="miscellaneous",
    )
    assert expense_ui._receipt_section_suggestion(analysis) == (
        f"Suggested: {kind} · Miscellaneous"
    )
    assert analysis.expense_section_guess == EXPENSE_SECTION_MISC


def test_tax_split_is_exact_and_copies_reviewed_coding(state):
    analysis = _analysis(
        total_amount="29.75",
        tax_amount="2.13",
        receipt_type="Parking",
        suggested_description="Parking for work",
    )
    expense_ui._seed_receipt_fields("synthetic", analysis)
    state["expense_section_synthetic"] = EXPENSE_SECTION_ENTERTAINMENT
    expense_ui._mark_receipt_section_edited("synthetic")
    state["expense_contact_synthetic"] = "Test Contact"
    state["expense_receipt_allocation_synthetic_job_number"] = "TEST0001"
    state["expense_receipt_allocation_synthetic_account_cost_type"] = "01AMA"
    state["expense_receipt_allocation_synthetic_cost_code"] = "5490"

    assert expense_ui._tax_split_amounts(analysis) == (
        Decimal("27.62"), Decimal("2.13"),
    )
    assert expense_ui._apply_receipt_tax_split("synthetic", analysis) is True
    assert state["expense_split_synthetic"] is True
    assert state["expense_split_count_synthetic"] == 2
    assert state["expense_amount_synthetic"] == "27.62"
    assert state["expense_amount_synthetic_line_2"] == "2.13"
    assert Decimal(state["expense_amount_synthetic"]) + Decimal(
        state["expense_amount_synthetic_line_2"]
    ) == Decimal(analysis.total_amount)
    assert "before tax" in state["expense_description_synthetic"]
    assert state["expense_description_synthetic_line_2"].startswith("Sales tax")
    assert state["expense_section_synthetic_line_2"] == EXPENSE_SECTION_ENTERTAINMENT
    assert state["expense_contact_synthetic_line_2"] == "Test Contact"
    assert state["expense_receipt_allocation_synthetic_line_2_cost_code"] == "5490"

    expense_ui.preserve_expense_draft_state()
    for key in ("expense_split_synthetic", "expense_amount_synthetic_line_2"):
        state.pop(key)
    expense_ui.restore_expense_draft_state()
    assert state["expense_split_synthetic"] is True
    assert state["expense_amount_synthetic_line_2"] == "2.13"


def test_tax_split_rejects_unreliable_and_foreign_totals():
    assert expense_ui._tax_split_amounts(
        _analysis(total_amount="10.00", tax_amount="12.00")
    ) is None
    assert expense_ui._tax_split_amounts(
        _analysis(total_amount="10.00", tax_amount="1.00", currency="CAD")
    ) is None


def test_reconciliation_does_not_change_exported_expense_item_structure():
    """Only the reviewed existing line fields, never a new report field, export."""
    from dataclasses import fields
    from app.expense_report import ExpenseItem
    assert "tip_amount" not in {field.name for field in fields(ExpenseItem)}
    assert "receipt_type" not in {field.name for field in fields(ExpenseItem)}
