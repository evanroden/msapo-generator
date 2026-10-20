"""Synthetic persisted-copy recovery, current report identity and pinned design.

AppTest exercises the actual recovery UI and library/journal mutations. It is
not native browser input delivery or a production-draft recovery operation.
"""
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_compare_ui import compare_drafts
from app.monthly_report_model import Facility, ReportDraft, ReportPeriod, ReportProfile, ResolvedBlock, default_sections


TOKEN = "c" * 32
PERIOD = ReportPeriod(2026, 9)
PREFIX = "synthetic_recovery_identity"
PROFILE = ReportProfile("Synthetic recovery contract", "report-a", "Original report group",
                        (Facility("north", "Synthetic North"), Facility("south", "Synthetic South")),
                        scope_type="multi_site", template="enfra_builtin:monthly_review_v1")
SOURCE = '''
import streamlit as st
from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_active_conflict_ui import render_older_draft_conflict, render_browser_conflict
token, contract, selected, period, prefix = st.session_state["target"]
if st.session_state["mode"] == "older":
    current = active.load(token, contract, selected, period)
    snapshot = library.load_snapshot(contract, selected, period)
    chosen = render_older_draft_conflict(current, snapshot, token, prefix)
    if chosen is not None:
        st.session_state["chosen"] = chosen
else:
    render_browser_conflict(st.session_state[prefix + "_draft"], token, prefix, {}, 0)
'''


def button(app, label):
    return next(item for item in app.button if item.label == label)


def setup(monkeypatch, tmp_path, mode, *, draft_pin=None, saved_pin=None, page_pin=None,
          with_snapshot=True):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    library.save_profile(PROFILE, expected_revision=0, actor="Synthetic setup", confirmed=True)
    draft = ReportDraft(PROFILE, PERIOD, "Synthetic unfinished author", default_sections(),
                        (ResolvedBlock("activity_summary", "This month", text="Unfinished repair wording."),))
    if draft_pin:
        draft = replace(draft, profile=replace(draft.profile, template=draft_pin))
    unfinished = active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=0)
    completed = replace(draft, prepared_by="Synthetic shared author", blocks=(
        replace(draft.blocks[0], text="Completed saved wording."),))
    if saved_pin:
        completed = replace(completed, profile=replace(completed.profile, template=saved_pin))
    snapshot = (library.save_snapshot(completed, expected_revision=0, entered_editor="Synthetic shared author")
                if with_snapshot else None)
    app = AppTest.from_string(SOURCE)
    app.session_state["target"] = (TOKEN, PROFILE.contract, PROFILE.key, PERIOD, PREFIX)
    app.session_state["mode"] = mode
    app.session_state[PREFIX + "_draft"] = replace(draft, blocks=(
        replace(draft.blocks[0], text="Keep this page's later manual wording."),))
    if page_pin:
        current = app.session_state[PREFIX + "_draft"]
        app.session_state[PREFIX + "_draft"] = replace(current, profile=replace(current.profile, template=page_pin))
    app.run()
    assert not app.exception
    button(app, "Review draft changes" if mode == "older" else "Compare browser copies").click().run()
    assert not app.exception
    return app, unfinished, snapshot


@pytest.mark.parametrize("mode", ["older", "browser"])
def test_recovery_shows_an_identical_design_once_for_both_copies_without_writing(
        monkeypatch, tmp_path, mode):
    pin = "enfra_master:" + "5" * 64
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode, draft_pin=pin)
    before_profile = library.load_profile(PROFILE.contract, PROFILE.key)
    before_page = app.session_state[PREFIX + "_draft"]
    for _ in range(2):
        receipts = [item.value for item in app.caption if "Report design" in item.value]
        assert len(receipts) == 1
        assert "both copies" in receipts[0] and "ENFRA company master" in receipts[0]
        assert pin.removeprefix("enfra_master:") in receipts[0]
        assert not any(item.label == "Pinned report design" for item in app.expander)
        assert active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
        assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
        assert library.load_profile(PROFILE.contract, PROFILE.key) == before_profile
        assert app.session_state[PREFIX + "_draft"] == before_page
        app.run()
        assert not app.exception


