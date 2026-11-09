"""Validate the proposed browser evidence gates, not browser acceptance itself."""
import ast
from pathlib import Path
import subprocess

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_adaptive.py'
TREE = ast.parse(SOURCE.read_text())


def function(name):
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    return namespace[name]


valid = function('navigation_hit_is_valid')
activated = function('navigation_hit_activated')


def sample(review=False):
    return {'point': [900, 85], 'band': {'left': 380, 'right': 1360, 'top': 60, 'bottom': 110},
            'target': {'left': 380, 'right': 1360, 'top': 70, 'bottom': 108},
            'capsule': {'right': 780}, 'viewport': {'width': 1440, 'height': 480},
            'connected': True, 'owns_hit': True, 'mode': 'wide', 'review_open': review,
            'wrapper_position': 'sticky', 'capsule_position': 'fixed' if review else 'static'}


@pytest.mark.parametrize('review', [False, True])
def test_real_empty_wrapper_point_accepts_sticky_or_fixed_state(review):
    assert valid(sample(review), review)


def test_review_uses_fixed_band_even_when_editor_wrapper_is_offscreen():
    observed = sample(True)
    observed['wrapper'] = {'left': 380, 'right': 1360, 'top': -152, 'bottom': -102}
    assert valid(observed, True)
    observed['review_open'] = False
    observed['capsule_position'] = 'static'
    observed['band'] = observed['wrapper']
    assert not valid(observed, False)


@pytest.mark.parametrize('key,value', [
    ('connected', False), ('owns_hit', False), ('mode', 'compact'),
    ('review_open', True), ('wrapper_position', 'static'), ('capsule_position', 'fixed'),
    ('point', [900, 120]), ('point', [379, 85]), ('point', [780, 85]),
    ('point', [1361, 85]), ('point', [900, 65]),
    ('viewport', {'width': 800, 'height': 480}),
    ('viewport', {'width': 1440, 'height': 80}),
])
def test_occlusion_clipping_wrong_mode_and_offscreen_points_fail(key, value):
    observed = sample()
    observed[key] = value
    assert not valid(observed, False)


def receipt():
    return {'same_node': True, 'connected': True, 'focused': True, 'details_open': None,
            'events': [{'type': kind, 'trusted': True, 'owned': True}
                       for kind in ['pointerdown', 'pointerup', 'click']]}


def test_exactly_one_trusted_native_textarea_activation_passes():
    assert activated(receipt(), 'textarea')


@pytest.mark.parametrize('key,value', [('same_node', False), ('connected', False), ('focused', False)])
def test_replaced_detached_or_unfocused_input_fails(key, value):
    observed = receipt()
    observed[key] = value
    assert not activated(observed, 'textarea')


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('key', ['trusted', 'owned'])
def test_each_event_must_be_trusted_and_reach_the_actual_control(index, key):
    observed = receipt()
    observed['events'][index][key] = False
    assert not activated(observed, 'textarea')


@pytest.mark.parametrize('edit', ['missing', 'duplicate', 'reordered'])
def test_missing_replayed_or_reordered_gestures_fail(edit):
    observed = receipt()
    events = observed['events']
    observed['events'] = events[:-1] if edit == 'missing' else events*2 if edit == 'duplicate' else list(reversed(events))
    assert not activated(observed, 'textarea')


@pytest.mark.parametrize('before,after,passes', [
    (False, True, True), (True, False, True), (False, False, False), (True, True, False),
    (None, True, False), (False, None, False), (False, 1, False),
])
def test_review_requires_a_real_disclosure_state_change(before, after, passes):
    observed = receipt()
    observed['details_open'] = after
    assert activated(observed, 'summary', before) is passes


def test_all_new_browser_callbacks_have_valid_javascript_syntax():
    node = next(n for n in TREE.body if isinstance(n, ast.FunctionDef)
                and n.name == 'exercise_navigation_click_through')
    callbacks = [ast.literal_eval(call.args[0]) for call in ast.walk(node)
                 if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                 and call.func.attr == 'evaluate' and call.args
                 and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)]
    assert len(callbacks) == 4
    for callback in callbacks:
        subprocess.run(['node', '-e', 'new Function("return ("+process.argv[1]+")");', callback],
                       check=True, capture_output=True, text=True, timeout=5)
