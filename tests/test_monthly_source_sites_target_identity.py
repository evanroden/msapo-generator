"""Target-site metadata is part of the explicit source-membership consent."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_source_sites_ui import correction_scope, source_review_epoch

PERIOD = ReportPeriod(2026, 9)
ORIGINAL = Facility("north", "Synthetic North", ("North campus", "North unit"))
UNCHANGED = Facility("south", "Synthetic South", ("South campus",))
INSPECTION = SimpleNamespace(sha256="a" * 64)
VIEW = SimpleNamespace(receipt_sha256="b" * 64)


def target(*facilities):
    return replace(synthetic_profiles()[0], facilities=facilities)


@pytest.mark.parametrize("changed", [
    Facility("north", "Renamed North", ORIGINAL.aliases),
    Facility("north", ORIGINAL.title, ("North campus", "Revised North unit")),
    Facility("north", ORIGINAL.title, ("North campus",)),
])
def test_scope_rejects_target_title_or_alias_change_even_when_keys_match(changed):
    original = correction_scope(INSPECTION, target(ORIGINAL), PERIOD, VIEW)
    revised = correction_scope(INSPECTION, target(changed), PERIOD, VIEW)
    assert revised != original, "A changed target site must require a new source-membership decision."
    assert revised == correction_scope(INSPECTION, target(changed), PERIOD, VIEW)


def test_scope_is_independent_of_facility_and_alias_order():
    a = correction_scope(INSPECTION, target(ORIGINAL, UNCHANGED), PERIOD, VIEW)
    reordered = Facility("north", ORIGINAL.title, tuple(reversed(ORIGINAL.aliases)))
    b = correction_scope(INSPECTION, target(UNCHANGED, reordered), PERIOD, VIEW)
    assert a == b


@pytest.mark.parametrize("changed", [
    SimpleNamespace(sha256="c" * 64),
    None,
])
def test_source_identity_and_view_receipt_remain_bound(changed):
    original = correction_scope(INSPECTION, target(ORIGINAL), PERIOD, VIEW)
    updated = correction_scope(changed or INSPECTION, target(ORIGINAL), PERIOD,
                               VIEW if changed is not None else SimpleNamespace(receipt_sha256="new"))
    assert updated != original


def test_period_and_contract_are_still_bound():
    original = correction_scope(INSPECTION, target(ORIGINAL), PERIOD, VIEW)
    assert original != correction_scope(INSPECTION, target(ORIGINAL), ReportPeriod(2026, 10), VIEW)
    assert original != correction_scope(INSPECTION,
        replace(target(ORIGINAL), contract="Other synthetic contract"), PERIOD, VIEW)


APP = r"""
from dataclasses import replace
from types import SimpleNamespace
import streamlit as st
from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_source_sites_ui import correct_detected_sites, source_review_epoch
from app.monthly_report_ui import _field

base = Facility("north", "Synthetic North", ("North campus", "North unit"))
state = st.selectbox("Target site metadata",
                     ("original", "renamed", "aliases", "reordered"))
if state == "renamed":
    current = Facility("north", "Renamed North", base.aliases)
elif state == "aliases":
    current = Facility("north", base.title, ("North campus", "Revised North unit"))
elif state == "reordered":
    current = Facility("north", base.title, tuple(reversed(base.aliases)))
else:
    current = base
report = replace(synthetic_profiles()[0], facilities=(current,))
inspection = SimpleNamespace(sha256="a" * 64)
view = SimpleNamespace(receipt_sha256="b" * 64)
sites = correct_detected_sites(
    inspection, report, ReportPeriod(2026, 9), (base,), (base,),
    "target-meta", _field, source_view=view)
st.session_state["confirmed_sites"] = tuple(s.key for s in sites) if sites else None
st.session_state["site_epoch"] = source_review_epoch(
    inspection, report, ReportPeriod(2026, 9),
    sites or (base,), "same", source_view=view)
st.text_input("Current source section edit", key="source_section_" + st.session_state["site_epoch"])
"""


def open_app():
    app = AppTest.from_string(APP, default_timeout=25).run()
    assert not app.exception
    assert app.session_state["confirmed_sites"] is None
    return app


def confirm(app):
    next(w for w in app.button if w.label == "Confirm source sites").click().run()
    assert not app.exception
    assert app.session_state["confirmed_sites"] == ("north",)


@pytest.mark.parametrize("kind", ["renamed", "aliases"])
def test_target_metadata_change_revokes_visible_confirmation_and_epoch(kind):
    app = open_app()
    confirm(app)
    old_epoch = app.session_state["site_epoch"]
    app.selectbox[0].set_value(kind).run()
    assert not app.exception
    assert app.session_state["confirmed_sites"] is None
    assert app.session_state["site_epoch"] != old_epoch
    app.run()
    assert app.session_state["confirmed_sites"] is None


@pytest.mark.parametrize("kind", ["renamed", "aliases"])
def test_returning_to_prior_site_metadata_does_not_resurrect_approval(kind):
    app = open_app()
    confirm(app)
    app.selectbox[0].set_value(kind).run()
    assert app.session_state["confirmed_sites"] is None
    app.selectbox[0].set_value("original").run()
    assert not app.exception
    assert app.session_state["confirmed_sites"] is None
    confirm(app)
    assert app.session_state["confirmed_sites"] == ("north",)


def test_nonsemantic_alias_reorder_retains_current_explicit_approval():
    app = open_app()
    confirm(app)
    old_epoch = app.session_state["site_epoch"]
    app.selectbox[0].set_value("reordered").run()
    assert not app.exception
    assert app.session_state["confirmed_sites"] == ("north",)
    assert app.session_state["site_epoch"] == old_epoch


def test_stale_source_section_input_cannot_rebind_after_site_rename():
    app = open_app()
    confirm(app)
    first_epoch = app.session_state["site_epoch"]
    next(w for w in app.text_input if w.label == "Current source section edit").set_value(
        "Old unpublished section choice").run()
    assert app.session_state["site_epoch"] == first_epoch
    app.selectbox[0].set_value("renamed").run()
    assert not app.exception
    assert app.session_state["site_epoch"] != first_epoch
    assert next(w for w in app.text_input if w.label == "Current source section edit").value == ""
    assert app.session_state["confirmed_sites"] is None
    confirm(app)


def test_changing_unrelated_same_source_controls_does_not_reset_confirmation():
    app = open_app()
    confirm(app)
    previous_epoch = app.session_state["site_epoch"]
    next(w for w in app.text_input if w.label == "Current source section edit").set_value(
        "Delivered section edit").run()
    assert app.session_state["confirmed_sites"] == ("north",)
    assert app.session_state["site_epoch"] == previous_epoch
    assert next(w for w in app.text_input if w.label == "Current source section edit").value == "Delivered section edit"
