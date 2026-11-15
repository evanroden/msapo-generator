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
    activity = replace(next(block for block in applied.blocks
                            if block.key == "activity_summary"),
                       source="This month", text="Independent later synthetic edit")
    app.session_state[draft_key] = replace(
        applied, blocks=tuple(activity if block.key == "activity_summary" else block
                              for block in applied.blocks))
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


def test_guided_undo_keeps_contact_input_delivered_on_the_undo_click(
    monkeypatch, tmp_path,
):
    """A queued contact-card correction must reach its editor, not Undo's reset."""
    from app.monthly_report_contact_apply_undo import UNDO_MARKER

    initial, _ = seed(monkeypatch, tmp_path)
    first, second = initial.sites[:2]
    profile = replace(
        synthetic_profiles()[1], contract=initial.contract,
        key="synthetic-pending-contact-undo", title="Synthetic contact race",
        facilities=(Facility(first.key, first.title), Facility(second.key, second.title)),
        scope_type="multi_site",
    )
    library.save_profile(profile, expected_revision=0,
                         actor="Synthetic Seeder", confirmed=True)
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Seeder")
    local = (first.title, "Backup", "Synthetic Local Person",
             "202-555-0136", "local@example.invalid")
    draft = directory.apply_contacts(
        draft, ResolvedBlock("contact_matrix", "This month", rows=(local,)))
    library.save_snapshot(draft, expected_revision=0,
                          entered_editor="Synthetic Seeder")

    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, first.title)
    next(w for w in app.checkbox if w.label == second.title).check().run()
    next(w for w in app.text_input if w.label == "Prepared by").set_value(
        "Synthetic Editor").run()
    next(b for b in app.button
         if b.label == "Save contacts to directory and report").click().run()
    assert not app.exception
    current = current_draft(app, profile.key)
    assert len(next(b for b in current.blocks if b.key == "contact_matrix").rows) == 3

    state = app.session_state.filtered_state
    draft_key = next(k for k, value in state.items()
                     if isinstance(value, ReportDraft) and value.profile.key == profile.key)
    prefix = draft_key.removesuffix("_draft")
    binding = next(k for k in state
                   if k.startswith(prefix + "_contacts_contact_matrix_")
                   and k.endswith("_compact_editor_key"))
    editor_key = state[binding]
    record = dict(state[editor_key])
    tables = record["tables"]
    first_row = tables[0].rows[0]
    changed = (*first_row[:3], "202-555-0148", *first_row[4:])
    corrected = (replace(tables[0], rows=(changed, *tables[0].rows[1:])), *tables[1:])
    record["pending"] = {"expected": tables, "corrected": corrected,
                         "result": corrected, "action": "edit", "active": (0, 0)}
    app.session_state[editor_key] = record

    next(b for b in app.button
         if b.label == "Undo last directory Apply in this report").click().run()
    assert not app.exception
    assert any("newer contact or note edit is pending" in w.value for w in app.warning)
    after = current_draft(app, profile.key)
    contact = next(b for b in after.blocks if b.key == "contact_matrix")
    assert all(UNDO_MARKER not in b.references for b in after.blocks)
    assert any(row[3] == "202-555-0148" for row in contact.rows) or any(
        isinstance(value, dict) and value.get("pending", {}).get("corrected") == corrected
        for value in app.session_state.filtered_state.values()
        if isinstance(value, dict))


def test_guided_undo_keeps_note_delivered_on_the_undo_click(
    monkeypatch, tmp_path,
):
    """A current-scope rich-text callback must be captured before Undo can reset."""
    from app import monthly_report_guided as guided
    from app.monthly_report_contact_apply_undo import UNDO_MARKER

    initial, _ = seed(monkeypatch, tmp_path)
    first, second = initial.sites[:2]
    profile = replace(
        synthetic_profiles()[1], contract=initial.contract,
        key="synthetic-pending-note-undo", title="Synthetic note race",
        facilities=(Facility(first.key, first.title), Facility(second.key, second.title)),
        scope_type="multi_site",
    )
    library.save_profile(profile, expected_revision=0,
                         actor="Synthetic Seeder", confirmed=True)
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Seeder")
    local = (first.title, "Backup", "Synthetic Local Person",
             "202-555-0137", "local@example.invalid")
    draft = directory.apply_contacts(
        draft, ResolvedBlock("contact_matrix", "This month", rows=(local,)))
    library.save_snapshot(draft, expected_revision=0,
                          entered_editor="Synthetic Seeder")

    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, first.title)
    next(w for w in app.checkbox if w.label == second.title).check().run()
    next(w for w in app.text_input if w.label == "Prepared by").set_value(
        "Synthetic Editor").run()
    next(b for b in app.button
         if b.label == "Save contacts to directory and report").click().run()
    assert not app.exception

    state = app.session_state.filtered_state
    draft_key = next(k for k, value in state.items()
                     if isinstance(value, ReportDraft) and value.profile.key == profile.key)
    prefix = draft_key.removesuffix("_draft")
    contact = next(b for b in current_draft(app, profile.key).blocks
                   if b.key == "contact_matrix")
    scope = guided._signature((
        prefix, state[prefix + "_rich_text_epoch"],
        state.get("_monthly_qa_generation", "")))
    widget = prefix + "_edit_contact_matrix_text_" + guided._signature(scope)
    note = "Synthetic new contact note delivered with Undo."
    app.session_state[widget] = note
    app.session_state[widget + "_explicitly_edited"] = {
        "text": note, "baseline": contact.fingerprint,
        "result": guided._edited_rich_text(contact, note).fingerprint,
        "scope": scope,
    }
    next(b for b in app.button
         if b.label == "Undo last directory Apply in this report").click().run()
    assert not app.exception
    assert any("newer contact or note edit is pending" in w.value for w in app.warning)
    after = next(b for b in current_draft(app, profile.key).blocks
                 if b.key == "contact_matrix")
    assert after.text == note
    assert UNDO_MARKER not in after.references