@pytest.mark.parametrize("mode", ["older", "browser"])
def test_recovery_design_receipts_identify_each_different_copy_without_resolving_shared_defaults(
        monkeypatch, tmp_path, mode):
    first, second = "enfra_master:" + "6" * 64, "enfra_native:" + "7" * 64
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode, draft_pin=first,
        saved_pin=second if mode == "older" else None, page_pin=second if mode == "browser" else None)
    before_profile = library.load_profile(PROFILE.contract, PROFILE.key)
    receipts = [item.value for item in app.caption if "Report design" in item.value]
    assert len(receipts) == 2 and not any("both copies" in value for value in receipts)
    labels = (("Unfinished draft", first), ("Saved report", second)) if mode == "older" else (
        ("This page", second), ("Newer browser copy", first))
    for label, pin in labels:
        matching = [value for value in receipts if label in value]
        assert len(matching) == 1 and pin.split(":", 1)[1] in matching[0]
    assert any(item.label == "Pinned report design" for item in app.expander)
    assert active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    assert library.load_profile(PROFILE.contract, PROFILE.key) == before_profile


def test_missing_saved_version_still_displays_the_available_drafts_design_without_creating_a_version(
        monkeypatch, tmp_path):
    pin = "enfra_native:" + "8" * 64
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, "older", draft_pin=pin, with_snapshot=False)
    assert snapshot is None
    receipts = [item.value for item in app.caption if "Report design" in item.value]
    assert len(receipts) == 1 and "Unfinished draft" in receipts[0]
    assert "Reference report design" in receipts[0] and "8" * 64 in receipts[0]
    assert "both copies" not in receipts[0]
    assert not any(item.label == "Open saved report" for item in app.button)
    assert active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) is None


def revise_identity(kind):
    state = library.load_profile(PROFILE.contract, PROFILE.key)
    if kind == "title":
        profile = replace(state.profile, title="Renamed report group")
    elif kind == "aliases":
        profile = replace(state.profile, facilities=(
            replace(state.profile.facilities[0], aliases=("North operating campus",)),
            state.profile.facilities[1]))
    elif kind == "scope":
        profile = replace(state.profile, scope_type="regional")
    else:
        raise AssertionError(kind)
    return library.save_profile(profile, expected_revision=state.revision,
                                actor="Synthetic other editor", confirmed=True)


CHOICES = [("older", "Continue with unfinished draft"), ("older", "Open saved report"),
           ("browser", "Keep this page for recovery"), ("browser", "Use the newer browser copy")]


@pytest.mark.parametrize("saved_pin,working_pin", [
    ("enfra_master:" + "1" * 64, "enfra_master:" + "2" * 64),
    ("enfra_native:" + "3" * 64, "enfra_master:" + "3" * 64),
    ("enfra_builtin:monthly_review_v1", "enfra_master:" + "4" * 64),
])
def test_layout_only_pin_change_is_a_meaningful_recovery_comparison(saved_pin, working_pin):
    draft = ReportDraft(PROFILE, PERIOD, "Synthetic author", default_sections(), ())
    saved = replace(draft, profile=replace(PROFILE, template=saved_pin))
    working = replace(draft, profile=replace(PROFILE, template=working_pin))
    change, = compare_drafts(working, saved)
    assert "design" in change.title.casefold()
    assert change.saved != change.working
    assert compare_drafts(saved, saved) == ()
    assert saved.profile.template == saved_pin and working.profile.template == working_pin


@pytest.mark.parametrize("mode,label", CHOICES)
@pytest.mark.parametrize("kind", ["title", "aliases", "scope"])
def test_old_recovery_choice_is_invalidated_by_a_later_current_report_identity(
        monkeypatch, tmp_path, mode, label, kind):
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode)
    old_action = button(app, label)
    working = app.session_state[PREFIX + "_draft"]
    current = revise_identity(kind)
    old_action.click().run()
    assert not app.exception
    assert active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    assert library.load_profile(PROFILE.contract, PROFILE.key) == current
    assert app.session_state[PREFIX + "_draft"] == working
    assert "chosen" not in app.session_state
    assert button(app, label).key != old_action.key
    assert any("changed" in item.value.casefold() for item in app.info)


