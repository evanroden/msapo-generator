"""Reachable sidebar Apply/Undo uses the actual Monthly AppTest controls.

This test does not assert a served browser, physical device or authentic source.
"""

from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory, monthly_report_library as library
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles
from app.monthly_report_start import design_seed
from tests.test_monthly_report_selected_directory_ui import seed
from test_monthly_report_ui import monthly, choose_report, ROOT


def current_draft(app, key):
    return next(draft for draft in app.session_state.filtered_state.values()
                if isinstance(draft, ReportDraft) and draft.profile.key == key)


def test_real_guided_sidebar_undo_preserves_later_section_edits_and_reopen(
    monkeypatch, tmp_path,
):
    initial, _ = seed(monkeypatch, tmp_path)
    profile = replace(
        synthetic_profiles()[1], contract=initial.contract,
        key="synthetic-sidebar-undo", title="Unity and USH directory Undo",
        facilities=(Facility("unity", "Unity Hospital"),
                    Facility("ush", "Unity Specialty Hospital")),
        scope_type="multi_site",
    )
    library.save_profile(profile, expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Seeder")
    local = ("Unity Hospital", "Night Lead", "Report-Only Person",
             "202-555-0184", "local@example.invalid")
    draft = directory.apply_contacts(
        draft, ResolvedBlock("contact_matrix", "This month", rows=(local,)))
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Seeder")

    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, "Unity Hospital")
    next(w for w in app.checkbox if w.label == "Unity Specialty Hospital").check().run()
    next(w for w in app.text_input if w.label == "Prepared by").set_value(
        "Synthetic Editor").run()
    assert not app.exception
    assert next(b for b in current_draft(app, profile.key).blocks
                if b.key == "contact_matrix").rows == (local,)

    next(button for button in app.button
         if button.label == "Save contacts to directory and report").click().run()
    assert not app.exception
    applied = current_draft(app, profile.key)
    contact = next(b for b in applied.blocks if b.key == "contact_matrix")
    assert len(contact.rows) == 3 and contact.rows[-1] == local
    assert any(b.label == "Undo last directory Apply in this report" for b in app.button)

    # Simulate a separately committed working-draft section edit. Native
    # rich-text input and unblurred-browser behaviour require separate served
    # acceptance, not a synthetic claim from this session mutation.
    draft_key = next(key for key, value in app.session_state.filtered_state.items()
                     if isinstance(value, ReportDraft) and value.profile.key == profile.key)
    activity = ResolvedBlock("activity_narrative", "This month",
                             text="Independent later synthetic edit")
    app.session_state[draft_key] = replace(
        applied, blocks=(*applied.blocks, activity))
    app.run()
    assert not app.exception
    next(button for button in app.button
         if button.label == "Undo last directory Apply in this report").click().run()
    assert not app.exception
    restored = current_draft(app, profile.key)
    assert next(b for b in restored.blocks if b.key == "contact_matrix").rows == (local,)
    assert activity in restored.blocks
    assert directory.load_directory(initial.contract).revision == initial.revision + 1

    next(b for b in app.button if b.label == "Save shared version").click().run()
    assert not app.exception
    stored = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert stored is not None
    assert next(b for b in stored.draft.blocks if b.key == "contact_matrix").rows == (local,)
    assert activity in stored.draft.blocks

    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, "Unity Hospital")
    next(w for w in reopened.checkbox if w.label == "Unity Specialty Hospital").check().run()
    assert not reopened.exception
    assert next(b for b in current_draft(reopened, profile.key).blocks
                if b.key == "contact_matrix").rows == (local,)
