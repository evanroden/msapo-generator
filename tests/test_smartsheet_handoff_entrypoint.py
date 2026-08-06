import ast
from pathlib import Path


WEB_UI = Path(__file__).parents[1] / "app" / "web_ui.py"


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


def test_main_exposes_smartsheet_handoff_after_email_panel():
    tree = ast.parse(WEB_UI.read_text(encoding="utf-8"))
    main = _functions(tree)["main"]

    send_lines = _named_call_lines(main, "_render_send_section")
    handoff_lines = _named_call_lines(main, "_render_smartsheet_handoff_control")

    assert len(send_lines) == 1
    assert len(handoff_lines) == 1
    assert send_lines[0] < handoff_lines[0]


def test_handoff_uses_server_side_streamlit_page_switch():
    source = WEB_UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = _functions(tree)["_render_smartsheet_handoff_control"]

    buttons = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "button"
    ]

    assert len(buttons) == 1
    button = buttons[0]
    assert ast.literal_eval(button.args[0]) == "📋 Continue to Smartsheet PO handoff"
    keywords = {item.arg: item.value for item in button.keywords}
    assert ast.literal_eval(keywords["type"]) == "primary"
    assert ast.literal_eval(keywords["use_container_width"]) is True
    assert ast.literal_eval(keywords["key"]) == "continue_to_smartsheet_po"

    switches = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "switch_page"
    ]
    assert len(switches) == 1
    assert ast.literal_eval(switches[0].args[0]) == "pages/2_Smartsheet_PO.py"

    assert '_render_smartsheet_handoff_control("4" if epo_mode else "5")' in source
