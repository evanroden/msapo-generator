"""Starting-image replacement must include the ordinary guided working draft."""
from dataclasses import fields, replace
import hashlib

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_model import BlockSpec, ColumnSpec
from app.monthly_report_start_conflicts import image_conflicts, apply_replacements
from app.monthly_report_asset_review import pending_asset_indexes
from tests.test_monthly_report_start_conflicts import (
    pair, context, block, collision, button, manifest,
)
from tests.test_monthly_report_start_import import save_start, PERIOD
from tests.test_monthly_report_starting_replay_edits import repeat_saved_start


@pytest.mark.parametrize("slot", ["org_chart", "contact_matrix", "business_hours_workflow", "after_hours_workflow"])
def test_guided_presentation_required_flag_does_not_hide_conflict(slot):
    old, incoming = pair(slot)
    guided = complete_guided_sections(old)
    conflicts = image_conflicts(guided, incoming, None, **context())
    assert len(conflicts) == 1
    replaced = apply_replacements(guided, incoming, None, {slot: conflicts[0].binding}, **context())
    assert block(replaced, slot) == block(incoming, slot)
    assert replaced.sections == guided.sections
    assert old.blocks == guided.blocks


@pytest.mark.parametrize("field,value", [
    ("key", "another_destination"), ("type", "rich_text"),
    ("allowed_sources", ("Omit",)), ("stock_text_keys", ("different",)),
    ("columns", (ColumnSpec("different", "Different"),)),
])
def test_every_other_block_spec_field_remains_a_compatibility_boundary(field, value):
    assert {f.name for f in fields(BlockSpec)} == {
        "key", "type", "required", "allowed_sources", "stock_text_keys", "columns",
    }
    old, incoming = pair()
    guided = complete_guided_sections(old)
    incoming = replace(incoming, sections=tuple(replace(section, blocks=tuple(
        replace(spec, **{field: value}) if spec.key == "org_chart" else spec
        for spec in section.blocks)) for section in incoming.sections))
    assert image_conflicts(guided, incoming, None, **context()) == ()


def test_required_change_after_review_still_invalidates_exact_intent():
    old, incoming = pair()
    choice = image_conflicts(old, incoming, None, **context())[0]
    with pytest.raises(ValueError, match="changed after preview"):
        apply_replacements(complete_guided_sections(old), incoming, None,
                           {choice.slot: choice.binding}, **context())


@pytest.mark.parametrize("saved_snapshot", [False, True])
def test_guided_ui_keep_replace_save_reload_replay_without_generate(collision, saved_snapshot):
    initial, first, second, upload, _ = collision
    # Cover both a resumed saved report and the first import's working draft.
    # The fixture's snapshot is retained; no Generate call is needed either way.
    revision = 1 if saved_snapshot else 0
    if not saved_snapshot:
        # Use another period with no snapshot instead of deleting persisted data.
        from app.monthly_report_model import ReportPeriod
        period = ReportPeriod(2026, 10)
        initial = replace(initial, period=period)
    else:
        period = PERIOD
    app = AppTest.from_string('''
import streamlit as st
from app import monthly_report_library as library
from app.monthly_report_guided import complete_guided_sections
from app.monthly_report_section_ui import render_section_setup
from app.monthly_report_ui import _field
working = complete_guided_sections(st.session_state["working"])
state = library.load_profile(working.profile.contract, working.profile.key)
render_section_setup(working.profile.contract, working.period, "Synthetic Editor", _field,
    state=state, working_draft=working, working_revision=st.session_state["revision"])
''', default_timeout=30)
    app.session_state["working"] = initial
    app.session_state["revision"] = revision
    before = manifest(initial).read_bytes()
    app.run()
    assert not app.exception and not app.error
    assert button(app, "Continue to this month’s updates").disabled
    assert len(app.image) == 2
    button(app, "Keep current organization chart and return to review").click().run()
    assert manifest(initial).read_bytes() == before
    sha = hashlib.sha256(second.read_bytes()).hexdigest()
    assert not library.starting_contribution(initial.profile.contract, initial.profile.key, period, sha)[1]
    button(app, "Use incoming organization chart").click().run()
    assert manifest(initial).read_bytes() == before
    assert not button(app, "Continue to this month’s updates").disabled
    saved = save_start(app)
    assert block(saved).asset_hashes != block(initial).asset_hashes
    assert pending_asset_indexes(block(saved)) == (0,)
    assert library.load_profile(initial.profile.contract, initial.profile.key).block("org_chart").asset_hashes == block(initial).asset_hashes
    assert library.load_snapshot(initial.profile.contract, initial.profile.key, PERIOD).draft.blocks == initial.blocks
    # Reopen through the same ordinary guided wrapper with the imported result.
    reopened = AppTest.from_file(app._script_path, default_timeout=30)
    reopened.session_state["working"] = library.load_imported_draft(initial.profile.contract, initial.profile.key)
    reopened.session_state["revision"] = revision
    reopened.run()
    assert not reopened.exception and not reopened.error
    assert not any(b.label == "Use incoming organization chart" for b in reopened.button)
    replayed = save_start(reopened)
    assert block(replayed) == block(saved)
