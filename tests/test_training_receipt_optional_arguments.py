"""Pinned Playwright Page forwarding omits nested None, not explicit zero/false.

Source: microsoft/playwright-python v1.58.0, _page.wait_for_function and
_helper.locals_to_params. Hosted call409/call827 both carried only reviews0 and
includedfalse; saved/previous were absent. This replay needs no native browser.
"""
import json
import subprocess
from typing import Dict

import pytest

from scripts import qa_training_source_review as qa


# Exact pinned helper body; Page calls this before Frame serialization.
def locals_to_params(args: Dict) -> Dict:
    copy = {}
    for key in args:
        if key == "self":
            continue
        if args[key] is not None:
            copy[key] = (
                args[key]
                if not isinstance(args[key], Dict)
                else locals_to_params(args[key])
            )
    return copy


def capture(**wanted):
    class Page:
        def wait_for_function(self, predicate, *, arg, timeout):
            self.predicate, self.payload, self.timeout = predicate, arg, timeout
        def evaluate(self, *args):
            return {}
    page = Page()
    qa.receipt(page, **wanted)
    assert page.timeout == 30000
    return page.predicate, page.payload


def evaluate(wanted, *, saved=0, reviews=0, included=False, previous="same", state="notRunning", transport=True):
    predicate,payload=capture(**wanted)
    if transport:
        payload=locals_to_params({"self":object(),"arg":payload})["arg"]
    value={"reviews":reviews,"saved_revision":saved,"tables":[{"rows":[["Synthetic drill"]]}] if included else [],
           "review_revision":previous}
    code="const document={body:{innerText:"+json.dumps(qa.RECEIPT_PREFIX+json.dumps(value))+"},querySelector:()=>({getAttribute:()=>"+json.dumps(state)+"})};"
    code+="console.log(JSON.stringify(("+predicate+")("+json.dumps(payload)+")));"
    result=subprocess.run(["node","-e",code],capture_output=True,text=True,check=True,timeout=5)
    return json.loads(result.stdout)


def test_actual_page_forwarding_retains_false_zero_and_omits_only_none():
    _,payload=capture(reviews=0,included=False)
    assert payload["wanted"]=={"reviews":0,"included":False,"saved":None,"previous":None}
    forwarded=locals_to_params({"self":object(),"arg":payload})["arg"]
    # Exactly the decoded arguments in both captured hosted wait calls.
    assert forwarded["wanted"]=={"reviews":0,"included":False}
    assert locals_to_params({"saved":0,"included":False,"previous":""})=={"saved":0,"included":False,"previous":""}


@pytest.mark.parametrize("transport",[False,True],ids=["explicit-null","actual-omitted"])
def test_omitted_saved_and_previous_are_optional_on_exact_initial_receipt(transport):
    assert evaluate({"reviews":0,"included":False},transport=transport) is True


@pytest.mark.parametrize("wanted,actual,expected",[
    ({},{},True),
    ({"saved":0},{"saved":0},True),
    ({"saved":0},{"saved":1},False),
    ({"saved":1},{"saved":0},False),
    ({"saved":False},{"saved":0},False),
    ({"saved":""},{"saved":0},False),
    ({"reviews":0},{"reviews":1},False),
    ({"reviews":False},{"reviews":0},False),
    ({"included":False},{"included":False},True),
    ({"included":False},{"included":True},False),
    ({"included":True},{"included":False},False),
    ({"previous_review":"same"},{"previous":"same"},False),
    ({"previous_review":"prior"},{"previous":"same"},True),
    ({"previous_review":""},{"previous":""},False),
    ({"reviews":0,"included":False},{"state":"running"},False),
])
def test_explicit_scalar_conditions_and_idle_state_are_not_truthiness(wanted,actual,expected):
    assert evaluate(wanted,**actual) is expected


def test_all_requested_conditions_must_match_together():
    wanted={"reviews":1,"included":True,"saved":1,"previous_review":"prior"}
    assert evaluate(wanted,reviews=1,included=True,saved=1,previous="changed") is True
    assert evaluate(wanted,reviews=1,included=True,saved=0,previous="changed") is False
    assert evaluate(wanted,reviews=1,included=True,saved=1,previous="prior") is False
