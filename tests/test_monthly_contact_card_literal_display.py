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


def _card_widget(app, kind, suffix):
    controls = [w for w in getattr(app, kind)
                if isinstance(w.key, str) and w.key.endswith(suffix)]
    assert len(controls) == 1
    return controls[0]


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

    _card_widget(app, "button", "_open_0_0").click().run()
    assert not app.exception
    assert _card_widget(app, "text_input", "_field_0").value == PERSON
    assert _card_widget(app, "text_input", "_field_1").value == ROLE
    assert _card_widget(app, "text_input", "_field_2").value == SITE
    _card_widget(app, "button", "_close").click().run()
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
    group = _card_widget(app, "button", "_add_group_0_0")
    assert group.label == literal("Add vendor contact to " + TRADE)
    assert group.label != "Add vendor contact to " + TRADE
    assert app.session_state["visible_tables"] == (table,)

    _card_widget(app, "button", "_open_0_0").click().run()
    assert not app.exception
    custom = _card_widget(app, "text_input", "_field_3")
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
    assert _card_widget(app, "button", "_open_0_0").label == "Edit contact"
    assert _card_widget(app, "button", "_add_0").label == "Add contact"
    app.run()
    assert not app.exception
    assert app.session_state["visible_tables"] == (table,)

def test_contract_scoped_vendor_summary_preserves_unmapped_values_and_msa_status():
    # The merged #686 summary must not drop unrecognized source columns.
    table = ReportTable(
        ("Discipline", "MSA", CUSTOM),
        ((TRADE, "", "**Source note**"),), "synthetic:retained-vendor",
    )
    app = _open(table, vendor=True)
    summary = TRADE + " · " + CUSTOM + ": **Source note** · MSA: Not provided"
    assert literal(summary) in [w.value for w in app.markdown]
    assert summary not in [w.value for w in app.markdown]
    assert app.session_state["original_tables"] == (table,)
    assert app.session_state["visible_tables"] == (table,)
    _card_widget(app, "button", "_open_0_0").click().run()
    assert not app.exception
    assert _card_widget(app, "text_input", "_field_1").value == ""
    assert _card_widget(app, "text_input", "_field_2").value == "**Source note**"
    _card_widget(app, "button", "_close").click().run()
    assert app.session_state["visible_tables"] == (table,)

def test_html_like_contact_names_display_as_source_text():
    row = ("<strong>Synthetic Name</strong>", "Supervisor <level-2>", "Plant <West>")
    table = ReportTable(("Name", "Role", "Site"), (row,), "synthetic:html-like")
    app = _open(table)
    summary = " · ".join(row)
    assert literal(summary) in [w.value for w in app.markdown]
    assert summary not in [w.value for w in app.markdown]
    _card_widget(app, "button", "_open_0_0").click().run()
    assert not app.exception
    assert tuple(_card_widget(app, "text_input", f"_field_{i}").value for i in range(3)) == row
    _card_widget(app, "button", "_close").click().run()
    assert app.session_state["visible_tables"] == (table,)
    assert app.session_state["original_tables"] == (table,)
