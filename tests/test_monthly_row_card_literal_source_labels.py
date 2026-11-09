"""Synthetic native row-card source labels display literally without altering rows.

These AppTests use the actual Monthly proposal/onsite editor and existing
Streamlit fixtures. Source strings are invented, never customer records.
"""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_row_cards_ui import _source_display
from app.monthly_report_ui_text import literal
from test_monthly_report_row_cards_ui import (
    PROPOSAL_COLUMNS, SCRIPT, button, example, field, workspace,
)


DESCRIPTION = "[Synthetic pump](https://example.invalid/pump) **Replacement**"
SITE = "www.example.invalid/plant"
VENDOR = "supplier@example.invalid"
STATUS = "_Pending_"
DECISION = "[Deferred](https://example.invalid/decision)"
CUSTOM_HEADING = "[Vendor](https://example.invalid/vendor) **Name**"


def _row():
    return ("0007", SITE, VENDOR, DESCRIPTION, STATUS, DECISION,
            "Source notes remain exactly as entered.")


def test_display_helper_does_not_change_standard_native_labels():
    for name in (*PROPOSAL_COLUMNS, "Finish Date", "Task Code-Description",
                 "Area", "Proposal (scope)", "North Plant"):
        assert _source_display(name) == name
    for sample in (DESCRIPTION, SITE, VENDOR, STATUS, DECISION,
                   "# Heading", "- List item", "1. Numbered item",
                   "<a>Original text</a>"):
        assert _source_display(sample) == literal(sample)
    assert _source_display("Pump P-1") == "Pump P-1"


def test_proposal_source_summary_displays_literal_links_and_keeps_raw_rows():
    row = _row()
    app = workspace("proposals", rows=(row,))
    assert not app.exception
    assert literal(DESCRIPTION) in [item.value for item in app.markdown]
    assert DESCRIPTION not in [item.value for item in app.markdown]
    # Only source labels and values are escaped; application-owned separators
    # and ordinary headings stay unchanged for existing keyboard/editor flows.
    assert "Proposal #: 0007 · Facility: " + literal(SITE) + " · Vendor: " + literal(VENDOR) in [
        item.value for item in app.caption
    ]
    assert "Status: " + literal(STATUS) + " · Decision: " + literal(DECISION) in [
        item.value for item in app.caption
    ]
    assert app.session_state["block"].rows == (row,)


def test_proposal_edit_close_and_reopen_retain_exact_source_values():
    row = _row()
    app = workspace("proposals", rows=(row,))
    original = app.session_state["block"]
    button(app, "Edit proposal").click().run()
    assert not app.exception
    assert field(app, "Facility").value == SITE
    assert field(app, "Vendor").value == VENDOR
    assert field(app, "Work Description", "text_area").value == DESCRIPTION
    assert field(app, "Status").value == STATUS
    assert field(app, "Decision").value == DECISION
    source_id = field(app, "Work Description", "text_area").proto.id
    app.run()
    assert field(app, "Work Description", "text_area").proto.id == source_id
    button(app, "Close editing").click().run()
    assert not app.exception
    assert app.session_state["block"] == original
    button(app, "Edit proposal").click().run()
    assert field(app, "Work Description", "text_area").value == DESCRIPTION


def test_custom_imported_column_heading_is_literal_but_row_edit_is_raw():
    row = _row()
    spec, block = example("proposals", rows=(row,))
    custom = replace(spec, columns=tuple(
        replace(col, title=CUSTOM_HEADING) if col.title == "Vendor" else col
        for col in spec.columns))
    script = SCRIPT.replace("INITIAL", repr(block)).replace("SPEC", repr(custom))
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    button(app, "Edit proposal").click().run()
    assert not app.exception
    matched = [item for item in app.text_input if item.label == literal(CUSTOM_HEADING)]
    assert len(matched) == 1
    assert matched[0].value == VENDOR
    assert not any(item.label == CUSTOM_HEADING for item in app.text_input)
    matched[0].set_value("Reviewed synthetic supplier").run()
    assert not app.exception
    assert app.session_state["block"].rows[0][2] == "Reviewed synthetic supplier"
    assert app.session_state["block"].references == block.references
    assert app.session_state["block"].rows[0][3:] == row[3:]


def test_normal_proposal_labels_and_onsite_summary_remain_usable():
    ordinary = ("0009", "North", "Synthetic vendor", "Inspected motor",
                "Pending", "Review", "Recorded")
    app = workspace("proposals", rows=(ordinary,))
    assert not app.exception
    assert "Inspected motor" in [item.value for item in app.markdown]
    button(app, "Edit proposal").click().run()
    assert not app.exception
    labels = {widget.label for kind in ("text_input", "text_area")
              for widget in getattr(app, kind)}
    assert labels == set(PROPOSAL_COLUMNS)
    assert field(app, "Vendor").value == "Synthetic vendor"

    onsite = ("00042", "2026-09-12", "North plant", DESCRIPTION, "P-0007")
    other = workspace("service_calls", rows=(onsite,))
    assert not other.exception
    assert literal(DESCRIPTION) in [item.value for item in other.markdown]
    assert other.session_state["block"].rows == (onsite,)
    assert any(item.label == "Edit onsite call" for item in other.button)
