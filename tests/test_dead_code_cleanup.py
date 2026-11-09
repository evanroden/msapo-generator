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


def test_high_confidence_august_css_cleanup_preserves_live_rules():
    from app import web_ui

    css = web_ui.CUSTOM_CSS
    assert ".epc-needs-value" not in css
    assert ".scope-section" not in css
    assert ".scope-text" not in css
    assert ".scope-label {" in css
    assert ".step-num.yellow {" in css
    assert '<div class="step-num navy">' not in inspect.getsource(web_ui)
    assert '<div class="step-num">1</div>' in inspect.getsource(web_ui)


def test_high_confidence_august_unused_python_exports_are_absent():
    from app import expense_report, po_context, po_rules

    assert not hasattr(expense_report, "ALLOCATION_KINDS")
    assert not hasattr(expense_report, "EXPENSE_SECTIONS")
    assert not hasattr(po_context, "_existing_path")
    assert not hasattr(po_context, "PREPARED_PO_CONTEXT_STATE_KEY")
    assert not hasattr(po_rules, "asset_id_is_numeric")
    assert expense_report.ALLOCATION_JOB == "job"
    assert callable(po_rules.normalize_asset_id)
