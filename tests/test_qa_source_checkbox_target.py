"""Replay's one native checkbox gesture targets its visible enclosing label."""
import ast
from pathlib import Path
from unittest.mock import Mock

import pytest


def action(namespace):
    path = Path(__file__).resolve().parents[1] / "scripts/qa_monthly_live.py"
    module = ast.parse(path.read_text())
    journey = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                   and n.name == "correct_replay_source_scope")
    # Execute the actual action after the last picker closes and before its
    # existing warning-clear/durable-result assertions, without a browser.
    starts = [i for i, n in enumerate(journey.body)
              if 'expect(page.get_by_role(\'listbox\')).to_have_count(0)' in ast.unparse(n)]
    start = starts[-1] + 1
    end = next(i for i in range(start, len(journey.body))
               if ast.unparse(journey.body[i]).startswith('expect(stale).to_have_count(0'))
    helpers = [n for n in module.body if isinstance(n, ast.FunctionDef)
               and n.name == "click_native_checkbox_label"]
    exec(compile(ast.Module(body=helpers + journey.body[start:end], type_ignores=[]),
                 str(path), "exec"), namespace)


def exercise(blocked=None):
    evidence, checkbox, label, label_inputs, source_pages, chip = (Mock() for _ in range(6))
    events = []
    evidence.get_by_role.side_effect = lambda role, **kw: (
        checkbox if role == "checkbox" and kw == {
            "name": "Remove unavailable source links", "exact": True} else pytest.fail("wrong checkbox"))
    checkbox.locator.side_effect = lambda selector: (
        label if selector == "xpath=ancestor::label" else pytest.fail("wrong label boundary"))
    label.get_by_role.side_effect = lambda role: (
        label_inputs if role == "checkbox" else pytest.fail("wrong native input"))
    source_pages.get_by_text.side_effect = lambda name, **kw: (
        chip if name == "synthetic-activity.txt · page 1" and kw == {"exact": True}
        else pytest.fail("wrong selected source"))
    checkbox.check.side_effect = AssertionError("clipped native input cannot receive a pointer")
    checkbox.click.side_effect = AssertionError("do not click clipped input")
    checkbox.press.side_effect = AssertionError("no keyboard fallback")

    def expectation(target):
        result = Mock()
        def count(value):
            assert value == 1 and target in (checkbox, label, label_inputs)
            reason = {id(checkbox): "duplicate checkbox", id(label): "missing or ambiguous label",
                      id(label_inputs): "label contains another checkbox"}[id(target)]
            if blocked == reason:
                raise AssertionError(reason)
            events.append(reason + " checked")
        def visible():
            assert target in (chip, label)
            reason = "current source not selected" if target is chip else "label hidden"
            if blocked == reason:
                raise AssertionError(reason)
            events.append(reason + " checked")
        def unchecked():
            assert target is checkbox
            if blocked == "already checked":
                raise AssertionError("already checked")
            events.append("initially unchecked")
        result.to_have_count.side_effect = count
        result.to_be_visible.side_effect = visible
        result.not_to_be_checked.side_effect = unchecked
        return result

    label.click.side_effect = lambda: events.append("one visible label pointer click")
    namespace = dict(evidence=evidence, source_pages=source_pages, expect=expectation)
    if blocked:
        with pytest.raises(AssertionError, match=blocked):
            action(namespace)
        label.click.assert_not_called()
    else:
        action(namespace)
        label.click.assert_called_once_with()
        assert events == ["current source not selected checked", "duplicate checkbox checked",
                          "initially unchecked", "missing or ambiguous label checked",
                          "label contains another checkbox checked", "label hidden checked",
                          "one visible label pointer click"]
    checkbox.check.assert_not_called()
    checkbox.click.assert_not_called()
    checkbox.press.assert_not_called()


def test_replay_clicks_the_exact_visible_native_label_once():
    exercise()


def test_one_current_source_choice_is_observed_before_tab_and_after_removal():
    path = Path(__file__).resolve().parents[1] / "scripts/qa_monthly_live.py"
    module = ast.parse(path.read_text())
    journey = next(n for n in module.body if isinstance(n, ast.FunctionDef)
                   and n.name == "correct_replay_source_scope")
    statements = [ast.unparse(n) for n in journey.body]
    choice = "page.get_by_role('option', name='synthetic-activity.txt · page 1', exact=True).click()"
    selected = "expect(source_pages.get_by_text('synthetic-activity.txt · page 1', exact=True)).to_be_visible()"
    assert statements.count(choice) == 1
    at = statements.index(choice)
    assert statements[at + 1:at + 3] == [selected, "page.keyboard.press('Tab')"]
    assert statements.count(selected) == 3  # Before Tab, after Tab, after removing obsolete links.


@pytest.mark.parametrize("blocked", ["current source not selected", "duplicate checkbox",
    "missing or ambiguous label", "label contains another checkbox", "label hidden", "already checked"])
def test_unready_or_ambiguous_checkbox_never_gets_a_gesture(blocked):
    exercise(blocked)


def test_source_correction_evidence_uploads_before_later_browser_steps():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/adaptive-workspaces.yml"
    workflow = path.read_text()
    expected = """        run: python scripts/qa_source_corrections.py
      - name: Upload source correction evidence immediately, including first failures
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: source-correction-browser-evidence-${{ github.run_attempt }}
          path: test-artifacts/source-corrections/
          retention-days: 7
          if-no-files-found: warn
      - name: Fresh ordinary Monthly site pointer and keyboard from zero
"""
    assert workflow.count(expected) == 1
    final = workflow.split("      - name: Upload synthetic screenshots and geometry\n", 1)[1]
    assert final.startswith("        if: always()\n        uses: actions/upload-artifact@v4\n")
    assert "            test-artifacts/source-corrections/\n" in final
    assert "permissions:\n  contents: read\n" in workflow
