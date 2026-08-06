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
    handoff_lines = _named_call_lines(main, "_render_smartsheet_handoff_link")

    assert len(send_lines) == 1
    assert len(handoff_lines) == 1
    assert send_lines[0] < handoff_lines[0]


def test_handoff_uses_exact_in_session_streamlit_page_link():
    source = WEB_UI.read_text(encoding="utf-8")
    tree = ast.parse(source)
    helper = _functions(tree)["_render_smartsheet_handoff_link"]

    page_links = [
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
        and node.func.attr == "page_link"
    ]

    assert len(page_links) == 1
    call = page_links[0]
    assert ast.literal_eval(call.args[0]) == "pages/2_Smartsheet_PO.py"

    keywords = {item.arg: item.value for item in call.keywords}
    assert ast.literal_eval(keywords["label"]) == "Continue to Smartsheet PO handoff"
    assert ast.literal_eval(keywords["icon"]) == "📋"
    assert ast.literal_eval(keywords["use_container_width"]) is True

    assert '_render_smartsheet_handoff_link("4" if epo_mode else "5")' in source
