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


def test_general_template_starts_without_rfi_but_reused_design_keeps_its_choice(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    period = ReportPeriod(2026, 9)
    profile = replace(synthetic_profiles()[0], excluded_sections=("training",))
    draft, _ = design_seed(profile, period, "Synthetic Editor")
    included = {s.key: s.included for s in draft.sections}
    assert not included["rfi"] and not included["training"] and included["activity"]
    # An existing contract design explicitly includes RFI, even without a report
    # snapshot. The new-template default must not override that saved choice.
    source = library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
    target = replace(synthetic_profiles()[1], key="synthetic-target")
    reused, _ = design_seed(target, period, "Synthetic Editor", source)
    assert next(s for s in reused.sections if s.key == "rfi").included
    # More recent saved section choices take precedence over the profile.
    saved = replace(reused, profile=profile, sections=tuple(replace(s, included=s.key in ("rfi", "activity")) for s in reused.sections))
    library.save_snapshot(saved, expected_revision=0, entered_editor="Synthetic Editor")
    again, _ = design_seed(target, period, "Synthetic Editor", source)
    assert {s.key for s in again.sections if s.included} == {"rfi", "activity"}


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
    assert not any(c.type=="currency" or c.title in ("Cost","Amount") for s in draft.sections for b in s.blocks for c in b.columns)
    save_design_start(draft, assets, actor="Synthetic Editor", confirmed=True)
    library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic Editor")
    assert latest_snapshot(profile.contract, profile.key, ReportPeriod(2026, 9)).draft.period.month == 7
    assert latest_snapshot(profile.contract, profile.key, ReportPeriod(2026, 6)) is None
    # Reusing a saved snapshot must not turn image/text definitions into invalid
    # table overrides when the new design is saved.
    source=library.load_profile(profile.contract,profile.key)
    other=replace(synthetic_profiles()[1],key="another-site-set")
    copied,images=design_seed(other,ReportPeriod(2026,9),"Synthetic Editor",source)
    assert save_design_start(copied,images,actor="Synthetic Editor",confirmed=True).profile.key==other.key


def test_first_report_general_template_and_named_group_can_be_resumed(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == "Site name").set_value("Synthetic East; Synthetic West").run()
    next(w for w in app.text_input if w.label == "Name for this group (optional)").set_value("Synthetic Region").run()
    next(w for w in app.checkbox if w.label == "This is a regional report").check().run()
    assert not any(w.label == "Starting point" for w in app.radio)
    next(w for w in app.button if w.key and "report_start_card_use-the-general" in w.key).click().run()
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Editor").run()
    next(w for w in app.checkbox if w.label == "Save this design for these sites so we can use it next month").check().run()
    next(b for b in app.button if b.label == "Start this report").click().run()
    assert not app.exception
    assert next(w for w in app.radio if w.label == "Report steps").value.endswith("Report")
    assert next(w for w in app.text_input if w.label == "Name for this group (optional)").value == "Synthetic Region"
    assert not any(w.label == "Site / report" for w in app.selectbox)
    assert next(w for w in app.text_input if w.label == "Prepared by").value == "Synthetic Editor"
    assert any(w.label == "Include Organizational Chart" for w in app.checkbox)
    assert not any("logo" in w.label.lower() for w in app.get("file_uploader"))
    next(w for w in app.button if w.label == "Change logos").click().run()
    assert any(w.label == "New client logo" for w in app.get("file_uploader"))
    next(w for w in app.button if w.label == "Done with cover changes").click().run()
    step(app, 3)
    assert not any("logo" in w.label.lower() for w in app.get("file_uploader"))
    # Navigation is deliberately free: an unfinished standing section does not
    # prevent adding work now, then returning to complete it later.
    step(app, 2)
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic partial update.").run()
    step(app, 3)
    step(app, 2)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == "Synthetic partial update."


def test_latest_imported_design_wins_over_older_saved_month_without_using_future_work(monkeypatch, tmp_path):
    from app.monthly_report_start import latest_saved_draft, recommended_designs
    from app.monthly_report_setup import new_month_draft
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = synthetic_profiles()[0]
    august, assets = design_seed(profile, ReportPeriod(2026, 8), "Synthetic Editor")
    august = replace(august, sections=tuple(replace(s, included=s.key == "activity") for s in august.sections))
    save_design_start(august, assets, actor="Synthetic Editor", confirmed=True)
    july = replace(august, period=ReportPeriod(2026, 7), sections=tuple(replace(s, included=True) for s in august.sections))
    library.save_snapshot(july, expected_revision=0)
    seed = latest_saved_draft(profile.contract, profile.key, ReportPeriod(2026, 9), before=True)
    assert seed == august
    assert sum(s.included for s in new_month_draft(seed, ReportPeriod(2026, 9)).sections) == 1
    assert latest_saved_draft(profile.contract, profile.key, ReportPeriod(2026, 6)) is None
    changed = replace(august, prepared_by="Synthetic Colleague")
    library.save_snapshot(changed, expected_revision=0)
    assert latest_saved_draft(profile.contract, profile.key, ReportPeriod(2026, 8)) == changed
    other = replace(synthetic_profiles()[1], key="new-report")
    unrelated = replace(profile, contract="Other Synthetic Contract", key="other-contract")
    assert recommended_designs(other, (unrelated, profile), ReportPeriod(2026, 9)) == (profile,)


from tests.conftest import requires_libreoffice


@requires_libreoffice
def test_from_scratch_regional_report_generates_and_next_month_keeps_design(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from test_monthly_report_ui import ROOT, choose_report
    from app.contracts import RRH_CONTRACT
    from app.monthly_report_guided import STEPS
    import fitz
    app = monthly(monkeypatch, tmp_path, saved=False)
    next(w for w in app.text_input if w.label == "Site name").set_value("Synthetic Cedar; Synthetic Harbor; Synthetic Meadow").run()
    next(w for w in app.text_input if w.label == "Name for this group (optional)").set_value("Synthetic Lakes Region").run()
    next(w for w in app.checkbox if w.label == "This is a regional report").check().run()
    next(b for b in app.button if b.label == "Use ENFRA template").click().run()
    next(w for w in app.text_input if w.label == "Your name").set_value("Synthetic Editor").run()
    next(w for w in app.checkbox if w.label == "Save this design for these sites so we can use it next month").check().run()
    next(b for b in app.button if b.label == "Start this report").click().run()
    for label in [w.label for w in app.checkbox if w.label.startswith("Include ") and w.label not in ("Include Organizational Chart", "Include Monthly Activity Summary")]:
        next(w for w in app.checkbox if w.label == label).uncheck().run()
    next(b for b in app.button if b.label == "Continue to this month’s work").click().run()
    next(w for w in app.text_area if w.label == "Activity summary").set_value("Synthetic team completed the September inspection.").run()
    step(app, 3)
    next(b for b in app.button if b.label == "Start an editable org chart").click().run()
    next(w for w in app.text_input if w.label == "Name").set_value("Synthetic Manager").run()
    next(w for w in app.checkbox if w.label == "I checked the standing information for these sites").check().run()
    step(app, 4)
    generate = next(b for b in app.button if b.label == "Generate DOCX and PDF")
    assert not generate.disabled, [w.value for w in (*app.error, *app.warning)]
    generate.click().run(timeout=60)
    assert not app.exception
    assert {w.label for w in app.get("download_button")} == {"Download DOCX", "Download PDF"}
    package = next(v for k, v in app.session_state.filtered_state.items() if k.endswith("_package"))
    with fitz.open(stream=package.pdf, filetype="pdf") as pdf:
        assert pdf.page_count >= 6
        assert "September 2026" in pdf[0].get_text()
        assert "Synthetic team completed" in " ".join(p.get_text() for p in pdf)
    assert "September 2026" in package.docx_name
    profile = library.list_profiles(RRH_CONTRACT)[0]
    saved = library.load_snapshot(RRH_CONTRACT, profile.key, ReportPeriod(2026, 9))
    assert len(saved.draft.profile.facilities) == 3
    next_app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    next_app.segmented_control[0].set_value("Monthly report").run()
    choose_report(next_app)
    for site in profile.facilities:
        next(w for w in next_app.checkbox if w.label == site.title).check().run()
    next_app.selectbox("report_month_number").set_value(10).run()
    assert next(w for w in next_app.text_input if w.label == "Name for this group (optional)").value == "Synthetic Lakes Region"
    assert next(w for w in next_app.checkbox if w.label == "This is a regional report").value
    assert sum(w.value for w in next_app.checkbox if w.label.startswith("Include ")) == 2
    step(next_app, 2)
    assert next(w for w in next_app.text_area if w.label == "Activity summary").value == ""
    step(next_app, 3)
    assert next(w for w in next_app.text_input if w.label == "Name").value == "Synthetic Manager"
    assert not next(w for w in next_app.checkbox if w.label == "I checked the standing information for these sites").value
    assert next(r for r in next_app.radio if r.label == "Report steps").value == STEPS[2]
