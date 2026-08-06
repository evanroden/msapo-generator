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


def test_main_has_one_inline_smartsheet_route_and_no_email_route():
    source = WEB_UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = _functions(tree)["main"]

    assert len(_named_call_lines(main, "render_inline_smartsheet_handoff")) == 1
    assert "Prepare Smartsheet submission" in source
    assert "st.switch_page" not in source
    assert "build_eml" not in source
    assert "Use email backup" not in source
    assert "Outlook" not in source
    assert "Apple Mail" not in source
    assert "_render_send_section" not in source


def test_main_generates_only_the_scope_pdf_package():
    source = WEB_UI.read_text(encoding="utf-8")

    assert "build_scope_pdf(" in source
    assert "Generate Scope/Inclusions/Exclusions PDF" in source
    assert "unchanged original quote plus one simple PDF" in source
    assert "generate_msapo" not in source
    assert "convert_docx" not in source
    assert "download_button(" in source


def test_inline_handoff_keeps_prefill_downloads_and_requester_memory():
    inline_path = ROOT / "app" / "smartsheet_inline.py"
    inline = inline_path.read_text(encoding="utf-8")
    tree = ast.parse(inline)
    helper = _functions(tree)["render_inline_smartsheet_handoff"]
    helper_source = ast.get_source_segment(inline, helper)

    assert helper_source is not None
    assert "render_manual_handoff(" in helper_source
    assert ".download_button(" in helper_source
    assert "record_device_requester(" in helper_source
    assert "build_prefilled_form_url(fields, config)" in helper_source
    assert "prefill_enabled(config)" in helper_source
    assert "prefilled.url" in helper_source
    assert 'link_label="Open prefilled Smartsheet form ↗"' in helper_source
    assert "st.switch_page" not in inline
    assert "st.checkbox" not in helper_source
    assert "person filling out this request" in helper_source
    assert "Object Account =" in helper_source
    assert "Agreement Type =" in helper_source
    assert "Dispatch Service Center = NA" in helper_source
    assert "Leave Request Completed, PO #, Work Order #" in helper_source
    assert "email backup" not in helper_source.lower()


def test_legacy_destination_is_non_submitting_compatibility_notice():
    page = (ROOT / "pages" / "2_Smartsheet_PO.py").read_text(encoding="utf-8")
    assert "compatibility page" in page.lower()
    assert "Return to Purchase Order Process Control" in page
    assert "render_inline_smartsheet_handoff" not in page
    assert "submit_po" not in page


def test_prefilled_link_is_labeled_and_suppresses_referrer_data():
    component = (ROOT / "app" / "smartsheet_ui.py").read_text(encoding="utf-8")
    assert 'link_label: str = "Open Smartsheet form ↗"' in component
    assert '"linkLabel": link_label' in component
    assert "textContent = D.linkLabel" in component
    assert 'referrerpolicy="no-referrer"' in component


def test_render_blueprint_maps_only_fields_that_may_be_populated():
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
        "original_po_number",
        "send_copy_email",
    ):
        assert f'"{forbidden}":' not in source
