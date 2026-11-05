"""Saved contact cards display source strings literally without changing identities.

These synthetic Streamlit actions cover ordinary contacts, vendor trade groups,
custom heading labels, and unchanged raw editing/persistence inputs.
"""
from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable
from app.monthly_report_ui_text import literal


CARD_APP = """
import streamlit as st
from app.monthly_report_contact_cards_ui import edit_contact_tables
from app.monthly_report_visual_ui import _contact_label
from app.monthly_report_ui import _field

tables, pending = edit_contact_tables(
    st.session_state["original_tables"], "synthetic_literal_cards",
    _field, _contact_label, vendor=st.session_state["vendor"],
)
st.session_state["visible_tables"] = tables
st.session_state["pending_contact_change"] = pending
"""

PERSON = "[Synthetic Person](https://example.invalid) **Lead**"
ROLE = "_Supervisor_"
SITE = "www.example.invalid"
TRADE = "[Electrical](https://example.invalid/vendor) **Trade**"
CUSTOM = "[Supplier notes](https://example.invalid/details)"


def _open(table, *, vendor=False):
    app = AppTest.from_string(CARD_APP, default_timeout=30)
    app.session_state["original_tables"] = (table,)
    app.session_state["vendor"] = vendor
    app.run()
    assert not app.exception
    return app


def test_untrusted_contact_card_summary_is_literal_with_raw_identity_and_edit():
    table = ReportTable(
        ("Name", "Role", "Site"),
        ((PERSON, ROLE, SITE),), "synthetic:contact",
    )
    app = _open(table)
    summary = " · ".join((PERSON, ROLE, SITE))
    rendered = [widget.value for widget in app.markdown]
    assert literal(summary) in rendered
    assert summary not in rendered
    assert app.session_state["visible_tables"] == (table,)

    next(button for button in app.button if button.label == "Edit contact").click().run()
    assert not app.exception
    assert next(control.value for control in app.text_input
                if control.label == "Name") == PERSON
    assert next(control.value for control in app.text_input
                if control.label == "Role") == ROLE
    assert next(control.value for control in app.text_input
                if control.label == "Site") == SITE
    next(button for button in app.button if button.label == "Close editing").click().run()
    assert not app.exception
    assert app.session_state["visible_tables"] == (table,)
    assert app.session_state["original_tables"] == (table,)


def test_vendor_category_and_custom_field_labels_are_literal_but_values_unchanged():
    table = ReportTable(
        ("Name", "Role", "Trade", CUSTOM),
        ((PERSON, "Contractor", TRADE, "**Source note**"),), "synthetic:vendor",
    )
    app = _open(table, vendor=True)
    rendered = [widget.value for widget in app.markdown]
    assert literal(PERSON + " · Contractor") in rendered
    assert PERSON + " · Contractor" not in rendered
    group = next(button for button in app.button
                 if "Add vendor contact to " in button.label)
    assert group.label == literal("Add vendor contact to " + TRADE)
    assert group.label != "Add vendor contact to " + TRADE
    assert app.session_state["visible_tables"] == (table,)

    next(button for button in app.button if button.label == "Edit vendor contact").click().run()
    assert not app.exception
    custom = next(control for control in app.text_input
                  if "Supplier notes" in control.label)
    assert custom.label == literal(CUSTOM)
    assert custom.value == "**Source note**"
    assert app.session_state["visible_tables"] == (table,)


def test_plain_contact_labels_keep_the_same_edit_and_add_controls():
    table = ReportTable(
        ("Name", "Role", "Site"),
        (("Synthetic Alice", "Supervisor", "North"),), "synthetic:plain",
    )
    app = _open(table)
    assert "Synthetic Alice · Supervisor · North" in [
        widget.value for widget in app.markdown]
    assert any(button.label == "Edit contact" for button in app.button)
    assert any(button.label == "Add contact" for button in app.button)
    app.run()
    assert not app.exception
    assert app.session_state["visible_tables"] == (table,)
