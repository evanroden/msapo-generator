"""Object Account and Agreement Type are operator-editable, not derived-only.

Reported: ISDC-funded work could not be processed at all. The job number was
never the problem -- RRH-695400030-ISDC is offered normally. The blocker was
downstream: both coding fields were derived solely from the four-way purchase
route, with no operator override, so two values the Smartsheet form legitimately
accepts were UNREACHABLE:

    Object Account   form accepts 6, tool could emit 4   -> 5490-OTHER missing
    Agreement Type   form accepts 7, tool could emit 5   -> CSAPO missing

Which coding a job takes depends on the contract vehicle -- whether there is an
MSA or a CSA with that customer -- and on whether the vendor is coming onsite.
No text rule can see any of that, which is why deriving alone was never going to
be sufficient.

The 2026-08-04 handoff specified this editability: "Object account remains
editable on the handoff page because a person may need one of the other
confirmed account choices." It was lost in the Smartsheet transition.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest

from app.po_context import build_po_context
from app.po_rules import PURCHASE_ROUTES, classify_po
from app.smartsheet import AGREEMENT_TYPE_OPTIONS, OBJECT_ACCOUNT_OPTIONS

ROOT = Path(__file__).resolve().parents[1]


def _started_app() -> AppTest:
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=60)
    for key, value in dotenv_values(ROOT / ".env.example").items():
        if value is not None:
            app.session_state[key] = value
    app.run()
    app.button[0].click().run()  # byline -> synthetic sample quote
    return app


def _selector(app: AppTest, label: str):
    return next(widget for widget in app.selectbox if widget.label == label)


def _state(app: AppTest) -> dict:
    return {key: app.session_state[key] for key in app.session_state.filtered_state}


def test_every_confirmed_form_option_is_reachable():
    """The regression in one assertion. Deriving from four routes could not
    produce 5490-OTHER or CSAPO, so any funding stream needing them was stuck."""
    app = _started_app()
    assert set(_selector(app, "Object Account").options) == set(OBJECT_ACCOUNT_OPTIONS)
    assert set(_selector(app, "Agreement Type for PO").options) == set(
        AGREEMENT_TYPE_OPTIONS
    )


def test_an_isdc_job_can_be_coded_and_reaches_the_smartsheet_fields():
    """End to end: the operator picks the ISDC coding and it survives into the
    package Smartsheet receives, rather than being overwritten by the route."""
    app = _started_app()
    _selector(app, "Object Account").set_value("5490-OTHER").run()
    _selector(app, "Agreement Type for PO").set_value("03 - CSAPO (CONSTRUCTION)").run()

    context = build_po_context(_state(app))
    assert context.fields["object_account"] == "5490-OTHER"
    assert context.fields["agreement_type"] == "03 - CSAPO (CONSTRUCTION)"


def test_an_untouched_request_still_gets_the_route_derived_pair():
    """The common case must need no interaction. This is also the guard against
    reintroducing the "5511-Subcontractor every single time" defect from the
    opposite direction -- the default still comes from the route."""
    app = _started_app()
    assert _selector(app, "Object Account").value == "5511-SUBCONTRACTOR"
    assert _selector(app, "Agreement Type for PO").value == "03 - MSAPO (SERVICE)"

    context = build_po_context(_state(app))
    assert context.fields["object_account"] == "5511-SUBCONTRACTOR"
    assert context.fields["agreement_type"] == "03 - MSAPO (SERVICE)"


def test_an_untouched_field_follows_a_changed_route():
    """Track-the-default: a field still holding the previous default follows a
    new one. Plain setdefault would freeze the first route's coding in place and
    silently contradict the route shown beside it."""
    app = _started_app()
    assert _selector(app, "Object Account").value == "5511-SUBCONTRACTOR"

    route = next(
        widget
        for widget in app.selectbox
        if "how will this work or purchase be handled" in widget.label.lower()
    )
    route.set_value("Buying materials or parts; no vendor labor onsite").run()

    assert _selector(app, "Object Account").value == "5301-MATERIALS"


def test_an_operator_choice_survives_a_route_change():
    """The other half of the protocol. Someone who deliberately coded a job
    5490-OTHER must not have it silently rewritten by touching the route."""
    app = _started_app()
    _selector(app, "Object Account").set_value("5490-OTHER").run()

    route = next(
        widget
        for widget in app.selectbox
        if "how will this work or purchase be handled" in widget.label.lower()
    )
    route.set_value("Buying materials or parts; no vendor labor onsite").run()

    assert _selector(app, "Object Account").value == "5490-OTHER"
    assert build_po_context(_state(app)).fields["object_account"] == "5490-OTHER"


def test_temporary_invalid_amount_does_not_turn_defaults_into_na_overrides():
    """NA is a display fallback while classification is impossible, not proof
    that the operator deliberately selected NA. Restoring the amount must
    restore both route-derived defaults."""
    app = _started_app()
    amount_label = "PO/CO amount — final total including every fee and tax *"
    amount = next(field for field in app.text_input if field.label == amount_label)
    original_amount = amount.value

    amount.set_value("").run()
    assert _selector(app, "Object Account").value == "NA"
    assert _selector(app, "Agreement Type for PO").value == "NA"

    amount = next(field for field in app.text_input if field.label == amount_label)
    amount.set_value(original_amount).run()

    assert _selector(app, "Object Account").value == "5511-SUBCONTRACTOR"
    assert _selector(app, "Agreement Type for PO").value == "03 - MSAPO (SERVICE)"
    context = build_po_context(_state(app))
    assert context.fields["object_account"] == "5511-SUBCONTRACTOR"
    assert context.fields["agreement_type"] == "03 - MSAPO (SERVICE)"


def test_operator_coding_survives_expense_workflow_round_trip():
    """PO selectboxes do not render on the expense branch, so their widget keys
    are collected by Streamlit. The non-widget mirror must restore the explicit
    financial coding when the operator returns."""
    app = _started_app()
    _selector(app, "Object Account").set_value("5490-OTHER").run()
    _selector(app, "Agreement Type for PO").set_value(
        "03 - CSAPO (CONSTRUCTION)"
    ).run()

    app.segmented_control[0].set_value("Expense reimbursement").run()
    app.segmented_control[0].set_value("Purchase order").run()

    assert _selector(app, "Object Account").value == "5490-OTHER"
    assert _selector(app, "Agreement Type for PO").value == (
        "03 - CSAPO (CONSTRUCTION)"
    )
    context = build_po_context(_state(app))
    assert context.fields["object_account"] == "5490-OTHER"
    assert context.fields["agreement_type"] == "03 - CSAPO (CONSTRUCTION)"


def test_reselecting_the_current_default_resumes_following_route_defaults():
    """An override is explicit state, but it is not irreversible. Choosing the
    current derived value again clears the override and later route changes
    should follow the matrix."""
    app = _started_app()
    account = _selector(app, "Object Account")
    account.set_value("5490-OTHER").run()
    _selector(app, "Object Account").set_value("5511-SUBCONTRACTOR").run()

    route = next(
        widget
        for widget in app.selectbox
        if "how will this work or purchase be handled" in widget.label.lower()
    )
    route.set_value("Buying materials or parts; no vendor labor onsite").run()

    assert _selector(app, "Object Account").value == "5301-MATERIALS"


def test_malformed_or_obsolete_coding_mirror_recovers_and_stays_bounded(monkeypatch):
    import app.web_ui as web_ui

    state = {
        "_po_coding_draft": {
            "old-token": {"object_account": {"value": "5490-OTHER"}},
            "active-token": "corrupted",
        }
    }
    monkeypatch.setattr(web_ui.st, "session_state", state)

    value = web_ui._sync_po_coding_field(
        "active-token", "object_account", "5511-SUBCONTRACTOR"
    )

    assert value == "5511-SUBCONTRACTOR"
    assert state["object_account_active-token"] == "5511-SUBCONTRACTOR"
    assert set(state["_po_coding_draft"]) == {"active-token"}


@pytest.mark.parametrize("route", PURCHASE_ROUTES)
def test_the_derived_default_still_matches_the_routing_matrix(route):
    """The business matrix is UNCHANGED by this feature -- only who gets the
    last word. classify_po remains the source of the default."""
    expected = classify_po(route, "1000.00")
    assert expected.object_account in OBJECT_ACCOUNT_OPTIONS
    assert expected.agreement_type in AGREEMENT_TYPE_OPTIONS


def test_a_stale_value_outside_the_catalog_falls_back_rather_than_being_sent():
    """Streamlit keeps widget state for keys whose widgets did not render, and
    Smartsheet rejects a dropdown value that is not character-for-character an
    option -- which surfaces as a failed submission, after the operator has left
    the page."""
    app = _started_app()
    token = app.session_state["analysis_token"]
    state = _state(app)
    state[f"object_account_{token}"] = "5490 OTHER"  # space, not hyphen

    context = build_po_context(state)
    assert context.fields["object_account"] == "5511-SUBCONTRACTOR"
