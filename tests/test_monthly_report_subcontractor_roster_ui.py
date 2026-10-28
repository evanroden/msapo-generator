"""Native Section 6 opt-in save/reuse is distinct from report editing."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app.monthly_report_model import ReportPeriod, ReportDraft, ReportTable, ResolvedBlock, default_sections
from app.monthly_report_subcontractor_roster import load_rosters, save_roster
from app.monthly_report_subcontractor_roster_ui import _preview_rows
from test_monthly_report_subcontractor_roster import (
    NATIVE_SPEC, profile, row, rows,
)


APP = """
import streamlit as st
from app.monthly_report_model import ReportDraft, ReportPeriod, default_sections
from app.monthly_report_subcontractor_roster_ui import render_subcontractor_roster
from app.monthly_report_model import default_sections

def field(key, default):
    st.session_state.setdefault(key, default)
    return key

saved = st.session_state["vendor_block"]
profile = st.session_state["vendor_profile"]
spec = next(s for s in default_sections() if s.key == "subcontractors").blocks[0]
draft = ReportDraft(profile, ReportPeriod(2026,9), "Synthetic Editor",
                    default_sections(), (saved,))
changed = render_subcontractor_roster(draft, spec, saved, "vendor_demo", field)
st.session_state["vendor_block"] = changed
"""


def launch(monkeypatch, tmp_path, p, block):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    app = AppTest.from_string(APP, default_timeout=30)
    app.session_state["vendor_profile"] = p
    app.session_state["vendor_block"] = block
    app.run()
    assert not app.exception
    return app


def button(app, title):
    return next(b for b in app.button if b.label == title)


def check(app, phrase):
    return next(x for x in app.checkbox if phrase in x.label)


def test_share_is_approval_bound_and_does_not_mutate_report(monkeypatch, tmp_path):
    north = profile("Synthetic Contract A")
    before = rows(row(north.facilities[0].title, "Saved only with consent"))
    app = launch(monkeypatch, tmp_path, north, before)
    assert button(app, "Save shared subcontractors").disabled
    assert load_rosters(north.contract).revision == 0
    app.run()
    assert app.session_state["vendor_block"] == before
    check(app, "I reviewed these vendor contacts").check().run()
    assert not button(app, "Save shared subcontractors").disabled
    button(app, "Save shared subcontractors").click().run()
    assert not app.exception
    assert load_rosters(north.contract).revision == 1
    assert app.session_state["vendor_block"] == before
    app.run()
    assert not app.exception and load_rosters(north.contract).revision == 1
    assert button(app, "Use saved subcontractors in this report").disabled
    # Replacing a manually populated report table is a second explicit choice.
    check(app, "Replace this report's existing vendor tables").check().run()
    button(app, "Use saved subcontractors in this report").click().run()
    assert not app.exception
    assert app.session_state["vendor_block"].rows == before.rows
    assert app.session_state["vendor_block"].source == "Library"
    assert load_rosters(north.contract).revision == 1


def test_another_site_cannot_see_site_only_roster_but_can_choose_contract_roster(
        monkeypatch, tmp_path):
    # Set the isolated storage root *before* the first direct save. Previously
    # the initial save went to the default store, then launch changed the root.
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = profile("Synthetic Contract A")
    south = profile("Synthetic Contract A", "a2", ("south",))
    source = rows(row(north.facilities[0].title, "Site only"))
    save_roster(north, source, NATIVE_SPEC, site_keys=("north",),
                expected_revision=0, actor="Synthetic Editor", confirmed=True)
    app = launch(monkeypatch, tmp_path, south, rows())
    assert not any(b.label == "Use saved subcontractors in this report" for b in app.button)
    # A separate contract-wide version is explicitly approved on a different
    # report and does not auto-fill South while this UI remains mounted.
    save_roster(north, rows(row("All sites", "Shared vendor")),
                NATIVE_SPEC, site_keys=(), expected_revision=1,
                actor="Synthetic Editor", confirmed=True)
    app.run()
    assert not app.exception
    assert not any(b.label == "Use saved subcontractors in this report" for b in app.button)
    assert any("version changed" in w.value.lower() for w in app.warning)
    assert not app.session_state["vendor_block"].rows
    button(app, "Reload shared subcontractors").click().run()
    assert not app.exception
    button(app, "Use saved subcontractors in this report").click().run()
    assert not app.exception
    assert app.session_state["vendor_block"].rows == (row("All sites", "Shared vendor"),)
    assert load_rosters(north.contract).revision == 2


def test_stale_shared_save_is_blocked_until_reloaded_without_discarding_fields(
        monkeypatch, tmp_path):
    north = profile("Synthetic Contract A")
    before = rows(row(north.facilities[0].title, "Report-only correction"))
    app = launch(monkeypatch, tmp_path, north, before)
    save_roster(north, rows(row(north.facilities[0].title, "Other user's save")),
                NATIVE_SPEC, site_keys=("north",),
                expected_revision=0, actor="Synthetic Other", confirmed=True)
    app.run()
    assert not app.exception
    assert any("version changed" in w.value.lower() for w in app.warning)
    assert not any(b.label == "Save shared subcontractors" for b in app.button)
    assert app.session_state["vendor_block"] == before
    button(app, "Reload shared subcontractors").click().run()
    assert not app.exception
    assert button(app, "Save shared subcontractors").disabled
    assert app.session_state["vendor_block"] == before
    assert load_rosters(north.contract).entries[0].tables[0].rows[0][2] == "Other user's save"


def test_risky_contract_wide_promotion_refuses_explicit_site_rows(monkeypatch, tmp_path):
    north = profile("Synthetic Contract A")
    before = rows(row(north.facilities[0].title, "Site-specific vendor"))
    app = launch(monkeypatch, tmp_path, north, before)
    next(r for r in app.radio if r.label == "Approved reuse scope").set_value(
        "Entire contract").run()
    check(app, "I reviewed these vendor contacts").check().run()
    button(app, "Save shared subcontractors").click().run()
    assert not app.exception
    assert any("names a site" in w.value.lower() for w in app.warning)
    assert load_rosters(north.contract).revision == 0
    assert app.session_state["vendor_block"] == before


def test_saved_roster_preview_keeps_repeated_blank_and_literal_column_labels(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    north = profile("Synthetic Contract A")
    source = ReportTable(
        ("Vendor", "Contact", "Contact", "", "Column 4", "Contact (2)"),
        (("Synthetic Vendor", "First contact", "Second contact",
          "Blank heading value", "Literal Column 4", "Literal Contact (2)"),),
    )
    preview = _preview_rows(source)
    assert len(preview) == 1
    assert len(preview[0]) == len(source.columns)
    assert len(set(preview[0])) == len(source.columns)
    assert list(preview[0].values()) == list(source.rows[0])
    assert preview[0]["Contact"] == "First contact"
    assert preview[0]["Contact (2)"] == "Literal Contact (2)"

    stored = save_roster(
        north, ResolvedBlock("subcontractor_matrix", "This month", extra_tables=(source,)),
        NATIVE_SPEC, site_keys=("north",), expected_revision=0,
        actor="Synthetic Editor", confirmed=True,
    )
    assert stored.entries[0].tables[0].columns == source.columns
    assert stored.entries[0].tables[0].rows == source.rows
    app = launch(monkeypatch, tmp_path, north, rows())
    check(app, "Review saved roster rows").check().run()
    assert not app.exception
    shown = app.dataframe[0].value
    assert list(shown.columns) == list(preview[0])
    assert list(shown.iloc[0]) == list(source.rows[0])
    # Opening a preview does not publish, change or overwrite the shared data.
    assert load_rosters(north.contract) == stored
