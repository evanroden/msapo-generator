"""Fast scope checks; actual visibility/input is tested by qa_sidebar_navigation."""
import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.web_ui import CUSTOM_CSS
from scripts.qa_sidebar_navigation import FIXTURE


ROOT = Path(__file__).parents[1]


def test_only_native_sidebar_opener_overrides_hidden_header():
    css = re.sub(r"/\*.*?\*/", "", CUSTOM_CSS, flags=re.S)
    visible = [selector.strip() for selector, rule in
               re.findall(r"([^{}]+)\{([^{}]*)\}", css)
               if re.search(r"\bvisibility\s*:\s*visible\b", rule)]
    assert visible == [
        '[data-testid="stHeader"] [data-testid="stExpandSidebarButton"]']
    assert "#MainMenu, footer, header {visibility: hidden;}" in css


def test_synthetic_fixture_uses_native_sidebar_and_only_session_navigation():
    app = AppTest.from_string(FIXTURE, default_timeout=20).run()
    assert not app.exception
    assert app.sidebar.expander[0].label == "Administration"
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert app.session_state["sidebar_destination"] == "Synthetic branding"
    app.sidebar.button[1].click().run()
    assert not app.exception
    assert app.session_state["sidebar_destination"] == "Synthetic master templates"


def test_header_clearance_is_limited_to_narrow_workflows_with_a_sidebar():
    selector = '.stApp:has([data-testid="stSidebar"]) .block-container {'
    narrow = CUSTOM_CSS.split("@media (max-width: 1100px) {", 1)[1]
    assert narrow.lstrip().startswith(selector)
    assert "padding-top: 3.75rem !important;" in narrow.split(selector, 1)[1].split("}", 1)[0]


def test_native_browser_regression_remains_in_hosted_dom_job():
    workflow = (ROOT / ".github/workflows/adaptive-workspaces.yml").read_text()
    assert workflow.count("- 'scripts/qa_sidebar_navigation.py'") == 2
    assert workflow.count("- 'tests/test_sidebar_navigation.py'") == 2
    step = workflow.split("      - name: Native sidebar visibility and pointer/keyboard navigation\n", 1)[1].split("      - ", 1)[0]
    assert "if: ${{ !cancelled() }}" in step
    assert "timeout-minutes: 26" in step
    assert "python scripts/ci_native_test_budget.py --minutes 25 <<'NATIVE_TEST'" in step
    assert "          python scripts/qa_sidebar_navigation.py\n          NATIVE_TEST" in step
