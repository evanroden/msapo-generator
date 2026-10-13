"""Normal monthly selection, distinct from the fixed-target shared-test UI.

These AppTest journeys execute production run_web against temporary storage.
Preview rendering is suppressed by the existing navigation fixture; they prove
server/widget behavior, not pointer hit targets or real-browser checkbox DOM.
"""
from dataclasses import replace

from streamlit.testing.v1 import AppTest

from app import monthly_report_library as library
from app.contracts import RRH_CONTRACT
from app.monthly_report_model import ResolvedBlock, default_sections, synthetic_profiles
from test_monthly_report_ui import ROOT, choose_report, monthly


def _sites(app):
    return [item for item in app.checkbox if item.key and item.key.startswith("report_sites_")
            and "_region_" not in item.key]


def _box(app, label):
    return next(item for item in _sites(app) if item.label == label)


def _selected(app):
    return tuple(item.label for item in _sites(app) if item.value)


def _activity(app):
    return next(item for item in app.text_area if item.label == "Activity summary")


def test_normal_catalog_single_combined_uncheck_all_and_reentry(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    options = _sites(app)
    assert len(options) >= 2
    assert len({item.key for item in options}) == len(options)
    first, second = options[0].label, options[-1].label
    assert not _selected(app)
    _box(app, first).check().run()
    assert not app.exception
    assert _selected(app) == (first,)
    assert any(item.value == "Sites selected (1): " + first for item in app.caption)
    _box(app, second).check().run()
    assert not app.exception
    assert set(_selected(app)) == {first, second}
    assert any(item.value.startswith("Sites selected (2):") for item in app.caption)
    _box(app, first).uncheck().run()
    assert not app.exception
    assert _selected(app) == (second,)
    app.run()
    assert _selected(app) == (second,)  # A false checkbox is not uninitialized.
    _box(app, second).uncheck().run()
    assert not app.exception
    assert not _selected(app)
    assert any(item.value == "Select at least one site to continue." for item in app.info)
    assert not any(item.label == "Starting report" for item in app.get("file_uploader"))
    app.run()
    assert not _selected(app)
    _box(app, first).check().run()
    assert _selected(app) == (first,)
    assert any(item.label == "Starting report" for item in app.get("file_uploader"))
    assert library.list_profiles(RRH_CONTRACT) == ()  # Selection alone never saves standing data.


def test_normal_custom_site_add_remove_and_duplicate_recovery(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path, saved=False)
    catalog = _sites(app)[0].label
    _box(app, catalog).check().run()
    custom = next(item for item in app.text_input if item.label == "Site name")
    custom.input("Synthetic Annex; Synthetic West Campus").run()
    assert not app.exception
    assert any(item.value.startswith("Sites selected (3):") and "Synthetic Annex" in item.value
               and "Synthetic West Campus" in item.value for item in app.caption)
    next(item for item in app.text_input if item.label == "Site name").input("Synthetic Annex").run()
    assert any(item.value.startswith("Sites selected (2):") and "Synthetic Annex" in item.value for item in app.caption)
    _box(app, catalog).uncheck().run()
    assert not app.exception
    assert any(item.value == "Sites selected (1): Synthetic Annex" for item in app.caption)
    next(item for item in app.text_input if item.label == "Site name").input("Synthetic Annex; Synthetic Annex").run()
    assert not app.exception
    assert any("included more than once" in item.value for item in app.warning)
    next(item for item in app.text_input if item.label == "Site name").input("Synthetic Annex").run()
    assert not app.exception
    assert any(item.label == "Starting report" for item in app.get("file_uploader"))
    next(item for item in app.text_input if item.label == "Site name").input("").run()
    assert any(item.value == "Select at least one site to continue." for item in app.info)


def test_saved_single_and_combined_site_selection_returns_to_each_unchanged_draft(monkeypatch, tmp_path):
    # Initialize the standard normal-route test environment without saved data.
    monthly(monkeypatch, tmp_path, saved=False)
    north, south = synthetic_profiles()[1].facilities
    activity_only = tuple(section.key for section in default_sections() if section.key != "activity")
    individual = replace(synthetic_profiles()[0], contract=RRH_CONTRACT, key="synthetic-single-selection",
                         excluded_sections=activity_only)
    combined = replace(synthetic_profiles()[1], contract=RRH_CONTRACT, key="synthetic-combined-selection",
                       excluded_sections=activity_only)
    for profile, text in ((individual, "Synthetic single initial."), (combined, "Synthetic combined initial.")):
        library.save_profile(profile, expected_revision=0, actor="Synthetic Editor", confirmed=True)
        library.replace_block(profile.contract, profile.key, "activity_summary",
                              ResolvedBlock("activity_summary", "Library", text=text),
                              expected_revision=1, actor="Synthetic Editor", confirmed=True,
                              label="Synthetic selection test")
    app = AppTest.from_file(ROOT / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, north.title)
    assert _activity(app).value == "Synthetic single initial."
    _activity(app).input("Synthetic single manually revised.").run()
    _box(app, south.title).check().run()
    assert not app.exception
    assert set(_selected(app)) == {north.title, south.title}
    assert _activity(app).value == "Synthetic combined initial."
    _activity(app).input("Synthetic combined manually revised.").run()
    _box(app, south.title).uncheck().run()
    assert not app.exception
    assert _selected(app) == (north.title,)
    assert _activity(app).value == "Synthetic single manually revised."
    _box(app, south.title).check().run()
    assert _activity(app).value == "Synthetic combined manually revised."
    for workflow in ("Purchase order", "Expense reimbursement"):
        app.segmented_control[0].set_value(workflow).run()
        app.segmented_control[0].set_value("Monthly report").run()
        assert not app.exception
        assert set(_selected(app)) == {north.title, south.title}
        assert _activity(app).value == "Synthetic combined manually revised."
    assert library.load_profile(RRH_CONTRACT, individual.key).revision == 2
    assert library.load_profile(RRH_CONTRACT, combined.key).revision == 2
