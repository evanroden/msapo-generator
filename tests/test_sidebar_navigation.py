"""Fast scope checks; actual visibility/input is tested by qa_sidebar_navigation."""
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from streamlit.testing.v1 import AppTest
import pytest

from app.web_ui import CUSTOM_CSS
from scripts import qa_sidebar_navigation as navigation
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
    assert len(app.get("link_button")) == 4


def test_header_clearance_covers_shared_shell_with_a_sidebar():
    selector = '.stApp:has([data-testid="stSidebar"]) .block-container {'
    narrow = CUSTOM_CSS.split("@media (max-width: 1780px) {", 1)[1]
    assert narrow.lstrip().startswith(selector)
    assert "padding-top: 3.75rem !important;" in narrow.split(selector, 1)[1].split("}", 1)[0]


def test_only_collapsed_sidebar_subtree_is_removed_from_focus():
    assert CUSTOM_CSS.count(navigation.COLLAPSED_SIDEBAR_RULE) == 1
    assert '[aria-expanded="true"]' not in navigation.COLLAPSED_SIDEBAR_RULE
    assert "stExpandSidebarButton" not in navigation.COLLAPSED_SIDEBAR_RULE
    assert "visibility: hidden;" in navigation.COLLAPSED_SIDEBAR_RULE
    assert '[aria-expanded="false"] *' in navigation.COLLAPSED_SIDEBAR_RULE


@pytest.mark.parametrize("hidden_stop", [False, True])
@pytest.mark.parametrize("key", ["Tab", "Shift+Tab"])
def test_tab_gate_rejects_any_collapsed_sidebar_stop(hidden_stop, key):
    page = Mock()
    control = Mock()
    page.evaluate.side_effect = [{"insideCollapsedSidebar": hidden_stop},
                                 {"insideCollapsedSidebar": False}]
    control.evaluate.side_effect = [False, True]
    record = []
    if hidden_stop:
        with pytest.raises(navigation.CollapsedSidebarFocusError, match="received Tab focus"):
            navigation.tab_to_control(page, control, record, key=key)
        control.evaluate.assert_not_called()
        assert len(record) == 1
    else:
        navigation.tab_to_control(page, control, record, key=key)
        assert len(record) == 2
    for call in page.keyboard.press.call_args_list:
        assert call.args == (key,) and not call.kwargs


def test_tab_gate_does_not_accept_an_unreachable_control():
    page = Mock()
    control = Mock()
    page.evaluate.return_value = {"insideCollapsedSidebar": False}
    control.evaluate.return_value = False
    with pytest.raises(AssertionError, match="unreachable by Tab"):
        navigation.tab_to_control(page, control, [])
    assert page.keyboard.press.call_count == 30


def test_native_browser_regression_remains_in_hosted_dom_job():
    workflow = (ROOT / ".github/workflows/adaptive-workspaces.yml").read_text()
    assert workflow.count("- 'scripts/qa_sidebar_navigation.py'") == 2
    assert workflow.count("- 'tests/test_sidebar_navigation.py'") == 2
    step = workflow.split("      - name: Native sidebar visibility and pointer/keyboard navigation\n", 1)[1].split("      - ", 1)[0]
    assert "if: ${{ !cancelled() }}" in step
    assert "timeout-minutes: 26" in step
    assert "python scripts/ci_native_test_budget.py --minutes 25 <<'NATIVE_TEST'" in step
    assert "          python scripts/qa_sidebar_navigation.py\n          NATIVE_TEST" in step


@pytest.mark.parametrize("after_hit", [True, False])
def test_actionability_wait_preserves_the_final_hit_assertion(monkeypatch, after_hit):
    calls = []
    class Opener:
        def click(self, **options):
            calls.append(options)
    opener = Opener()
    class Page:
        def get_by_test_id(self, testid):
            assert testid == "stExpandSidebarButton"
            return opener
    states = iter([{"ownsHit": False},
                   {"visibility": "visible", "inViewport": True, "ownsHit": after_hit}])
    monkeypatch.setattr(navigation, "inspect_opener", lambda page: next(states))
    record = {}
    if after_hit:
        assert navigation.actionable_opener(Page(), record) is opener
    else:
        with pytest.raises(AssertionError):
            navigation.actionable_opener(Page(), record)
    assert calls == [{"trial": True, "timeout": 5000}]
    assert record["before_actionability"]["ownsHit"] is False
    assert record["after_actionability"]["ownsHit"] is after_hit


