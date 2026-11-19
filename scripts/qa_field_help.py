"""Field help: real pointer, keyboard and WebKit touch; synthetic data only.

A source inventory covers every production PO/expense help call, including
conditional widgets. A local Streamlit fixture renders the identical shared
helper for all entries, so every sentence is exercised in both browser engines.
Two existing synthetic workflow fixtures also prove integration on real forms.
No external website, account, form submission or email is used.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "test-artifacts" / "field-help"
EXPECTED = {"app/web_ui.py": 15, "app/expense_ui.py": 17}
REPORT = {"synthetic_only": True, "inputs": "native Playwright mouse, keyboard, touchscreen",
          "browsers": [], "checks": [], "failures": []}


def inventory():
    """Read actual widget labels and literal help sentences, never a second copy."""
    result = []
    for path, expected in EXPECTED.items():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
        widgets = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "st"
                    and any(kw.arg == "help" for kw in node.keywords)):
                raise AssertionError(f"Native Streamlit help icon remains: {path}:{node.lineno}")
            if not (isinstance(node.func, ast.Name) and node.func.id == "field_with_help"):
                continue
            if not (len(node.args) >= 2
                    and isinstance(node.args[0], ast.Attribute)
                    and isinstance(node.args[0].value, ast.Name)
                    and node.args[0].value.id == "st"):
                raise AssertionError(f"Help wrapper must call a Streamlit widget: {path}:{node.lineno}")
            words = [kw.value for kw in node.keywords if kw.arg == "help"]
            if len(words) != 1:
                raise AssertionError(f"One literal help is required: {path}:{node.lineno}")
            label, instruction = ast.literal_eval(node.args[1]), ast.literal_eval(words[0])
            if not (isinstance(label, str) and isinstance(instruction, str) and instruction.strip()):
                raise AssertionError(f"Label and help must be nonempty: {path}:{node.lineno}")
            if instruction.count(".") + instruction.count("!") < 1:
                raise AssertionError(f"Help must explain the field: {path}:{node.lineno}")
            widgets.append({"workflow": "po" if "web_ui" in path else "expense",
                            "widget": node.args[0].attr, "label": label,
                            "help": instruction, "line": node.lineno})
        widgets.sort(key=lambda row: row["line"])
        if len(widgets) != expected:
            raise AssertionError(f"{path}: expected {expected} visible help fields, got {len(widgets)}")
        result.extend(widgets)
    for index, row in enumerate(result):
        row["id"] = f"{index:02d}"
    return result


def fixture():
    import streamlit as st
    from app.field_help import field_with_help
    st.set_page_config(page_title="Synthetic field help check", layout="wide")
    st.title("Synthetic field help check")
    st.caption("Each field uses the shared production guidance renderer.")
    for row in inventory():
        with st.container(key=f"qa_field_help_{row['id']}"):
            # A text input provides a stable and keyboard-accessible activation
            # target even for guidance attached to conditional production widgets.
            field_with_help(st.text_input, row["label"],
                            key=f"qa_help_input_{row['id']}", help=row["help"])


def record(engine, input_type, row, present):
    REPORT["checks"].append({"engine": engine, "input": input_type,
                             "id": row["id"], "workflow": row["workflow"],
                             "label": row["label"], "passed": bool(present)})
    if not present:
        raise AssertionError(f"{engine} {input_type}: missing exact help for {row['id']}")


def local_only(route, port):
    parsed = urlparse(route.request.url)
    if parsed.scheme in {"blob", "data"} or (parsed.hostname == "127.0.0.1" and parsed.port == port):
        route.continue_()
    else:
        route.abort()


def exercise_gallery(browser, engine, viewport, rows, touch=False):
    context = browser.new_context(viewport=viewport, has_touch=touch, is_mobile=touch)
    page = context.new_page()
    name = f"{engine}-{viewport['width']}x{viewport['height']}"
    page.route("**/*", lambda route: local_only(route, 8526))
    try:
        page.goto("http://127.0.0.1:8526", wait_until="domcontentloaded")
        page.locator(".st-key-qa_field_help_00").wait_for(timeout=30000)
        for row in rows:
            wrapper = page.locator(f".st-key-qa_field_help_{row['id']}")
            field = wrapper.get_by_role("textbox", name=row["label"], exact=True)
            caption = wrapper.get_by_text(row["help"], exact=True)
            field.scroll_into_view_if_needed()
            assert field.count() == 1
            assert wrapper.locator('[data-testid="stTooltipIcon"], [aria-label^="Help for"]').count() == 0
            assert caption.is_visible()
            rect = field.bounding_box()
            if not rect:
                raise AssertionError(f"Field {row['id']} has no measurable geometry")
            if touch:
                page.touchscreen.tap(rect["x"] + rect["width"] / 2,
                                     rect["y"] + rect["height"] / 2)
                record(name, "touchscreen.tap", row, caption.is_visible())
            else:
                page.mouse.move(rect["x"] + rect["width"] / 2,
                                rect["y"] + rect["height"] / 2)
                record(name, "page.mouse.move", row, caption.is_visible())
                field.focus()
                assert field.evaluate("n => document.activeElement === n")
                record(name, "keyboard focus", row, caption.is_visible())
                page.keyboard.press("Tab")
                record(name, "Tab", row, caption.is_visible())
        page.screenshot(path=str(OUT / f"{name}.png"))
        REPORT["browsers"].append(name)
    except Exception:
        page.screenshot(path=str(OUT / f"{name}-failure.png"))
        raise
    finally:
        context.close()


def smoke(browser, engine, workflow, port, text, expand=None):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.route("**/*", lambda route: local_only(route, port))
    try:
        page.goto(f"http://127.0.0.1:{port}", wait_until="domcontentloaded")
        if expand:
            page.get_by_text(expand, exact=True).click()
        from playwright.sync_api import expect
        expect(page.get_by_text(text, exact=True).first).to_be_visible(timeout=60000)
        if page.locator('[data-testid="stTooltipIcon"], [aria-label^="Help for"]').count():
            raise AssertionError("A native help icon remains in a real workflow")
        REPORT["checks"].append({"engine": engine, "input": "real workflow visible caption",
                                 "workflow": workflow, "passed": True})
        page.screenshot(path=str(OUT / f"{engine}-{workflow}-actual.png"))
    except Exception:
        page.screenshot(path=str(OUT / f"{engine}-{workflow}-failure.png"))
        raise
    finally:
        context.close()


def run_server(port, entry, root_prefix, tests):
    with tempfile.TemporaryDirectory(prefix=root_prefix) as temp:
        if root_prefix.startswith("expense"):
            (Path(temp) / ".synthetic-expense-fixture").write_text("synthetic-only")
        env = dict(os.environ)
        env.update(EPC_DATA_DIR=temp, ANTHROPIC_API_KEY="test-key-not-used",
                   SMARTSHEET_API_MODE="disabled", PDF_BACKEND="libreoffice")
        args = [sys.executable, "-m", "streamlit", "run", entry,
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
        if entry.endswith("qa_field_help.py"):
            args += ["--", "--fixture"]
        with (OUT / f"server-{port}.log").open("w") as log:
            process = subprocess.Popen(args, cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(200):
                    if process.poll() is not None:
                        raise RuntimeError(f"Local synthetic app {entry} stopped")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError(f"Local synthetic app {entry} did not start")
                tests()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)


def main():
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    rows = inventory()
    REPORT["inventory"] = rows
    try:
        with sync_playwright() as playwright:
            def galleries():
                for engine, browser_type in [("chromium", playwright.chromium),
                                              ("webkit", playwright.webkit)]:
                    browser = browser_type.launch(headless=True)
                    try:
                        exercise_gallery(browser, engine, {"width": 1440, "height": 900}, rows)
                        for viewport in ({"width": 820, "height": 1180},
                                         {"width": 390, "height": 844}):
                            exercise_gallery(browser, engine, viewport, rows, touch=True)
                    except Exception:
                        REPORT["failures"].append({"engine": engine,
                                                  "traceback": traceback.format_exc()})
                    finally:
                        browser.close()
            run_server(8526, "scripts/qa_field_help.py", "field-help-synthetic-", galleries)
            for workflow, port, entry, prefix, help_text, expanded in [
                ("po", 8527, "tests/fixtures/workspaces/po_app.py",
                 "po-adaptive-synthetic-",
                 "Review and correct the proposed work description. This text is copied into the supporting document.",
                 "Review scope, inclusions, and exclusions"),
                ("expense", 8528, "tests/fixtures/workspaces/expense_app.py",
                 "expense-adaptive-synthetic-",
                 "Upload images or PDFs that support this expense report. You can select several files, and each file may contain multiple pages.",
                 None)]:
                def integrated():
                    for engine, browser_type in [("chromium", playwright.chromium),
                                                  ("webkit", playwright.webkit)]:
                        browser = browser_type.launch(headless=True)
                        try:
                            smoke(browser, engine, workflow, port, help_text, expanded)
                        except Exception:
                            REPORT["failures"].append({"engine": engine, "workflow": workflow,
                                                      "traceback": traceback.format_exc()})
                        finally:
                            browser.close()
                run_server(port, entry, prefix, integrated)
    finally:
        (OUT / "results.json").write_text(json.dumps(REPORT, indent=2), encoding="utf-8")
    passes = sum(check["passed"] for check in REPORT["checks"])
    print(f"Field help: {passes} pass, {len(REPORT['failures'])} failed browser sessions")
    if REPORT["failures"]:
        raise AssertionError("Field help browser failures: " +
                             "; ".join(item.get("engine", "?") + "/" + item.get("workflow", "gallery")
                                       for item in REPORT["failures"]))


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        fixture()
    else:
        main()
