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


def test_main_exposes_delivery_controls_before_conditional_routes():
    tree = ast.parse(WEB_UI.read_text(encoding="utf-8"))
    main = _functions(tree)["main"]

    send_lines = _named_call_lines(main, "_render_send_section")
    control_lines = _named_call_lines(main, "_render_delivery_controls")
    inline_lines = _named_call_lines(main, "render_inline_smartsheet_handoff")

    assert len(send_lines) == 1
    assert len(control_lines) == 1
    assert len(inline_lines) == 1
    assert control_lines[0] < send_lines[0]
    assert control_lines[0] < inline_lines[0]


def test_delivery_controls_offer_smartsheet_and_email_side_by_side():
    source = WEB_UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = _functions(tree)["_render_delivery_controls"]

    buttons = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "button"
    ]

    assert len(buttons) == 2
    labels = {ast.literal_eval(button.args[0]) for button in buttons}
    assert labels == {
        "📋 Prepare Smartsheet submission",
        "✉️ Use email backup",
    }
    for button in buttons:
        keywords = {item.arg: item.value for item in button.keywords}
        assert ast.literal_eval(keywords["type"]) == "primary"
        assert ast.literal_eval(keywords["use_container_width"]) is True

    columns = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "columns"
    ]
    assert len(columns) == 1
    assert ast.literal_eval(columns[0].args[0]) == 2

    helper_source = ast.get_source_segment(source, helper)
    assert helper_source is not None
    assert 'st.session_state[route_key] = "smartsheet"' in helper_source
    assert 'st.session_state[route_key] = "email"' in helper_source
    assert "st.switch_page" not in source


def test_inline_handoff_keeps_manual_controls_and_requester_memory():
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
    assert 'config.form_url or ""' not in helper_source
    assert 'fields.pop("send_copy_email", None)' in helper_source
    assert "st.checkbox" not in helper_source
    assert "Request type = PO" in helper_source
    assert "Dispatch service center = NA" in helper_source


def test_legacy_destination_explains_mobile_session_loss():
    page = (ROOT / "pages" / "2_Smartsheet_PO.py").read_text(encoding="utf-8")
    assert "No prepared PO reached this page" in page
    assert "opens inline on the same page" in page



def test_prefilled_link_is_labeled_and_suppresses_referrer_data():
    component = (ROOT / "app" / "smartsheet_ui.py").read_text(encoding="utf-8")
    assert 'link_label: str = "Open Smartsheet form ↗"' in component
    assert '"linkLabel": link_label' in component
    assert "textContent = D.linkLabel" in component
    assert 'referrerpolicy="no-referrer"' in component


def test_render_blueprint_enables_the_complete_exact_label_map():
    source = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert 'SMARTSHEET_URL_PREFILL_ENABLED\n        value: "true"' in source
    assert '"request_type":"REQUEST TYPE"' in source
    assert '"requester_name":"REQUESTER"' in source
    assert '"job_number":"JOB NUMBER"' in source
    assert '"site_location":"SITE NUMBER / LOCATION"' in source
    assert '"cost_code":"COST CODE"' in source
    assert '"object_account":"OBJECT ACCOUNT"' in source
    assert '"agreement_type":"AGREEMENT TYPE FOR PO"' in source
    assert '"original_po_number":"ORIGIONAL PO NUMBER"' in source
    assert '"total":"PO/CO AMOUNT"' in source
    assert '"vendor":"VENDOR NAME"' in source
    assert '"contact_name":"VENDOR CONTACT NAME"' in source
    assert '"contact_email":"VENDOR CONTACT EMAIL"' in source
    assert '"description_of_work":"DESCRIPTION OF WORK"' in source
    assert '"asset_id":"ASSET ID"' in source
    assert '"dispatch_service_center":"DISPATCH WO TO SERVICE CENTER?"' in source
    assert '"instructions":"ADDITIONAL INFORMATION IF NEEDED"' in source
