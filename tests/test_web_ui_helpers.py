import inspect
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from app import web_ui
from app.web_ui import _document_signature, _parse_amount, _pricing_difference


ROOT = Path(__file__).parents[1]


def _configure_smartsheet(monkeypatch):
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            monkeypatch.setenv(key, value)


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
    assert base != _document_signature(
        "abc", "Tulane", "Tulane", ["Labor", "Testing"], ["Painting"]
    )


def test_review_path_does_not_return_before_rendering_correctable_fields():
    source = inspect.getsource(web_ui.main)
    review_path = source.split(
        'token = st.session_state.get("analysis_token", "x")', 1
    )[1]

    assert "\n        return" not in review_path
    invalidation = review_path.index("A PDF-bearing detail changed")
    for marker in (
        'total_key = f"total_{token}"',
        'contact_key = f"contact_{token}"',
        'email_key = f"cemail_{token}"',
        'description_key = f"desc_{token}"',
        'scope_key = f"scope_{token}"',
    ):
        assert review_path.index(marker) < invalidation


def test_typed_total_survives_a_site_change(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "true")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.button[0].click().run()

    total = next(
        field
        for field in app.text_input
        if field.label
        == "PO/CO amount — final total including every fee and tax *"
    )
    total.set_value("1900.00").run()
    site = next(field for field in app.selectbox if field.label == "Site *")
    site.set_value("UMMC").run()

    retained_total = next(
        field
        for field in app.text_input
        if field.label
        == "PO/CO amount — final total including every fee and tax *"
    )
    assert not app.exception
    assert retained_total.value == "1900.00"


def test_unmapped_rrh_cost_code_blocks_generation(monkeypatch):
    _configure_smartsheet(monkeypatch)
    monkeypatch.setenv("EPC_ENABLE_SYNTHETIC_SAMPLE", "true")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    app.button[0].click().run()

    site = next(field for field in app.selectbox if field.label == "Site *")
    site.set_value("Unity Specialty").run()

    manual_cost = next(
        field for field in app.text_input if field.label == "Job cost code *"
    )
    generate = next(
        button
        for button in app.button
        if button.label == "Generate both files and Smartsheet link"
    )

    assert not app.exception
    assert manual_cost.value == ""
    assert generate.disabled
    assert any("enter the job cost code" in item.value for item in app.warning)
