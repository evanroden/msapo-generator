"""A67: synthetic direct contact summaries and stale-click identity guards.

These AppTest exercises do not constitute live/served browser acceptance.
"""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportTable
from app.monthly_report_organization_ui import _visible_contact_summary
from test_monthly_report_organization_ui import SCRIPT


def _workspace():
    extra = """original["contact_matrix"] = replace(
    original["contact_matrix"],
    extra_tables=(ReportTable(
        ("Name", "Role", "Site", "Vendor", "Email", "", "Email"),
        (("Person One", "Coordinator", "Synthetic North",
          "Supplier One", "one@example.invalid", "Keep custom", "second@example.invalid"),
         ("Person Two", "Supervisor", "Synthetic South",
          "Supplier Two", "two@example.invalid", "Keep other", "other@example.invalid")),
        "source:a67"),
    ),
)
"""
    code = SCRIPT.replace("st.session_state.setdefault(\"original\", original)", extra +
                          "st.session_state.setdefault(\"original\", original)")
    app = AppTest.from_string(code, default_timeout=40).run()
    assert not app.exception
    return app


def test_summary_shows_person_role_site_vendor_email_before_edit_and_preserves_schema():
    app = _workspace()
    text = [node.value for node in app.text]
    assert any("Person One · Coordinator · Synthetic North · Supplier One · one@example.invalid" in value
               for value in text)
    assert any("Person Two · Supervisor · Synthetic South · Supplier Two · two@example.invalid" in value
               for value in text)
    assert not app.text_input
    assert len([button for button in app.button if button.label == "Edit contact"]) == 2
    assert app.session_state["blocks"] == app.session_state["original"]
    assert app.session_state["blocks"]["contact_matrix"].extra_tables[0].columns == (
        "Name", "Role", "Site", "Vendor", "Email", "", "Email",
    )


def test_direct_edit_one_action_preserves_other_contact_and_custom_columns():
    app = _workspace()
    before = app.session_state["original"]["contact_matrix"]
    next(button for button in app.button if button.label == "Edit contact").click().run()
    assert not app.exception
    assert next(widget for widget in app.text_input if widget.label == "Email").value == "one@example.invalid"
    assert next(widget for widget in app.text_input if widget.label == "Detail 6").value == "Keep custom"
    next(widget for widget in app.text_input if widget.label == "Email").set_value("changed@example.invalid").run()
    next(button for button in app.button if button.label == "Close editing").click().run()
    assert not app.exception
    after = app.session_state["blocks"]["contact_matrix"]
    assert after.extra_tables[0].rows[0][4] == "changed@example.invalid"
    assert after.extra_tables[0].rows[1] == before.extra_tables[0].rows[1]
    assert after.extra_tables[0].columns == before.extra_tables[0].columns
    assert after.extra_tables[0].reference == before.extra_tables[0].reference
    assert after.text == before.text
    assert all(app.session_state["blocks"][key] == value
               for key, value in app.session_state["original"].items()
               if key != "contact_matrix")


def test_stale_direct_summary_click_cannot_open_an_obsolete_row():
    app = _workspace()
    key = "test_organization_contact_binding"
    observed = app.session_state[key]
    assert len(observed) == 2
    app.session_state[key] = ("different-report-epoch", "different-rows")
    next(button for button in app.button if button.label == "Edit contact").click().run()
    assert not app.exception
    assert not app.text_input
    assert app.session_state["blocks"] == app.session_state["original"]
    assert len([button for button in app.button if button.label == "Edit contact"]) == 2


def test_summary_blank_or_duplicate_column_names_never_write_or_reorder_values():
    columns = ("Name", "Email", "Email", "Vendor", "", "Site")
    row = ("Synthetic", "first@example.invalid", "second@example.invalid",
           "Vendor", "untouched", "Synthetic Site")
    summary = _visible_contact_summary(columns, row, 0)
    assert summary == "Synthetic · Synthetic Site · Vendor · first@example.invalid"
    assert row[2] == "second@example.invalid" and row[4] == "untouched"
