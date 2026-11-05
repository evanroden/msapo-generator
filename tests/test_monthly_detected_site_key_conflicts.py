"""Detected source-site identity conflicts must never become accepted site scope."""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest


COLLISION_APP = r"""
from types import SimpleNamespace
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_source_sites_ui import correct_detected_sites
from app.monthly_report_ui import _field

known = Facility("north", "Known North Campus", ("North Main", "North Annex"))
choice = st.selectbox("Detected site variant",
                      ("exact", "different title", "different aliases", "other detection"))
if choice == "different title":
    detected = Facility("north", "Other North Campus", known.aliases)
elif choice == "different aliases":
    detected = Facility("north", known.title, ("North Main", "Different Annex"))
elif choice == "other detection":
    detected = Facility("west", "Detected West Campus", ("West Unit",))
else:
    detected = known
profile = replace(synthetic_profiles()[0], facilities=(known,))
result = correct_detected_sites(
    SimpleNamespace(sha256="a" * 64), profile, ReportPeriod(2026, 9),
    (detected,), (known,), "key-collision", _field,
    source_view=SimpleNamespace(receipt_sha256="b" * 64))
st.session_state["accepted"] = tuple((s.key, s.title) for s in result) if result else None
"""


DETECTION_APP = r"""
from types import SimpleNamespace
from dataclasses import replace
import streamlit as st
from app.monthly_report_model import Facility, ReportPeriod, synthetic_profiles
from app.monthly_report_source_sites_ui import correct_detected_sites
from app.monthly_report_ui import _field

known = Facility("north", "Known North Campus", ("North Main",))
state = st.selectbox("Detected label revision",
                     ("original", "renamed", "aliases", "reorder-only"))
names = ("Outpost", "Outpost Building")
if state == "renamed":
    source = Facility("outpost", "New Outpost", names)
elif state == "aliases":
    source = Facility("outpost", "Synthetic Outpost", ("Outpost", "New Building"))
elif state == "reorder-only":
    source = Facility("outpost", "Synthetic Outpost", tuple(reversed(names)))
else:
    source = Facility("outpost", "Synthetic Outpost", names)
profile = replace(synthetic_profiles()[0], facilities=(known,))
result = correct_detected_sites(
    SimpleNamespace(sha256="c" * 64), profile, ReportPeriod(2026, 9),
    (source,), (known,), "source-descriptor", _field,
    source_view=SimpleNamespace(receipt_sha256="d" * 64))
st.session_state["accepted"] = tuple((s.key, s.title, s.aliases) for s in result) if result else None
"""


def app(script):
    result = AppTest.from_string(script, default_timeout=25).run()
    assert not result.exception
    return result


def confirm(app):
    next(b for b in app.button if b.label == "Confirm source sites").click().run()
    assert not app.exception


@pytest.mark.parametrize("variant", ("different title", "different aliases"))
def test_conflicting_known_and_detected_site_keys_disable_confirmation(variant):
    widget = app(COLLISION_APP)
    widget.selectbox[0].set_value(variant).run()
    assert not widget.exception
    submit = next(b for b in widget.button if b.label == "Confirm source sites")
    assert submit.disabled, "Conflicting physical sites must not share a selectable source key."
    assert any("conflict" in warning.value.lower() or "different site" in warning.value.lower()
               for warning in widget.warning)
    assert widget.session_state["accepted"] is None
    widget.run()
    assert widget.session_state["accepted"] is None


def test_exact_duplicate_site_definition_does_not_trigger_unnecessary_review():
    widget = app(COLLISION_APP)
    confirm(widget)
    assert widget.session_state["accepted"] == (("north", "Known North Campus"),)
    widget.run()
    assert widget.session_state["accepted"] == (("north", "Known North Campus"),)


def test_distinct_new_source_site_can_still_be_explicitly_confirmed():
    widget = app(COLLISION_APP)
    widget.selectbox[0].set_value("other detection").run()
    assert not widget.exception
    confirm(widget)
    assert widget.session_state["accepted"] == (("west", "Detected West Campus"),)


@pytest.mark.parametrize("variant", ("different title", "different aliases"))
def test_previously_confirmed_known_site_revoked_on_conflicting_detection(variant):
    widget = app(COLLISION_APP)
    confirm(widget)
    assert widget.session_state["accepted"] == (("north", "Known North Campus"),)
    widget.selectbox[0].set_value(variant).run()
    assert widget.session_state["accepted"] is None
    assert next(b for b in widget.button if b.label == "Confirm source sites").disabled
    widget.selectbox[0].set_value("exact").run()
    assert widget.session_state["accepted"] is None, "Returning to old source labels must not resurrect approval."


@pytest.mark.parametrize("variant", ("renamed", "aliases"))
def test_changed_unlisted_source_site_label_invalidates_prior_confirmation(variant):
    widget = app(DETECTION_APP)
    confirm(widget)
    assert widget.session_state["accepted"] is not None
    widget.selectbox[0].set_value(variant).run()
    assert not widget.exception
    assert widget.session_state["accepted"] is None
    widget.run()
    assert widget.session_state["accepted"] is None


@pytest.mark.parametrize("variant", ("renamed", "aliases"))
def test_reverting_detected_site_descriptor_requires_a_new_explicit_click(variant):
    widget = app(DETECTION_APP)
    confirm(widget)
    widget.selectbox[0].set_value(variant).run()
    assert widget.session_state["accepted"] is None
    widget.selectbox[0].set_value("original").run()
    assert widget.session_state["accepted"] is None
    confirm(widget)
    assert widget.session_state["accepted"][0][0] == "outpost"


def test_alias_list_reordering_does_not_revoke_same_source_site_consent():
    widget = app(DETECTION_APP)
    confirm(widget)
    prior = widget.session_state["accepted"]
    widget.selectbox[0].set_value("reorder-only").run()
    assert not widget.exception
    assert widget.session_state["accepted"][0][0:2] == prior[0][0:2]
    assert set(widget.session_state["accepted"][0][2]) == set(prior[0][2])


def test_conflict_blocks_active_operator_selection_not_only_automatic_default():
    widget = app(COLLISION_APP)
    widget.selectbox[0].set_value("different title").run()
    assert widget.session_state["accepted"] is None
    selector = next(w for w in widget.multiselect
                    if w.label == "Actual sites covered by the uploaded report")
    selector.set_value(["north"]).run()
    assert widget.session_state["accepted"] is None
    assert next(b for b in widget.button if b.label == "Confirm source sites").disabled


def test_distinct_source_and_target_sites_preserve_last_explicit_selection():
    widget = app(DETECTION_APP)
    selector = next(w for w in widget.multiselect
                    if w.label == "Actual sites covered by the uploaded report")
    selector.set_value(["north"]).run()
    confirm(widget)
    assert widget.session_state["accepted"] == (("north", "Known North Campus", ("North Main",)),)
    widget.run()
    assert widget.session_state["accepted"][0][0] == "north"
