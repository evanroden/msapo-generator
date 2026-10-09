"""Vendor page reuse and unknown agreement states stay intact while editing."""

from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app.monthly_report_asset_review import normalize_asset_reviews, pending_asset_indexes
from app.monthly_report_editor import _cell_text, _typed_table
from app.monthly_report_model import default_sections


def vendor_spec():
    return next(s for s in default_sections() if s.key == "subcontractors").blocks[0]


def vendor_app(rows=()):
    app = AppTest.from_string('''
from dataclasses import replace
from io import BytesIO
from PIL import Image
import streamlit as st
from app.monthly_report_model import ReportPeriod, ResolvedBlock, default_sections, synthetic_draft, synthetic_profiles
from app.monthly_report_ui import _field
from app.monthly_report_visual_ui import edit_contacts
raw = BytesIO()
Image.new("RGB", (120, 120), "navy").save(raw, "PNG")
assets = {"vendor-page.png": raw.getvalue()}
spec = next(s for s in default_sections() if s.key == "subcontractors").blocks[0]
initial = ResolvedBlock(spec.key, "Library", rows=st.session_state["seed_rows"], asset_hashes=("vendor-page.png",), references=("vendor-source",))
initial = replace(initial, client_reviewed_fingerprint=initial.fingerprint)
st.session_state.setdefault("original", initial)
draft = replace(synthetic_draft(synthetic_profiles()[0], ReportPeriod(2026, 9)), blocks=(initial,))
draft = st.session_state.setdefault("report_vendor_draft", draft)
changed = edit_contacts(draft, spec, draft.blocks[0], "report_vendor", assets, _field)
st.session_state["report_vendor_draft"] = replace(draft, blocks=(changed,))
''')
    app.session_state["seed_rows"] = rows
    return app.run()


def vendor_block(app):
    return app.session_state["report_vendor_draft"].blocks[0]


@pytest.mark.parametrize("rows", [(), (("Synthetic Site", "HVAC", "Example Vendor", "Example Contact", "", ""),)])
def test_vendor_pages_show_with_empty_or_populated_table_without_requiring_review(rows):
    app = vendor_app(rows)
    assert not app.exception
    assert "View or change saved vendor pages" in [e.label for e in app.expander]
    assert any(b.label == "View or change pictures" for b in app.button)
    assert not any(b.label == "Remove this picture" for b in app.button)
    assert vendor_block(app) == normalize_asset_reviews(app.session_state["original"])
    app.run()
    assert not app.exception
    block = vendor_block(app)
    assert block.source == "Library"
    assert block.client_reviewed_fingerprint == block.fingerprint
    assert block.rows == rows


def test_vendor_agreement_edit_preserves_unknown_and_invalidates_only_changed_content():
    rows = (("Synthetic Site", "HVAC", "Example Vendor", "Example Contact", "", ""),)
    app = vendor_app(rows)
    assert next(w for w in app.text_input if w.label == "MSA").value == ""
    next(w for w in app.text_input if w.label == "MSA").set_value("Needs confirmation").run()
    assert not app.exception
    block = vendor_block(app)
    assert block.rows[0][-1] == "Needs confirmation"
    assert block.source == "This month"
    assert not block.client_reviewed_fingerprint
    assert block.asset_hashes == ("vendor-page.png",)
    app.run()
    assert vendor_block(app) == block
    assert not pending_asset_indexes(block)
    next(b for b in app.button if b.label == "View or change pictures").click().run()
    next(b for b in app.button if b.label == "Remove this picture").click().run()
    assert not app.exception
    assert vendor_block(app).rows == block.rows
    assert vendor_block(app).asset_hashes == ()
    assert app.session_state["original"].rows[0][-1] == ""


def test_new_vendor_schema_accepts_agreement_states_without_boolean_conversion():
    spec = vendor_spec()
    assert spec.columns[-1].type == "text"
    states = ("", "No", "Needs confirmation", "Not applicable")
    rows = tuple(("Site", "HVAC", "Vendor", "Contact", "", status) for status in states)
    seed, _ = _typed_table(spec, rows)
    assert tuple(_cell_text(row["MSA"]) for row in seed) == states


def test_legacy_boolean_column_preserves_every_value_when_agreement_is_unknown():
    spec = vendor_spec()
    spec = replace(spec, columns=(*spec.columns[:-1], replace(spec.columns[-1], type="boolean")))
    states = ("", "No", "Yes", "Needs confirmation", "Not applicable", "Partly received")
    rows = tuple(("Site", "HVAC", "Vendor", "Contact", "", status) for status in states)
    seed, config = _typed_table(spec, rows)
    assert tuple(_cell_text(row["MSA"]) for row in seed) == states
    assert config["MSA"]["type_config"]["type"] == "text"


def test_known_legacy_boolean_values_keep_false_and_blank_distinct():
    spec = vendor_spec()
    spec = replace(spec, columns=(*spec.columns[:-1], replace(spec.columns[-1], type="boolean")))
    rows = tuple(("Site", "HVAC", "Vendor", "Contact", "", status) for status in ("", "No", "Yes"))
    seed, config = _typed_table(spec, rows)
    assert [row["MSA"] for row in seed] == [None, False, True]
    assert config["MSA"]["type_config"]["type"] == "checkbox"
