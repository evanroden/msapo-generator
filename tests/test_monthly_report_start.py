from dataclasses import replace
from io import BytesIO

from PIL import Image
import pytest

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ReportTable, ResolvedBlock, synthetic_profiles
from app.monthly_report_start import design_seed, save_design_start, membership_key, matching_profiles, report_key, latest_snapshot
from test_monthly_report_ui import monthly, step


def test_standing_confirmation_tracks_branding_changes_not_review_flags():
    from app.monthly_report_guided import _standing_signature
    logo = ResolvedBlock("client_logo", "Replace once", asset_hashes=("first.png",))
    first = _standing_signature((logo,), set())
    assert _standing_signature((replace(logo, client_reviewed_fingerprint=logo.fingerprint),), set()) == first
    assert _standing_signature((replace(logo, asset_hashes=("replacement.png",)),), set()) != first


def test_membership_is_explicit_order_independent_and_name_does_not_change_identity():
    group = synthetic_profiles()[1]
    assert membership_key(group.facilities) == membership_key(tuple(reversed(group.facilities)))
    assert report_key(group.facilities) == report_key(replace(group, title="Synthetic Western Region").facilities)
    assert matching_profiles((group,), group.facilities) == (group,)
    assert not matching_profiles((group,), group.facilities[:1])


def test_new_design_is_atomic_confirmed_and_remembers_assets_without_other_site_content(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    source_profile = synthetic_profiles()[0]
    state = library.save_profile(source_profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    image = BytesIO()
    Image.new("RGBA", (100, 30), (0, 50, 20, 0)).save(image, "PNG")
    ref = library.asset_reference(image.getvalue(), "png")
    state = library.replace_block(source_profile.contract, source_profile.key, "client_logo", ResolvedBlock("client_logo", "Library", asset_hashes=(ref,)),
                                  assets=((ref, image.getvalue()),), expected_revision=state.revision, actor="Synthetic Editor", confirmed=True, label="Logo")
    state = library.replace_block(source_profile.contract, source_profile.key, "contact_matrix", ResolvedBlock("contact_matrix", "Library", text="Other site's contact", extra_tables=(ReportTable(("Role", "Name"), (("Lead", "Synthetic Person"),)),)), expected_revision=state.revision, actor="Synthetic Editor", confirmed=True, label="Contacts")
    profile = replace(synthetic_profiles()[1], key="new-group")
    draft, assets = design_seed(profile, ReportPeriod(2026, 9), "Synthetic Editor", state)
    assert draft.profile.facilities == profile.facilities
    assert not any("Other site" in b.text or "Synthetic Person" in str(b.rows) for b in draft.blocks)
    contacts = next(b for b in draft.blocks if b.key == "contact_matrix")
    assert contacts.extra_tables[0].columns == ("Role", "Name") and not contacts.extra_tables[0].rows
    assert next(b for b in draft.blocks if b.key == "client_logo").asset_hashes == (ref,)
    with pytest.raises(ValueError):
        save_design_start(draft, assets, actor="Synthetic Editor", confirmed=False)
    saved = save_design_start(draft, assets, actor="Synthetic Editor", confirmed=True)
    assert saved.revision == 1 and library.load_imported_draft(profile.contract, profile.key) == draft
    with pytest.raises(library.RevisionConflict):
        save_design_start(draft, assets, actor="Synthetic Editor", confirmed=True)
    assert library.read_asset(profile.contract, profile.key, ref) == image.getvalue()


def test_latest_saved_design_survives_a_gap_in_reporting(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    draft, assets = design_seed(profile, ReportPeriod(2026, 7), "Synthetic Editor")
    save_design_start(draft, assets, actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    assert latest_snapshot(profile.contract, profile.key, ReportPeriod(2026, 9)).draft.period.month == 7
    assert latest_snapshot(profile.contract, profile.key, ReportPeriod(2026, 6)) is None


def test_first_report_general_template_and_named_group_can_be_resumed(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == "Site name").set_value("Synthetic East; Synthetic West").run()
    next(w for w in app.text_input if w.label == "Name for this group (optional)").set_value("Synthetic Region").run()
    next(w for w in app.checkbox if w.label == "This is a regional report").check().run()
    assert next(w for w in app.radio if w.label == "Starting point").value == "Use the general ENFRA monthly report template"
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Editor").run()
    next(w for w in app.checkbox if w.label == "Save this design for these sites so we can use it next month").check().run()
    next(b for b in app.button if b.label == "Start this report").click().run()
    assert not app.exception
    assert next(w for w in app.radio if w.label == "Report steps").value.endswith("Site information")
    assert next(w for w in app.text_input if w.label == "Name for this group (optional)").value == "Synthetic Region"
    assert not any(w.label == "Site / report" for w in app.selectbox)
    assert next(w for w in app.text_input if w.label == "Prepared by").value == "Synthetic Editor"
    assert any(w.label == "Updated client logo" for w in app.get("file_uploader"))
    # Navigation is deliberately free: an unfinished standing section does not
    # prevent adding work now, then returning to complete it later.
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic partial update.").run()
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == "Synthetic partial update."
