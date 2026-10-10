"""Collapsed contact rows distinguish same-name people at different sites."""
from streamlit.testing.v1 import AppTest

from app.monthly_report_visual_ui import _contact_label


def test_same_name_records_are_distinct_without_merging():
    cols = ("Name", "Role", "Site", "Phone")
    north = ("Jordan Example", "Hospital operator", "North", "111")
    south = ("Jordan Example", "Facilities lead", "South", "222")
    assert _contact_label(cols, north, 0) == "Jordan Example · Hospital operator · North"
    assert _contact_label(cols, south, 1) == "Jordan Example · Facilities lead · South"
    assert _contact_label(cols, north, 0) != _contact_label(cols, south, 1)


def test_expander_shows_identity_without_opening_row():
    app = AppTest.from_string("""
import streamlit as st
from app.monthly_report_visual_ui import _contact_rows
def field(key, initial):
    st.session_state.setdefault(key, initial)
    return key
_contact_rows(("Name", "Role", "Site"),
    (("Person One", "Client technician", "North"),
     ("Person One", "Client technician", "South")),
    "synthetic_contacts", field)
""").run()
    assert not app.exception
    assert [e.label for e in app.expander] == [
        "Person One · Client technician · North",
        "Person One · Client technician · South",
    ]


def test_synthetic_vendor_contact_heading_also_shows_facility():
    columns = ("Facility", "Discipline", "Vendor", "Contact", "Phone")
    row = ("South", "Mechanical", "Supplier Alpha", "Alex Contact", "555")
    assert _contact_label(columns, row, 0) == "Alex Contact · Mechanical · South"
