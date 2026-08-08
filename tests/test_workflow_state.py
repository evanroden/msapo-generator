from app.workflow_state import (
    PASTE_MODE,
    UPLOAD_MODE,
    choose_quote_text,
    clear_active_analysis,
    quote_length_problem,
)


def test_selected_quote_source_cannot_be_overridden_by_stale_inactive_text():
    uploaded = choose_quote_text(
        UPLOAD_MODE,
        uploaded_text="new uploaded quote",
        pasted_text="stale pasted quote",
    )
    pasted = choose_quote_text(
        PASTE_MODE,
        uploaded_text="stale uploaded quote",
        pasted_text="new pasted quote",
    )

    assert uploaded == ("new uploaded quote", "upload")
    assert pasted == ("new pasted quote", "paste")


def test_synthetic_quote_survives_reload_until_real_input_takes_over():
    assert choose_quote_text(
        UPLOAD_MODE,
        synthetic_active=True,
        synthetic_text="synthetic quote",
    ) == ("synthetic quote", "synthetic")


def test_clearing_source_removes_old_analysis_and_generated_package_state():
    state = {
        "analysis": object(),
        "analysis_token": "old",
        "quote_text": "old quote",
        "quote_source": "upload",
        "last_sig": "old-signature",
        "scope_pdf_bytes": b"old pdf",
        "scope_pdf_signature": "old-pdf-signature",
        "generated_context_old": "old-context",
        "uploaded_file_name": "preserved-source.pdf",
    }

    clear_active_analysis(state)

    assert state == {"uploaded_file_name": "preserved-source.pdf"}


def test_oversized_analysis_input_is_blocked_before_model_call():
    assert quote_length_problem("small quote") == ""
    assert "analysis limit" in quote_length_problem("x" * 500_001)