@pytest.mark.parametrize("mode,label", CHOICES)
def test_reviewed_current_identity_is_the_one_kept_on_the_first_persisted_choice(
        monkeypatch, tmp_path, mode, label):
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode)
    current = revise_identity("title")
    app.run()
    assert not app.exception
    assert current.profile.title in "\n".join(item.value for item in app.caption)
    before = active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD)
    assert before == unfinished
    button(app, label).click().run()
    assert not app.exception
    kept = active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD)
    assert kept.draft.profile.title == current.profile.title
    assert kept.draft.profile.facilities == current.profile.facilities
    expected = (snapshot.draft if label == "Open saved report" else unfinished.draft)
    if label == "Keep this page for recovery":
        expected = app.session_state[PREFIX + "_draft"]
    assert kept.draft.profile.template == expected.profile.template
    assert kept.draft.blocks == expected.blocks
    assert kept.generation == unfinished.generation
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    assert library.load_profile(PROFILE.contract, PROFILE.key) == current


@pytest.mark.parametrize("mode,label", [("older", "Open saved report"), ("browser", "Use the newer browser copy")])
def test_a_confirmed_identity_change_during_recovery_read_cannot_overtake_the_reviewed_choice(
        monkeypatch, tmp_path, mode, label):
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode)
    original_load = active.load
    calls, intervening = [], []
    # Older-draft UI reads once in its caller and once after the native choice.
    # Browser-copy UI reads its newer version while building that same choice.
    # Both are actual persisted library edits, before its eventual mutation.
    change_on = 2 if mode == "older" else 1
    def load_then_change(*args, **kwargs):
        result = original_load(*args, **kwargs)
        calls.append(None)
        if len(calls) == change_on:
            intervening.append(revise_identity("aliases"))
        return result
    monkeypatch.setattr(active, "load", load_then_change)
    button(app, label).click().run()
    assert not app.exception and len(intervening) == 1
    assert original_load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    assert library.load_profile(PROFILE.contract, PROFILE.key) == intervening[0]
    assert "chosen" not in app.session_state
    assert any("changed" in item.value.casefold() for item in app.error)


@pytest.mark.parametrize("mode,label", CHOICES)
def test_unrelated_standing_revision_does_not_invalidate_an_unchanged_report_identity(
        monkeypatch, tmp_path, mode, label):
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode)
    old_action = button(app, label)
    state = library.load_profile(PROFILE.contract, PROFILE.key)
    # A standing-content revision with the same report identity is independent
    # of this whole-copy browser choice. It must be retained, not reverted.
    updated = library.save_profile(replace(state.profile, asset_tags=("SYNTHETIC-AHU-0007",)),
                                   expected_revision=state.revision, actor="Synthetic inventory editor", confirmed=True)
    old_action.click().run()
    assert not app.exception
    assert library.load_profile(PROFILE.contract, PROFILE.key) == updated
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    if mode == "older":
        assert "chosen" in app.session_state
        assert app.session_state["chosen"].draft.profile.asset_tags == unfinished.draft.profile.asset_tags
    else:
        assert not any("changed again" in item.value for item in app.error)


@pytest.mark.parametrize("mode,label", CHOICES)
def test_changed_site_membership_keeps_both_copies_without_moving_content(
        monkeypatch, tmp_path, mode, label):
    app, unfinished, snapshot = setup(monkeypatch, tmp_path, mode)
    old_action = button(app, label)
    old_page = app.session_state[PREFIX + "_draft"]
    state = library.load_profile(PROFILE.contract, PROFILE.key)
    new_profile = replace(state.profile, facilities=(state.profile.facilities[0], Facility("east", "Synthetic East")))
    updated = library.save_profile(new_profile, expected_revision=state.revision,
                                   actor="Synthetic site manager", confirmed=True)
    old_action.click().run()
    assert not app.exception and button(app, label).disabled
    assert any("sites" in item.value.casefold() for item in app.error)
    assert active.load(TOKEN, PROFILE.contract, PROFILE.key, PERIOD) == unfinished
    assert library.load_snapshot(PROFILE.contract, PROFILE.key, PERIOD) == snapshot
    assert library.load_profile(PROFILE.contract, PROFILE.key) == updated
    assert app.session_state[PREFIX + "_draft"] == old_page
    assert "chosen" not in app.session_state
