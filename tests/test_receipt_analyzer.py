from app.expense_report import (
    EXPENSE_SECTION_ENTERTAINMENT,
    EXPENSE_SECTION_MISC,
)
from app.receipt_analyzer import ReceiptAnalysisError, normalize_receipt_response


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


def test_bad_hints_degrade_to_visible_manual_review():
    result = normalize_receipt_response(
        """{
          "merchant_name": "Parking",
          "transaction_date": "08/10/26",
          "total_amount": "subtotal only",
          "tax_amount": -4,
          "currency": "dollars",
          "suggested_description": null,
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
    assert "The receipt date could not be read reliably." in result.review_notes
    assert "Confirm the final amount paid." in result.review_notes
    assert "Confirm the receipt currency." in result.review_notes


def test_genuinely_malformed_receipt_response_still_raises():
    try:
        normalize_receipt_response("{not json")
    except ReceiptAnalysisError:
        pass
    else:
        raise AssertionError("malformed receipt JSON should fail")

