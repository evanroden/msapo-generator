"""An unavailable future master cannot strand an independently pinned report."""
from dataclasses import replace
from io import BytesIO
import json
from zipfile import ZipFile

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_designs as designs, monthly_report_library as library
from app.monthly_report_designs_ui import design_summary
from app.monthly_report_docx import assemble_docx
from app.monthly_report_model import (
    BlockSpec, ReportDraft, ReportPeriod, ResolvedBlock, SectionSpec, synthetic_profiles,
)
from app.monthly_report_start import design_seed
from test_monthly_report_designs import master_reference
from test_monthly_report_ui import ROOT, choose_report, monthly


PERIOD = ReportPeriod(2026, 9)
ACTOR = "Synthetic Design Editor"
DIGEST = "a" * 64


def encoded(**fields):
    return json.dumps({"schema": 1, **fields}).encode()


BAD_STATES = [
    ("malformed-json", b"{"),
    ("missing-revision", encoded(default=DIGEST)),
    ("nonstring-default", encoded(revision=1, default=42)),
    ("boolean-revision", encoded(revision=True, default=DIGEST)),
    ("invalid-digest", encoded(revision=1, default="invalid")),
    ("missing-default", encoded(revision=1)),
    ("negative-revision", encoded(revision=-1, default=DIGEST)),
    ("string-revision", encoded(revision="1", default=DIGEST)),
    ("null-default", encoded(revision=1, default=None)),
    ("uppercase-digest", encoded(revision=1, default="A" * 64)),
]


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


def write_manifest(raw):
    path = library._root() / "designs" / "master" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def files(root=None):
    root = library._root() if root is None else root
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and path.name != ".write-lock"}


def element(app, kind, label):
    return next(value for value in getattr(app, kind) if value.label == label)


def ready_report(profile):
    section = SectionSpec("activity", "2", "Monthly Activity Summary",
                          (BlockSpec("activity_summary", "rich_text"),))
    return ReportDraft(profile, PERIOD, ACTOR, (section,),
                       (ResolvedBlock("activity_summary", "This month",
                                      text="Synthetic retained monthly work."),))


def two_masters(tmp_path):
    old = designs.install_master(master_reference(tmp_path, "old", "Synthetic older design"),
                                 actor=ACTOR, expected_revision=0)
    profile = designs.pin(synthetic_profiles()[0])
    new = designs.install_master(master_reference(tmp_path, "new", "Synthetic future design"),
                                 actor=ACTOR, expected_revision=1)
    assert old != new and profile.template == designs.MASTER_PREFIX + old
    return profile, new


@pytest.mark.parametrize("damage,older_master", [
    *(pytest.param(raw, False, id=name) for name, raw in BAD_STATES[:5]),
    pytest.param(b"{", True, id="older-master-pin"),
])
def test_saved_report_remains_editable_and_reopens_with_its_pin(
        monkeypatch, tmp_path, damage, older_master):
    # This exercises the real Monthly entry point. Preview conversion alone is
    # stubbed by monthly(); the independent DOCX test below uses real assembly.
    monkeypatch.setattr("app.web_ui.device_token", lambda cookies: "")
    if older_master:
        old = designs.install_master(master_reference(tmp_path, "old", "Synthetic older design"),
                                     actor=ACTOR, expected_revision=0)
    app = monthly(monkeypatch, tmp_path / "runtime")
    element(app, "text_input", "Prepared by").set_value(ACTOR).run()
    element(app, "text_area", "Activity summary").set_value("Synthetic saved activity.").run()
    element(app, "button", "Save shared version").click().run()
    profile = library.list_profiles(app.session_state["report_contract"])[0]
    saved = library.load_snapshot(profile.contract, profile.key, PERIOD)
    expected_pin = saved.draft.profile.template
    assert expected_pin.startswith(designs.MASTER_PREFIX if older_master else designs.BUILTIN_PREFIX)
    if older_master:
        assert expected_pin == designs.MASTER_PREFIX + old
        designs.install_master(master_reference(tmp_path, "new", "Synthetic future design"),
                               actor=ACTOR, expected_revision=1)
    path = write_manifest(damage)
    masters = files(path.parent)
    app.run()
    assert not app.exception
    assert element(app, "text_area", "Activity summary").value == "Synthetic saved activity."
    assert any("This report uses:" in caption.value for caption in app.caption)
    assert any("master" in warning.value.casefold() for warning in app.warning)
    assert not any("Available company master: version 0" in caption.value for caption in app.caption)
    assert not any(button.label == "Apply current master to this report" for button in app.button)
    element(app, "text_area", "Activity summary").set_value("Synthetic edit during master recovery.").run()
    element(app, "button", "Save shared version").click().run()
    assert not app.exception
    updated = library.load_snapshot(profile.contract, profile.key, PERIOD)
    assert updated.revision == saved.revision + 1
    assert updated.draft.profile.template == expected_pin
    assert next(b.text for b in updated.draft.blocks if b.key == "activity_summary") == (
        "Synthetic edit during master recovery.")
    assert library.load_snapshot_version(profile.contract, profile.key, PERIOD, saved.revision) == saved
    assert files(path.parent) == masters

    reopened = AppTest.from_file(ROOT / "run_web.py", default_timeout=20).run()
    reopened.segmented_control[0].set_value("Monthly report").run()
    choose_report(reopened, profile.facilities[0].title)
    assert not reopened.exception
    assert element(reopened, "text_area", "Activity summary").value == "Synthetic edit during master recovery."
    assert any(button.label == "Save shared version" for button in reopened.button)
    reopened.run()
    assert not reopened.exception and files(path.parent) == masters
    assert library.load_snapshot(profile.contract, profile.key, PERIOD) == updated


