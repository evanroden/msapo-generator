"""The migration switch must stop every entry point before any app work."""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.service_closed import _DEFAULT_NOTICE, _valid_https_destination


ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINTS = (
    ROOT / "run_web.py",
    ROOT / "pages" / "2_Smartsheet_PO.py",
)
GOOD_URL = "https://process-control.example.invalid/new"


@pytest.fixture
def link_calls(monkeypatch):
    """AppTest 1.61 does not expose link_button elements; spy on the native call."""
    from app import service_closed

    calls = []
    native_link_button = service_closed.st.link_button

    def record(label, url, *args, **kwargs):
        calls.append((label, url))
        return native_link_button(label, url, *args, **kwargs)

    monkeypatch.setattr(service_closed.st, "link_button", record)
    return calls


def _app(path: Path) -> AppTest:
    app = AppTest.from_file(str(path), default_timeout=30).run()
    assert not app.exception, app.exception
    return app


def _assert_only_closure(app: AppTest, notice: str, url: str | None, links) -> None:
    assert [item.value for item in app.text] == [notice]
    assert links == ([("Open Process Control", url)] if url else [])
    for kind in (
        "segmented_control", "button", "page_link", "file_uploader",
        "text_input", "text_area", "download_button", "info", "markdown", "title",
    ):
        assert not app.get(kind), f"unexpected {kind} while closed"


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=lambda p: p.name)
def test_closed_valid_address_has_only_text_and_link_and_no_data_files(
    monkeypatch, tmp_path, link_calls, entry
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("EPC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MSAPO_SERVICE_MOVED_TO", GOOD_URL)
    monkeypatch.delenv("MSAPO_SERVICE_NOTICE", raising=False)

    _assert_only_closure(_app(entry), _DEFAULT_NOTICE, GOOD_URL, link_calls)
    assert list(data_dir.iterdir()) == []


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=lambda p: p.name)
@pytest.mark.parametrize("bad_url", ["http://example.invalid", "https:///", "somewhere/else", " "])
def test_bad_address_still_closes_without_link_or_data_writes(
    monkeypatch, tmp_path, caplog, link_calls, entry, bad_url
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("EPC_DATA_DIR", str(data_dir))
    monkeypatch.setenv("MSAPO_SERVICE_MOVED_TO", bad_url)
    monkeypatch.delenv("MSAPO_SERVICE_NOTICE", raising=False)

    with caplog.at_level(logging.WARNING, logger="app.service_closed"):
        _assert_only_closure(_app(entry), _DEFAULT_NOTICE, None, link_calls)

    warnings = [r for r in caplog.records if r.name == "app.service_closed"]
    assert len(warnings) == 1
    assert bad_url not in warnings[0].message
    assert list(data_dir.iterdir()) == []


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=lambda p: p.name)
def test_notice_is_literal_text_not_markdown_or_html(monkeypatch, link_calls, entry):
    notice = "<script>alert('no')</script> **bold** [fake](https://example.invalid)"
    monkeypatch.setenv("MSAPO_SERVICE_MOVED_TO", GOOD_URL)
    monkeypatch.setenv("MSAPO_SERVICE_NOTICE", notice)

    _assert_only_closure(_app(entry), notice, GOOD_URL, link_calls)


@pytest.mark.parametrize("entry", ENTRY_POINTS, ids=lambda p: p.name)
@pytest.mark.parametrize("open_value", [None, ""])
def test_unset_or_empty_switch_keeps_normal_first_screen(
    monkeypatch, entry, open_value
):
    if open_value is None:
        monkeypatch.delenv("MSAPO_SERVICE_MOVED_TO", raising=False)
    else:
        monkeypatch.setenv("MSAPO_SERVICE_MOVED_TO", open_value)
    monkeypatch.setenv("MSAPO_SERVICE_NOTICE", "unused notice")

    app = _app(entry)
    assert not app.text or _DEFAULT_NOTICE not in [x.value for x in app.text]
    if entry.name == "run_web.py":
        assert len(app.segmented_control) == 1
        assert app.segmented_control[0].label == "Choose workflow"
    else:
        assert any("Smartsheet PO handoff" in x.value for x in app.get("title"))
        assert app.get("info")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (GOOD_URL, True),
        ("https://example.invalid/path?draft=1", True),
        ("", False),
        ("http://example.invalid", False),
        ("javascript:alert(1)", False),
        ("https:///", False),
        ("https://example.invalid:99999", False),
        ("https://bad host.invalid", False),
        ("https://user@example.invalid", False),
    ],
)
def test_only_https_destinations_with_hosts_are_accepted(value, expected):
    assert _valid_https_destination(value) is expected


def _call_name(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Call):
        return None
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
        return f"{node.func.value.id}.{node.func.attr}"
    return None


def test_every_discoverable_page_guards_immediately_after_page_config():
    pages = sorted((ROOT / "pages").rglob("*.py"))
    assert pages, "Streamlit must have at least one discoverable page"
    for path in pages:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            alias.name
            for stmt in tree.body
            if isinstance(stmt, ast.ImportFrom) and stmt.module == "app.service_closed"
            for alias in stmt.names
        ]
        calls = [
            _call_name(stmt.value)
            for stmt in tree.body
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
        ]
        assert "close_if_moved" in imports, f"{path} must import the guard"
        assert calls[:2] == ["st.set_page_config", "close_if_moved"], (
            f"{path} must run the closure before rendering any page contents"
        )


def test_root_ui_guards_immediately_after_page_config():
    source = (ROOT / "app" / "web_ui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name == "main")
    calls = [
        _call_name(stmt.value)
        for stmt in main.body
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
    ]
    assert calls[:2] == ["st.set_page_config", "close_if_moved"]
