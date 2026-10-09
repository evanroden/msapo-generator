"""Organization changes are local and unchanged imported content stays intact."""

from streamlit.testing.v1 import AppTest


SCRIPT = '''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import BlockSpec, ReportPeriod, ReportTable, ResolvedBlock, synthetic_draft, synthetic_profiles
from app.monthly_report_organization_ui import ORGANIZATION_PARTS, render_organization
from app.monthly_report_ui import _field
image = BytesIO(); Image.new("RGB", (20, 20), "navy").save(image, "PNG")
assets = st.session_state.setdefault("assets", {"chart.png": image.getvalue(), "after.png": image.getvalue()})
original = {
    "org_chart": ResolvedBlock("org_chart", "Library", text="Reporting lines confirmed.", asset_hashes=("chart.png",), extra_tables=(ReportTable(("Team", "Team", ""), (("Site", "ENFRA", "Keep this custom cell"),)),), references=("chart-source",), client_reviewed_fingerprint="chart-review"),
    "business_hours_workflow": ResolvedBlock("business_hours_workflow", "Library", text="Call the daytime operator.", references=("day-source",)),
    "after_hours_workflow": ResolvedBlock("after_hours_workflow", "Library", text="Call the on-call operator.", asset_hashes=("after.png",), references=("night-source",)),
    "contact_matrix": ResolvedBlock("contact_matrix", "Library", text="Use the listed escalation order.", extra_tables=(ReportTable(("Role", "Name"), (("Operator", "Synthetic Person"),)),), references=("contact-source",)),
    "activity_summary": ResolvedBlock("activity_summary", "This month", text="Unrelated monthly work."),
}
st.session_state.setdefault("original", original)
blocks = st.session_state.setdefault("blocks", original)
specs = {key: BlockSpec(key, "image_page") for key, title in ORGANIZATION_PARTS}
draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=tuple(blocks.values()))
st.session_state["editor_calls"] = []
def editor(spec, block):
    st.session_state["editor_calls"].append(spec.key)
    value = st.text_area("Edit " + spec.key, key=_field("test_edit_" + spec.key, block.text))
    return replace(block, text=value, source="This month") if value != block.text else block
updated = render_organization(draft, blocks, specs, "test", assets, _field, editor)
st.session_state["blocks"] = updated
'''


def app():
    return AppTest.from_string(SCRIPT).run()


def click(at, label):
    return next(button for button in at.button if button.label == label).click().run()


def test_four_current_parts_need_no_keep_or_change_questions():
    at = app()
    assert not at.exception
    assert len(at.get("image")) == 2
    assert {item.value for item in at.markdown} >= {
        "#### Team chart", "#### Daytime outage procedure",
        "#### After-hours outage procedure", "#### Facility contacts",
    }
    assert not at.text_area and not at.checkbox and not at.radio and not at.selectbox
    assert len(at.button) == 4
    assert at.session_state["editor_calls"] == []
    assert at.session_state["blocks"] == at.session_state["original"]
    # Duplicate or blank headings must not erase a custom imported cell.
    assert any("Keep this custom cell" in frame.value.to_string() for frame in at.dataframe)


def test_after_hours_change_preserves_other_three_parts_and_provenance():
    at = app()
    click(at, "Change after-hours outage procedure")
    assert not at.exception
    assert at.session_state["editor_calls"] == ["after_hours_workflow"]
    assert [w.label for w in at.text_area] == ["Edit after_hours_workflow"]
    at.text_area[0].input("Call the updated on-call operator.").run()
    click(at, "Done changing after-hours outage procedure")
    assert not at.text_area
    blocks = at.session_state["blocks"]
    original = at.session_state["original"]
    assert blocks["after_hours_workflow"].text == "Call the updated on-call operator."
    assert blocks["after_hours_workflow"].asset_hashes == original["after_hours_workflow"].asset_hashes
    assert blocks["after_hours_workflow"].references == original["after_hours_workflow"].references
    assert all(block == original[key] for key, block in blocks.items() if key != "after_hours_workflow")


def test_changing_another_part_closes_previous_editor():
    at = app()
    click(at, "Change after-hours outage procedure")
    click(at, "Change daytime outage procedure")
    assert at.session_state["editor_calls"] == ["business_hours_workflow"]
    assert [w.label for w in at.text_area] == ["Edit business_hours_workflow"]
    assert at.session_state["blocks"] == at.session_state["original"]


def test_opening_complex_imported_chart_never_converts_it():
    at = app()
    click(at, "Change team chart")
    assert not at.exception
    assert "Build an editable team chart (optional)" in [expander.label for expander in at.expander]
    assert at.session_state["blocks"]["org_chart"] == at.session_state["original"]["org_chart"]
    assert not at.session_state["blocks"]["org_chart"].org_nodes
    click(at, "Done changing team chart")
    assert at.session_state["blocks"] == at.session_state["original"]


def test_editing_one_contact_retains_notes_and_other_parts():
    at = app()
    click(at, "Change facility contacts")
    assert not at.exception
    assert at.session_state["blocks"] == at.session_state["original"]
    next(w for w in at.text_input if w.label == "Name").input("Updated Synthetic Person").run()
    blocks, original = at.session_state["blocks"], at.session_state["original"]
    contacts = blocks["contact_matrix"]
    assert contacts.extra_tables[0].rows == (("Operator", "Updated Synthetic Person"),)
    assert contacts.text == original["contact_matrix"].text
    assert contacts.references == original["contact_matrix"].references
    assert all(block == original[key] for key, block in blocks.items() if key != "contact_matrix")


def test_missing_saved_page_is_recoverable_and_retained():
    at = AppTest.from_string(SCRIPT.replace('"chart.png": image.getvalue(), ', '')).run()
    assert not at.exception
    assert any("saved page is unavailable" in warning.value for warning in at.warning)
    assert at.session_state["blocks"] == at.session_state["original"]


def test_opening_native_chart_does_not_change_source_or_review_stamp():
    native = SCRIPT.replace(
        'st.session_state.setdefault("original", original)',
        '''from app.monthly_report_model import OrgChartNode
original["org_chart"] = replace(original["org_chart"], asset_hashes=(), extra_tables=(), org_nodes=(OrgChartNode("manager", "Synthetic Manager", "Manager"),))
st.session_state.setdefault("original", original)''',
    )
    at = AppTest.from_string(native).run()
    click(at, "Change team chart")
    assert not at.exception
    assert at.session_state["blocks"] == at.session_state["original"]
