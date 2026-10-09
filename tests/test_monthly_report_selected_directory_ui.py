"""Report-scoped inline contacts: no cross-contract or single-site fallback."""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_directory as directory
from app import monthly_report_directory_ui as ui
from app.monthly_report_model import Facility

APP = '''
import streamlit as st
from app.monthly_report_directory_ui import render_selected_directory
from app.monthly_report_model import Facility
render_selected_directory("Rochester Regional Health", (
    Facility("unity", "Unity Hospital"), Facility("ush", "Unity Specialty Hospital")),
    st.session_state.get("actor", "Synthetic Editor"), "report")
'''


def seed(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    sites = tuple(directory.DirectorySite(key, title, contacts=(directory.DirectoryContact(
        "Manager", name, email=key + "@example.invalid"),)) for key, title, name in (
        ("unity", "Unity Hospital", "Synthetic Unity Person"),
        ("ush", "Unity Specialty Hospital", "Synthetic USH Person"),
        ("other", "Other RRH Site", "Excluded Person")))
    state = directory.save_directory("Rochester Regional Health", sites, expected_revision=0,
                                     actor="Synthetic Seeder", confirmed=True)
    other = directory.save_directory("Adventist Health", (directory.DirectorySite("elsewhere", "Elsewhere",
        contacts=(directory.DirectoryContact("Manager", "Excluded Adventist Person"),)),),
        expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    return state, other


def test_both_selected_sites_visible_no_contract_or_site_dropdown(monkeypatch, tmp_path):
    seed(monkeypatch, tmp_path)
    app = AppTest.from_string(APP, default_timeout=20).run()
    assert not app.exception and not app.selectbox and not app.radio
    frames = [frame.value for frame in app.dataframe]
    assert frames[0]["Site"].tolist() == ["Unity Hospital", "Unity Specialty Hospital"]
    text = " ".join(str(frame) for frame in frames)
    assert "Synthetic Unity Person" in text and "Synthetic USH Person" in text
    assert "Excluded" not in text and "Adventist" not in text


def test_save_updates_both_selected_sites_and_preserves_other_records(monkeypatch, tmp_path):
    initial, other = seed(monkeypatch, tmp_path)
    original_grid = ui._grid
    def edit_grid(key, rows, **kwargs):
        result = original_grid(key, rows, **kwargs)
        if "_contacts_unity" in key or "_contacts_ush" in key:
            result = [dict(row, Phone="202-555-0199") for row in result]
        return result
    monkeypatch.setattr(ui, "_grid", edit_grid)
    app = AppTest.from_string(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == "Save contacts to directory and report").click().run()
    assert not app.exception
    saved = directory.load_directory(initial.contract)
    assert saved.revision == 2 and saved.actor == "Synthetic Editor"
    assert [s.contacts[0].phone for s in saved.sites[:2]] == ["202-555-0199"] * 2
    assert saved.sites[2] == initial.sites[2]
    assert directory.load_directory(other.contract) == other
    assert directory.load_directory(initial.contract, 1) == initial


def test_inline_blank_name_does_not_load_saved_contacts(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No saved contact reads without attribution")
    monkeypatch.setattr(directory, "load_directory", forbidden)
    app = AppTest.from_string(APP, default_timeout=20)
    app.session_state["actor"] = " "
    app.run()
    assert not app.exception and not app.dataframe and not app.button


def test_inactive_or_ambiguous_site_never_falls_back(monkeypatch, tmp_path):
    import pytest
    state, _ = seed(monkeypatch, tmp_path)
    state = replace(state, sites=(replace(state.sites[0], active=False), *state.sites[1:]))
    with pytest.raises(ValueError, match="needs to be resolved"):
        ui.selected_directory_sites(state, (Facility("unity", "Unity Hospital"),))


def test_inline_save_conflict_keeps_concurrent_revision(monkeypatch, tmp_path):
    initial, _ = seed(monkeypatch, tmp_path)
    original_save = directory.save_directory
    def concurrent_save(contract, sites, **kwargs):
        original_save(contract, initial.sites, expected_revision=1,
                      actor="Concurrent Editor", confirmed=True)
        return original_save(contract, sites, **kwargs)
    monkeypatch.setattr(directory, "save_directory", concurrent_save)
    app = AppTest.from_string(APP, default_timeout=20).run()
    next(button for button in app.button if button.label == "Save contacts to directory and report").click().run()
    assert not app.exception
    assert any("Someone changed this directory" in error.value for error in app.error)
    saved = directory.load_directory(initial.contract)
    assert saved.revision == 2 and saved.actor == "Concurrent Editor"
    assert saved.sites == initial.sites


def test_explicit_directory_save_updates_working_preview_and_saved_report_only(monkeypatch, tmp_path):
    from io import BytesIO
    from PIL import Image
    from app import monthly_report_library as library, monthly_report_section_preview_ui as previews
    from app.monthly_report_model import ReportDraft, ReportPeriod, ResolvedBlock, synthetic_profiles
    from app.monthly_report_start import design_seed
    from test_monthly_report_ui import monthly, choose_report, ROOT

    initial, _ = seed(monkeypatch, tmp_path)
    profile = replace(synthetic_profiles()[1], contract=initial.contract, key="unity-ush-test",
                      title="Unity and USH", facilities=(Facility("unity", "Unity Hospital"), Facility("ush", "Unity Specialty Hospital")))
    library.save_profile(profile, expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Seeder")
    original_contacts = ResolvedBlock("contact_matrix", "This month", rows=(
        ("Unity Hospital", "Manager", "Original report person", "Original phone", "report@example.invalid"),))
    draft = directory.apply_contacts(draft, original_contacts)
    raw = BytesIO()
    Image.new("RGB", (20, 20), "green").save(raw, "PNG")
    ref = library.asset_reference(raw.getvalue(), "png")
    chart = ResolvedBlock("org_chart", "Replace once", asset_hashes=(ref,))
    draft = replace(draft, blocks=tuple(b for b in draft.blocks if b.key != "org_chart") + (chart,))
    snapshot = library.save_snapshot(draft, expected_revision=0, assets=((ref, raw.getvalue()),), entered_editor="Synthetic Seeder")
    other_profile = replace(profile, key="other-report", title="Other report", facilities=(Facility("other", "Other RRH Site"),), scope_type="individual")
    library.save_profile(other_profile, expected_revision=0, actor="Synthetic Seeder", confirmed=True)
    other_draft, _ = design_seed(other_profile, draft.period, "Synthetic Seeder")
    other_snapshot = library.save_snapshot(other_draft, expected_revision=0, entered_editor="Synthetic Seeder")

    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, "Unity Hospital")
    next(w for w in app.checkbox if w.label == "Unity Specialty Hospital").check().run()
    next(w for w in app.text_input if w.label == "Prepared by").set_value("Synthetic Editor").run()
    def current(app):
        return next(value for value in app.session_state.filtered_state.values()
                    if isinstance(value, ReportDraft) and value.profile.key == profile.key)
    assert next(b for b in current(app).blocks if b.key == "contact_matrix") == original_contacts
    previous_chart = next(b for b in current(app).blocks if b.key == "org_chart")
    observed = []
    monkeypatch.setattr(previews, "render_section_preview", lambda draft, key, *args, **kwargs: observed.append((key, draft)))
    original_grid = ui._grid
    def edit_grid(key, rows, **kwargs):
        edited = original_grid(key, rows, **kwargs)
        return [dict(row, Phone="202-555-0177") for row in edited] if "_contacts_unity" in key or "_contacts_ush" in key else edited
    monkeypatch.setattr(ui, "_grid", edit_grid)
    next(b for b in app.button if b.label == "Save contacts to directory and report").click().run()
    assert not app.exception
    changed = current(app)
    contact_block = next(b for b in changed.blocks if b.key == "contact_matrix")
    assert len(contact_block.rows) == 2 and all(row[3] == "202-555-0177" for row in contact_block.rows)
    assert next(b for b in changed.blocks if b.key == "org_chart") == previous_chart
    assert any(key == "organization" and contact_block in shown.blocks for key, shown in observed)
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == snapshot
    assert library.load_snapshot(other_profile.contract, other_profile.key, draft.period) == other_snapshot
    next(b for b in app.button if b.label == "Save progress").click().run()
    assert not app.exception
    saved = library.load_snapshot(profile.contract, profile.key, draft.period)
    assert contact_block in saved.draft.blocks
    assert library.load_snapshot(other_profile.contract, other_profile.key, draft.period) == other_snapshot
    assert directory.load_directory(initial.contract).sites[2] == initial.sites[2]
    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, "Unity Hospital")
    next(w for w in reopened.checkbox if w.label == "Unity Specialty Hospital").check().run()
    assert not reopened.exception
    assert contact_block in current(reopened).blocks


def test_other_editors_directory_change_refreshes_only_the_open_working_copy(monkeypatch, tmp_path):
    from app import monthly_report_library as library, monthly_report_section_preview_ui as previews
    from app.monthly_report_model import ReportDraft, ReportPeriod, synthetic_profiles
    from app.monthly_report_start import design_seed
    from test_monthly_report_ui import monthly, choose_report

    initial, _ = seed(monkeypatch, tmp_path)
    profile = replace(synthetic_profiles()[0], contract=initial.contract, key='linked-contacts',
                      title='Linked contacts', facilities=(Facility('unity', 'Unity Hospital'),), scope_type='individual')
    library.save_profile(profile, expected_revision=0, actor='Synthetic Seeder', confirmed=True)
    draft, _ = design_seed(profile, ReportPeriod(2026, 9), 'Synthetic Seeder')
    draft = directory.apply_defaults(draft)
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Seeder')
    app = monthly(monkeypatch, tmp_path, saved=False)
    choose_report(app, 'Unity Hospital')
    next(w for w in app.text_input if w.label == 'Prepared by').set_value('Synthetic Editor').run()
    assert not app.exception
    latest = directory.save_directory(initial.contract, (
        replace(initial.sites[0], contacts=(directory.DirectoryContact('Manager', 'New Shared Person', email='new@example.invalid'),)),
        *initial.sites[1:]), expected_revision=1, actor='Other Editor', confirmed=True)
    observed = []
    monkeypatch.setattr(previews, 'render_section_preview', lambda shown, key, *a, **k: observed.append((key, shown)))
    app.run()
    assert not app.exception
    working = next(value for value in app.session_state.filtered_state.values()
                   if isinstance(value, ReportDraft) and value.profile.key == profile.key)
    contacts = next(b for b in working.blocks if b.key == 'contact_matrix')
    assert contacts.rows[0][2] == 'New Shared Person'
    assert any(key == 'organization' and contacts in shown.blocks for key, shown in observed)
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    assert directory.load_directory(initial.contract) == latest
