import json

import fitz
import pytest

from app.expense_report import (
    EXPENSE_SECTION_ENTERTAINMENT,
    EXPENSE_SECTION_MISC,
)
from app.receipt_analyzer import (
    RECEIPT_PROMPT,
    ReceiptAnalysisError,
    analyze_receipt,
    normalize_receipt_response,
)


def test_receipt_response_normalizes_editable_fields():
    result = normalize_receipt_response(
        """
        ```json
        {
          "merchant_name": "  Test Restaurant ",
          "transaction_date": "2026-08-10",
          "total_amount": "$1,234.50",
          "tax_amount": " 12.34 ",
          "currency": "usd",
          "suggested_description": "Business meal",
          "line_items": [
            {"description": "Guest meal", "amount": "600.00"},
            {"description": "Employee meal", "amount": "622.16"}
          ],
          "expense_section_guess": "entertainment",
          "confidence": "HIGH",
          "review_notes": ["Confirm attendee"]
        }
        ```
        trailing remark
        """
    )

    assert result.merchant_name == "Test Restaurant"
    assert result.transaction_date.isoformat() == "2026-08-10"
    assert result.total_amount == "1234.50"
    assert result.tax_amount == "12.34"
    assert result.currency == "USD"
    assert result.expense_section_guess == EXPENSE_SECTION_ENTERTAINMENT
    assert result.confidence == "high"
    assert result.review_notes == ["Confirm attendee"]
    assert [
        (item.description, item.amount) for item in result.line_items
    ] == [
        ("Guest meal", "600.00"),
        ("Employee meal", "622.16"),
    ]


def test_bad_hints_degrade_to_visible_manual_review():
    result = normalize_receipt_response(
        """{
          "merchant_name": "Parking",
          "transaction_date": "08/10/26",
          "total_amount": "subtotal only",
          "tax_amount": -4,
          "currency": "dollars",
          "suggested_description": null,
          "line_items": [
            {"description": "", "amount": "12.00"},
            {"description": "Usable item", "amount": "3.50"},
            {"description": "TOTAL", "amount": "18.00"},
            {"description": "Total Due", "amount": "18.00"},
            {"description": "Coupon", "amount": "2.00"},
            "not an object"
          ],
          "expense_section_guess": "meal",
          "confidence": "certain",
          "review_notes": "not a list"
        }"""
    )

    assert result.transaction_date is None
    assert result.total_amount == ""
    assert result.tax_amount == ""
    assert result.currency == ""
    assert result.suggested_description == "Parking"
    assert result.expense_section_guess == EXPENSE_SECTION_MISC
    assert result.confidence == "low"
    assert len(result.line_items) == 1
    assert result.line_items[0].description == "Usable item"
    assert result.line_items[0].amount == "3.50"
    assert "The receipt date could not be read reliably." in result.review_notes
    assert "Confirm the final amount paid." in result.review_notes
    assert "Confirm the receipt currency." in result.review_notes
    assert "One or more unreadable receipt-item rows were omitted." in result.review_notes


def test_detected_receipt_items_are_bounded_without_collapsing_repeated_items():
    line_items = [
        {"description": f"Repeated item {index % 3}", "amount": "1.00"}
        for index in range(65)
    ]
    result = normalize_receipt_response(json.dumps({"line_items": line_items}))

    assert len(result.line_items) == 60
    assert result.line_items[0].description == "Repeated item 0"
    assert result.line_items[3].description == "Repeated item 0"
    # Assert the FACTS the note has to carry, not one exact sentence. The
    # wording changed on 2026-08-18 because it used to say "the first 60 are
    # shown" even when rejected rows meant far fewer were -- see
    # tests/test_review_bug_fixes_2026_08_18.py. What must never change is that
    # a truncation is stated at all, and that the numbers in it are real.
    note = next(n for n in result.review_notes if "rows" in n)
    assert "65 rows" in note, "the note must name how many rows the receipt listed"
    assert "60" in note, "the note must name the bound that was applied"


def test_large_item_total_mismatch_requires_visible_review_note():
    result = normalize_receipt_response(
        json.dumps(
            {
                "total_amount": "120.00",
                "line_items": [
                    {"description": "Only readable item", "amount": "20.00"}
                ],
            }
        )
    )

    assert any(
        "differ substantially from the final charged total" in note
        for note in result.review_notes
    )


def test_receipt_prompt_treats_document_instructions_as_untrusted():
    assert "untrusted document content" in RECEIPT_PROMPT
    assert "instructions, code, prompts" in RECEIPT_PROMPT


def test_genuinely_malformed_receipt_response_still_raises():
    try:
        normalize_receipt_response("{not json")
    except ReceiptAnalysisError:
        pass
    else:
        raise AssertionError("malformed receipt JSON should fail")


def test_overlong_pdf_is_rejected_before_an_api_client_is_created(monkeypatch):
    document = fitz.open()
    for _ in range(11):
        document.new_page(width=100, height=100)
    payload = document.tobytes()
    document.close()

    def unexpected_client(**_kwargs):
        raise AssertionError("invalid receipt must not reach the AI client")

    monkeypatch.setattr("app.receipt_analyzer.ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("app.receipt_analyzer.anthropic.Anthropic", unexpected_client)

    with pytest.raises(ReceiptAnalysisError, match="11 pages; the limit is 10"):
        analyze_receipt(payload, "overlong.pdf")
