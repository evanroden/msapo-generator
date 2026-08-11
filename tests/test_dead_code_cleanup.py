import inspect

from app import document_generator, quote_analyzer


def test_document_generator_accepts_only_reviewed_scope_lists():
    signature = inspect.signature(document_generator.generate_docx)

    assert "approved_assumptions" not in signature.parameters
    assert "final_inclusions" in signature.parameters
    assert "final_exclusions" in signature.parameters
    assert not hasattr(document_generator, "_filter_items")


def test_quote_analyzer_does_not_redeclare_schema_defaults():
    source = inspect.getsource(quote_analyzer.analyze_quote)

    assert 'if "tax_note" not in data' not in source
    assert "Defaults for email / cost-code fields" not in source
