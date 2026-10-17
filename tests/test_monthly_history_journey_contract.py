"""Run the exact history predicate with browser-serialized optional arguments."""
import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest


def expression():
    source = Path(__file__).resolve().parents[1] / 'scripts/qa_monthly_history.py'
    tree = ast.parse(source.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'await_state')
    return ast.literal_eval(function.body[0].value.args[0])


def run_predicate(state, wanted, *, running='notRunning', mounted=True):
    script = """const state=JSON.parse(process.argv[1]);
const document={querySelectorAll:()=>JSON.parse(process.argv[4])?[{dataset:{enfraHistoryReceipt:JSON.stringify(state)}}]:[],
querySelector:()=>({getAttribute:()=>process.argv[3]})};
const predicate=eval('('+process.argv[5]+')');
console.log(JSON.stringify(predicate(JSON.parse(process.argv[2]))));"""
    result = subprocess.run(['node', '-e', script, json.dumps(state), json.dumps(wanted), running,
        json.dumps(mounted), expression()], capture_output=True, text=True, check=True, timeout=5)
    return json.loads(result.stdout)


def current():
    working = {'author': 'author-hash', 'activity': 'activity-hash', 'photos': ['photo-one', 'photo-two']}
    return {'scope': 'synthetic-scope', 'sequence': 4, 'saved_revision': 3,
            'working': working, 'durable': deepcopy(working)}


def wanted():
    return {'scope': 'synthetic-scope', 'revision': 3, 'after': 3}


@pytest.mark.parametrize('explicit_null', [False, True])
def test_unrequested_fields_accept_omitted_or_null_browser_arguments(explicit_null):
    target = wanted()
    if explicit_null:
        target.update(author=None, activity=None, photos=None)
    assert run_predicate(current(), target)


def test_initial_empty_cookie_scope_matches_without_a_working_draft():
    state = dict(current(), saved_revision=0, working=None, durable=None)
    assert run_predicate(state, dict(wanted(), revision=0))


def test_optional_revision_can_be_omitted_while_exact_supplied_fields_still_match():
    target = wanted()
    del target['revision']
    target.update(author='author-hash', activity='activity-hash', photos=2)
    assert run_predicate(current(), target)


def test_supplied_zero_photos_is_an_exact_value_rather_than_an_unrequested_field():
    state = current()
    state['working']['photos'] = []
    state['durable']['photos'] = []
    assert run_predicate(state, dict(wanted(), author='author-hash', activity='activity-hash', photos=0))
    assert not run_predicate(current(), dict(wanted(), photos=0))


@pytest.mark.parametrize('field,bad', [('author', 'wrong-author'), ('activity', 'wrong-activity'),
                                      ('photos', 1), ('photos', 0), ('revision', 2),
                                      ('scope', 'another-cookie'), ('after', 4)])
def test_requested_identity_value_and_freshness_cannot_be_relaxed(field, bad):
    assert not run_predicate(current(), dict(wanted(), **{field: bad}))


@pytest.mark.parametrize('working_field', ['author', 'activity', 'photos'])
def test_matching_display_cannot_acknowledge_different_durable_work(working_field):
    state = current()
    state['durable'][working_field] = [] if working_field == 'photos' else 'older'
    assert not run_predicate(state, wanted())


@pytest.mark.parametrize('running,mounted', [('running', True), ('notRunning', False)])
def test_running_or_missing_receipt_cannot_acknowledge_history(running, mounted):
    assert not run_predicate(current(), wanted(), running=running, mounted=mounted)
