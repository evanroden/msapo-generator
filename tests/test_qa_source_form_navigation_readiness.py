"""Replay must visit the exact source owner before it checks a native buffer."""
import ast
from pathlib import Path


def statements():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_live.py').read_text())
    fn = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == 'correct_replay_source_scope')
    return [ast.unparse(x) for x in fn.body]


def test_corrected_form_is_bound_to_warning_source_not_any_visible_form():
    body = '\n'.join(statements())
    assert "correction.locator('.enfra-source-warning').get_attribute('data-source-id')" in body
    assert "owner = page.locator('[class*=\"_managed_source_' + source_id + '\"]')" in body
    assert "details = owner.locator('[data-testid=\"stForm\"]')" in body
    assert 'details = details.filter(visible=True)' not in body


def test_each_file_gesture_finishes_navigation_before_next_action():
    body = statements()
    away = body.index("page.get_by_role('option', name=other, exact=True).click()")
    back = body.index("page.get_by_role('option', name='synthetic-activity.txt', exact=True).click()")
    assert body[away + 1] == 'expect(details).to_be_hidden(timeout=25000)'
    assert body[back + 1] == 'expect(details).to_be_visible(timeout=25000)'
    for index in (away, back):
        assert body[index + 2].startswith('page.wait_for_function(')
        assert 'notRunning' in body[index + 2]
    assert "expect(sites.get_by_text('Demo North', exact=True)).to_be_visible()" in body
    assert 'el === original && el.isConnected' in '\n'.join(body)


def test_readiness_adds_no_sleep_retry_input_replacement_or_submission():
    body = statements()
    assert not any(x.startswith(('time.sleep(', 'for ', 'while ')) for x in body)
    assert sum(x == "page.get_by_role('option', name=other, exact=True).click()" for x in body) == 1
    assert sum(x == "page.get_by_role('option', name='synthetic-activity.txt', exact=True).click()" for x in body) == 1
    assert sum(x == "details.get_by_role('button', name='Use these source details', exact=True).click()" for x in body) == 1
    assert sum(x == "combo.fill('Demo North')" for x in body) == 1