def test_permanently_obstructed_opener_does_not_pass(monkeypatch):
    calls = []
    class Page:
        def get_by_test_id(self, testid):
            assert testid == "stExpandSidebarButton"
            return self
        def click(self, **options):
            calls.append(options)
            raise TimeoutError("Another element still intercepts pointer events")
    monkeypatch.setattr(navigation, "inspect_opener", lambda page: {"ownsHit": False})
    record = {}
    with pytest.raises(TimeoutError, match="intercepts pointer events"):
        navigation.actionable_opener(Page(), record)
    assert calls == [{"trial": True, "timeout": 5000}]
    assert record == {"before_actionability": {"ownsHit": False}}


def test_sidebar_evidence_upload_is_immediate_even_on_failure():
    workflow = (ROOT / ".github/workflows/adaptive-workspaces.yml").read_text()
    journey = workflow.index("      - name: Native sidebar visibility and pointer/keyboard navigation\n")
    upload = workflow.index("      - name: Upload native sidebar evidence immediately, including first failures\n")
    following = workflow.index("      - name: Actual Expense workflow with isolated synthetic inputs\n")
    assert journey < upload < following
    step = workflow[upload:following]
    assert "if: always()" in step and "timeout-minutes: 3" in step
    assert "name: native-sidebar-browser-evidence-${{ github.run_attempt }}" in step
    assert workflow.count("test-artifacts/sidebar-navigation/") == 2


@pytest.mark.parametrize("readiness", ["ready", "missing", "hidden"])
def test_workflow_geometry_waits_for_all_native_radios(monkeypatch, readiness):
    calls = []
    geometry = [{"area": 0}] * 3
    class Radios:
        def nth(self, index):
            return index
    radios = Radios()
    class Workflow:
        def locator(self, selector):
            assert selector == 'button[role="radio"]'
            return radios
        def evaluate(self, script):
            calls.append("geometry")
            assert "getBoundingClientRect" in script and "querySelectorAll" in script
            return geometry
    workflow = Workflow()
    class Page:
        def locator(self, selector):
            assert selector == ".st-key-workflow_mode"
            return workflow
    class Expectation:
        def __init__(self, target):
            self.target = target
        def to_have_count(self, count, *, timeout):
            assert self.target is radios
            calls.append(("count", count, timeout))
            if readiness == "missing":
                raise AssertionError("Native radios did not hydrate")
        def to_be_visible(self, *, timeout):
            calls.append(("visible", self.target, timeout))
            if readiness == "hidden" and self.target == 1:
                raise AssertionError("Native radio remained hidden")
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(expect=Expectation))
    if readiness == "ready":
        assert navigation.inspect_workflow_overlap(Page()) is geometry
        assert calls == [("count", 3, 5000), ("visible", 0, 5000),
                         ("visible", 1, 5000), ("visible", 2, 5000), "geometry"]
    else:
        with pytest.raises(AssertionError, match="Native radio"):
            navigation.inspect_workflow_overlap(Page())
        assert calls[0] == ("count", 3, 5000)
        assert "geometry" not in calls


@pytest.mark.parametrize("readiness", ["quiet", "missing", "visible"])
def test_quiet_chrome_waits_for_fragments_without_skipping_visibility(monkeypatch, readiness):
    page = Mock()
    node = Mock()
    node.evaluate.return_value = "visible" if readiness == "visible" else "hidden"
    page.locator.return_value.all.return_value = [node]
    page.get_by_role.return_value.count.return_value = 0
    expectation = Mock()
    if readiness == "missing":
        expectation.to_have_count.side_effect = AssertionError("Fragment did not hydrate")
    expect = Mock(return_value=expectation)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(expect=expect))
    if readiness == "quiet":
        navigation.require_quiet_chrome(page)
    else:
        with pytest.raises(AssertionError):
            navigation.require_quiet_chrome(page)
    assert expectation.to_have_count.call_count == (1 if readiness == "missing" else 3)
    for call in expectation.to_have_count.call_args_list:
        assert call.args == (1,) and call.kwargs == {"timeout": 5000}
    if readiness == "missing":
        node.evaluate.assert_not_called()
    else:
        node.evaluate.assert_called()
