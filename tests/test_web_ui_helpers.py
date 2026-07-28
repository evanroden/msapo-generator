from decimal import Decimal

from app.web_ui import _document_signature, _parse_amount, _pricing_difference


def test_parse_amount_handles_us_currency_formatting():
    assert _parse_amount("$4,546.50") == Decimal("4546.50")
    assert _parse_amount("  $346.50 ") == Decimal("346.50")
    assert _parse_amount("") is None
    assert _parse_amount("not stated") is None


def test_pricing_difference_detects_mismatch():
    assert _pricing_difference("$4,200.00", "$346.50", "$4,546.50") == Decimal("0.00")
    assert _pricing_difference("$4,200.00", "$346.50", "$4,500.00") == Decimal("46.50")
    assert _pricing_difference("", "$346.50", "$4,546.50") is None


def test_document_signature_changes_with_routing_or_scope():
    base = _document_signature("abc", "Tulane", "Tulane", ["Labor"], ["Painting"])

    assert base == _document_signature("abc", "Tulane", "Tulane", ["Labor"], ["Painting"])
    assert base != _document_signature("abc", "NOVANT", "Tulane", ["Labor"], ["Painting"])
    assert base != _document_signature("abc", "Tulane", "Other Site", ["Labor"], ["Painting"])
    assert base != _document_signature("abc", "Tulane", "Tulane", ["Labor", "Testing"], ["Painting"])
