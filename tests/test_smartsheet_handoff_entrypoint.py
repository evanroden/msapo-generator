import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]
WEB_UI = ROOT / "app" / "web_ui.py"


def _functions(tree: ast.AST) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def _named_call_lines(function: ast.FunctionDef, name: str) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def test_main_has_one_final_generation_route_and_no_separate_submit_or_email_route():
    source = WEB_UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = _functions(tree)["main"]

    assert len(_named_call_lines(main, "render_inline_smartsheet_handoff")) == 1
    assert source.count('"Generate both files and Smartsheet link"') == 1
    assert "Prepare Smartsheet submission" not in source
    assert "Generate Scope/Inclusions/Exclusions PDF" not in source
    assert "step-num mint\">5" not in source
    assert "st.switch_page" not in source
    assert "build_eml" not in source
    assert "Use email backup" not in source
    assert "Outlook" not in source
    assert "Apple Mail" not in source


def test_four_step_screen_follows_actual_interaction_order():
    source = WEB_UI.read_text(encoding="utf-8")
    labels = (
        "Provide the vendor quote",
        "Review the extracted work",
        "Confirm the PO details",
        "Generate both files and the Smartsheet link",
    )
    positions = [source.index(label) for label in labels]
    assert positions == sorted(positions)
    assert source.count('class="step-num') == 4


def test_main_generates_exactly_the_quote_and_scope_pdf_from_one_action():
    source = WEB_UI.read_text(encoding="utf-8")

    assert source.count("build_scope_pdf(") == 1
    assert "unchanged quote" in source
    assert "scope_pdf_bytes" in source
    assert "uploaded_file_bytes" in source
    assert "generate_msapo" not in source
    assert "convert_docx" not in source
    assert "download_button(" not in source


def test_streamlined_controls_guess_and_remember_without_obsolete_buttons():
    source = WEB_UI.read_text(encoding="utf-8")

    assert "purchase_route_guess" in source
    assert "infer_purchase_route(" in source
    assert "guess_asset_uid(" in source
    assert "request_type_guess" in source
    assert "remembered_device_account_manager(" in source
    assert "record_device_account_manager(" in source
    assert "total_confirmed" not in source
    assert "forget_device_requester" not in source
    assert "Forget requester" not in source
    assert "max_chars=20" in source
    assert '"Review or change the tool\'s selections"' in source
    assert "disabled=bool(draft_problems)" in source
    assert "st.session_state.get(asset_state_key) not in options" in source
    assert source.index("Review or change the tool's selections") < source.index(
        "Your name (Requester / Asset Manager) *"
    )


def test_quote_source_and_retry_flow_fail_closed_without_stale_analysis():
    source = WEB_UI.read_text(encoding="utf-8")

    assert "QUOTE_INPUT_MODES" in source
    assert "choose_quote_text(" in source
    assert "clear_active_analysis(" in source
    assert "max_upload_size=MAX_ATTACHMENT_BYTES" in source
    assert "extraction_error_hash" in source
    assert "Try reading this file again" in source
    assert "analysis_error_signature" in source
    assert "Try analyzing this quote again" in source
    assert "st.tabs(" not in source
    assert "st.stop()" not in source


def test_inline_handoff_shows_two_downloads_link_and_only_hidden_copy_fallback():
    inline_path = ROOT / "app" / "smartsheet_inline.py"
    inline = inline_path.read_text(encoding="utf-8")
    tree = ast.parse(inline)
    helper = _functions(tree)["render_inline_smartsheet_handoff"]
    helper_source = ast.get_source_segment(inline, helper)

    assert helper_source is not None
    assert "render_prefilled_link(prefilled.url)" in helper_source
    assert "render_manual_handoff(" in helper_source
    assert '.expander("Troubleshooting: show manual field values", expanded=False)' in helper_source
    assert ".download_button(" in helper_source
    assert "len(renamed_files) != 2" in helper_source
    assert "record_device_requester(" not in helper_source
    assert "build_prefilled_form_url(fields, config)" in helper_source
    assert "prefill_enabled(config)" in helper_source
    assert "prefilled.missing_required" in helper_source
    assert "st.switch_page" not in inline
    assert "st.checkbox" not in helper_source
    assert "email backup" not in helper_source.lower()


def test_inline_handoff_contains_recent_login_retry_and_upload_reminders():
    inline = (ROOT / "app" / "smartsheet_inline.py").read_text(encoding="utf-8")

    assert "within the last few hours" in inline
    assert "same link again" in inline
    assert "upload the original quote" in inline
    assert "Scope/Inclusions/Exclusions PDF" in inline
    assert "does not submit it and cannot upload files" in inline


def test_legacy_destination_is_non_submitting_compatibility_notice():
    page = (ROOT / "pages" / "2_Smartsheet_PO.py").read_text(encoding="utf-8")
    assert "compatibility page" in page.lower()
    assert "Return to Purchase Order Process Control" in page
    assert "render_inline_smartsheet_handoff" not in page
    assert "submit_po" not in page


def test_prefilled_link_is_labeled_and_suppresses_referrer_data():
    component = (ROOT / "app" / "smartsheet_ui.py").read_text(encoding="utf-8")
    assert 'link_label: str = "Open Smartsheet form ↗"' in component
    assert 'link_label: str = "Open prefilled Smartsheet form ↗"' in component
    assert 'referrerpolicy="no-referrer"' in component
    assert component.count("st.iframe(") == 2
    assert "components.html(" not in component


def test_streamlit_runtime_security_controls_are_not_contradictory():
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    assert "enableCORS = true" in config
    assert "enableCORS = false" not in config
    assert "enableXsrfProtection = true" in config


def test_render_blueprint_maps_every_populated_field_under_exact_live_labels():
    source = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert 'SMARTSHEET_URL_PREFILL_ENABLED\n        value: "true"' in source
    for mapping in (
        '"request_type":"REQUEST TYPE"',
        '"requester_name":"REQUESTER"',
        '"job_number":"JOB NUMBER"',
        '"site_location":"SITE NUMBER / LOCATION"',
        '"cost_code":"COST CODE"',
        '"object_account":"OBJECT ACCOUNT"',
        '"agreement_type":"AGREEMENT TYPE FOR PO"',
        '"original_po_number":"ORIGINAL PO NUMBER"',
        '"total":"PO/CO AMOUNT"',
        '"vendor":"VENDOR NAME"',
        '"contact_name":"VENDOR CONTACT NAME"',
        '"contact_email":"VENDOR CONTACT EMAIL"',
        '"description_of_work":"DESCRIPTION OF WORK"',
        '"asset_id":"ASSET ID"',
        '"dispatch_service_center":"DISPATCH WO TO SERVICE CENTER?"',
        '"instructions":"ADDITIONAL INFORMATION IF NEEDED"',
    ):
        assert mapping in source

    for forbidden in (
        "leave_request_completed",
        "po_number",
        "work_order_number",
        "send_copy_email",
    ):
        assert f'"{forbidden}":' not in source
    assert "ORIGIONAL PO NUMBER" not in source