@pytest.mark.parametrize("damage", [pytest.param(raw, id=name) for name, raw in BAD_STATES])
def test_master_catalog_rejects_bad_required_fields_without_rewriting_them(damage):
    write_manifest(damage)
    before = files()
    with pytest.raises(library.LibraryError):
        designs.master_state()
    assert files() == before


@pytest.mark.parametrize("operation", ["pin", "seed", "install"])
@pytest.mark.parametrize("damage", [pytest.param(raw, id=name) for name, raw in BAD_STATES[1:3]])
def test_fresh_design_selection_and_installation_do_not_replace_bad_master_state(
        tmp_path, operation, damage):
    source = master_reference(tmp_path)
    write_manifest(damage)
    before = files()
    with pytest.raises(library.LibraryError):
        if operation == "pin":
            designs.pin(synthetic_profiles()[0])
        elif operation == "seed":
            design_seed(synthetic_profiles()[0], PERIOD, ACTOR)
        else:
            designs.install_master(source, actor=ACTOR, expected_revision=1)
    assert files() == before


def test_new_report_does_not_silently_fall_back_when_master_default_is_missing(monkeypatch, tmp_path):
    app = monthly(monkeypatch, tmp_path / "runtime", saved=False)
    path = write_manifest(encoded(revision=1))
    before = files()
    next(w for w in app.checkbox if w.key.startswith("report_sites_")).check().run()
    assert not app.exception
    assert app.error
    assert not any(b.label in {"Use ENFRA template", "Start this report"} for b in app.button)
    assert files() == before and path.read_bytes() == encoded(revision=1)


@pytest.mark.parametrize("revision,default", [(0, ""), (2, ""), (3, DIGEST)])
def test_valid_and_legacy_empty_master_records_preserve_history(revision, default):
    value = {"schema": 1, "revision": revision, "default": default,
             "history": [{"legacy_marker": "retain exactly"}]}
    raw = json.dumps(value).encode()
    path = write_manifest(raw)
    assert designs.master_state() == value
    profile = replace(synthetic_profiles()[0], template=designs.BUILTIN_PREFIX + "monthly_review_v1")
    assert design_summary(ready_report(profile)) == ("Built-in report design", revision)
    assert path.read_bytes() == raw


def test_absent_master_remains_an_explicit_zero_version_without_creating_a_record():
    assert designs.master_state() == {"revision": 0, "default": "", "history": []}
    profile = designs.pin(synthetic_profiles()[0])
    assert design_summary(ready_report(profile)) == ("Built-in report design", 0)
    assert files() == {}


def test_damaged_latest_manifest_does_not_change_older_pinned_word_output(tmp_path):
    profile, _ = two_masters(tmp_path)
    draft = ready_report(profile)
    saved = library.save_snapshot(draft, expected_revision=0)
    original = assemble_docx(draft)
    path = write_manifest(b"{")
    before = files()
    reopened = library.load_snapshot(profile.contract, profile.key, PERIOD)
    result = assemble_docx(reopened.draft)
    with ZipFile(BytesIO(original)) as left, ZipFile(BytesIO(result)) as right:
        assert {name: left.read(name) for name in left.namelist()} == {
            name: right.read(name) for name in right.namelist()}
        assert b"Synthetic retained monthly work." in right.read("word/document.xml")
    assert reopened == saved and files() == before
    # Losing the report's own design remains a hard output failure. Moving this
    # temporary synthetic file leaves its immutable content-addressed bytes intact.
    source = designs.source_for(profile)
    missing = source.with_suffix(".temporarily-missing")
    source.rename(missing)
    try:
        with pytest.raises(ValueError, match="unavailable"):
            assemble_docx(reopened.draft)
    finally:
        missing.rename(source)
    assert files() == before and path.read_bytes() == b"{"


def test_failed_explicit_apply_retains_draft_and_preview_until_target_recovers(tmp_path):
    profile, current = two_masters(tmp_path)
    draft = ready_report(profile)
    app = AppTest.from_string('''
import streamlit as st
from app.monthly_report_designs_ui import render_apply_master_design
render_apply_master_design(st.session_state['test_draft'], 'test')
''', default_timeout=20)
    cache = {"synthetic-preview": "keep existing preview"}
    app.session_state["test_draft"] = draft
    app.session_state["test_section_preview_cache"] = cache
    app.run()
    assert not app.exception
    apply = element(app, "button", "Apply current master to this report")
    metadata = library._root() / "designs" / "master" / "metadata" / (current + ".json")
    original = metadata.read_bytes()
    metadata.write_bytes(b"{")
    before = files()
    apply.click().run()
    assert not app.exception and app.warning
    assert app.session_state["test_draft"] == draft
    assert app.session_state["test_section_preview_cache"] == cache and files() == before
    app.run()
    assert not app.exception and app.session_state["test_draft"] == draft
    metadata.write_bytes(original)
    element(app, "button", "Apply current master to this report").click().run()
    assert not app.exception
    assert app.session_state["test_draft"].profile.template == designs.MASTER_PREFIX + current
    assert app.session_state["test_draft"].blocks == draft.blocks
    assert "test_section_preview_cache" not in app.session_state
