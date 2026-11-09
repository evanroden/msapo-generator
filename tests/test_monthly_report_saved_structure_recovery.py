"""Non-object saved drafts/blocks fail visibly without replacing stored work."""

from dataclasses import asdict, replace
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles


PERIOD = ReportPeriod(2026, 9)
TOKEN = "a" * 32
NON_OBJECTS = [None, [], "damaged", 17, True]


@pytest.fixture
def draft(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_draft(synthetic_profiles()[0], PERIOD)


def stored_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("value", NON_OBJECTS, ids=["null", "array", "string", "number", "boolean"])
@pytest.mark.parametrize("loader,message", [
    (library.block_from_dict, "Invalid saved report block."),
    (library.draft_from_dict, "Invalid report snapshot."),
])
def test_non_object_values_use_existing_recovery_error(value, loader, message):
    with pytest.raises(library.LibraryError, match=message):
        loader(value)


def test_valid_draft_and_block_round_trips_keep_fingerprints_and_reviews(draft):
    block = ResolvedBlock("activity_summary", "This month", text="Reviewed synthetic work.")
    block = replace(block, reviewed_fingerprint=block.fingerprint)
    draft = replace(draft, blocks=(block,))
    restored = library.draft_from_dict(json.loads(json.dumps(asdict(draft))))
    assert restored == draft and restored.fingerprint == draft.fingerprint
    assert library.block_from_dict(json.loads(json.dumps(asdict(block)))) == block


@pytest.mark.parametrize("loader,message", [
    (library.block_from_dict, "Invalid saved report block."),
    (library.draft_from_dict, "Invalid report snapshot."),
])
def test_missing_required_fields_keep_existing_recovery_error(loader, message):
    with pytest.raises(library.LibraryError, match=message):
        loader({})


@pytest.mark.parametrize("in_draft", [False, True])
def test_unrelated_attribute_errors_are_not_hidden(draft, monkeypatch, in_draft):
    from app import monthly_report_asset_review
    block = ResolvedBlock("activity_summary", "This month", text="Synthetic legacy approval.")
    block = replace(block, client_reviewed_fingerprint=block.fingerprint)

    def broken_normalizer(value):
        raise AttributeError("Synthetic unrelated implementation error")

    monkeypatch.setattr(monthly_report_asset_review, "normalize_asset_reviews", broken_normalizer)
    with pytest.raises(AttributeError, match="Synthetic unrelated implementation error"):
        if in_draft:
            library.draft_from_dict(asdict(replace(draft, blocks=(block,))))
        else:
            library.block_from_dict(asdict(block))


@pytest.mark.parametrize("kind", ["shared-draft", "shared-block", "journal-draft", "journal-block", "library-block"])
def test_non_object_saved_records_refuse_reads_without_mutation(draft, tmp_path, kind):
    library.save_snapshot(draft, expected_revision=0)
    active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=1)
    profile = draft.profile
    if kind.startswith("shared"):
        path = library._profile_path(profile.contract, profile.key, snapshots=True) / (PERIOD.key + ".json")
        read = lambda: library.load_snapshot(profile.contract, profile.key, PERIOD)
    elif kind.startswith("journal"):
        path = active._directory(TOKEN, profile.contract, profile.key, PERIOD) / "working.json"
        read = lambda: active.load(TOKEN, profile.contract, profile.key, PERIOD)
    else:
        library.save_profile(profile, expected_revision=0, actor="Synthetic editor", confirmed=True)
        library.replace_block(profile.contract, profile.key, "activity_summary",
                              ResolvedBlock("activity_summary", "Library", text="Synthetic default."),
                              expected_revision=1, actor="Synthetic editor", confirmed=True, label="Synthetic")
        path = library._profile_path(profile.contract, profile.key) / "manifest.json"
        read = lambda: library.load_profile(profile.contract, profile.key)
    value = json.loads(path.read_bytes())
    if kind == "library-block":
        value["versions"][0]["block"] = None
    elif kind.endswith("draft"):
        value["draft"] = None
    else:
        value["draft"]["blocks"] = [None]
    path.write_bytes(library._json(value))
    before = stored_bytes(tmp_path)
    with pytest.raises(library.LibraryError):
        read()
    assert stored_bytes(tmp_path) == before


HISTORY_APP = '''
import streamlit as st
from app.monthly_report_history_ui import render_snapshot_history
render_snapshot_history(st.session_state['draft'], 'structure_history', {}, st.session_state['snapshot'])
st.text_input('Continue editing current draft', value='Synthetic current work', key='current_note')
'''


@pytest.mark.parametrize("value", [None, []], ids=["null-block", "array-block"])
def test_selecting_damaged_history_keeps_current_edit_and_all_saved_bytes(draft, tmp_path, value):
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor="Synthetic editor")
    root = library._profile_path(draft.profile.contract, draft.profile.key, snapshots=True)
    history = root / "history" / (PERIOD.key + "-00000001.json")
    valid_history = history.read_bytes()
    damaged = json.loads(valid_history)
    damaged["draft"]["blocks"] = [value]
    history.write_bytes(library._json(damaged))
    before = stored_bytes(tmp_path)
    app = AppTest.from_string(HISTORY_APP, default_timeout=20)
    app.session_state["draft"] = draft
    app.session_state["snapshot"] = saved
    app.run()
    assert not app.exception and not app.error
    app.text_input(key="current_note").set_value("Keep this unpublished note").run()
    app.selectbox[0].set_value(1).run()
    assert not app.exception
    assert [error.value for error in app.error] == [
        "Shared report history could not be read: Invalid report snapshot."]
    assert app.text_input(key="current_note").value == "Keep this unpublished note"
    app.text_input(key="current_note").set_value("Editing continues after failed inspection").run()
    assert not app.exception
    assert app.text_input(key="current_note").value == "Editing continues after failed inspection"
    assert stored_bytes(tmp_path) == before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, PERIOD) == saved

    # Restore only the disposable test fixture; normal inspection never does this.
    history.write_bytes(valid_history)
    restored = stored_bytes(tmp_path)
    app.run()
    assert not app.exception and not app.error
    assert app.text_input(key="current_note").value == "Editing continues after failed inspection"
    assert stored_bytes(tmp_path) == restored


@pytest.mark.parametrize("value", NON_OBJECTS, ids=["null", "array", "string", "number", "boolean"])
@pytest.mark.parametrize("expected", ["current", "fallback"])
def test_malformed_journal_cannot_claim_or_overwrite_a_save(draft, tmp_path, value, expected):
    saved = active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=0)
    path = active._directory(TOKEN, draft.profile.contract, draft.profile.key, PERIOD) / "working.json"
    damaged = json.loads(path.read_bytes())
    damaged["draft"] = value
    path.write_bytes(library._json(damaged))
    before = stored_bytes(tmp_path)
    with pytest.raises(library.LibraryError, match="unfinished browser journal could not be read safely"):
        active.save(TOKEN, draft, expected_revision=saved.revision if expected == "current" else 0,
                    expected_generation=saved.generation if expected == "current" else "",
                    base_snapshot_revision=0)
    assert stored_bytes(tmp_path) == before


def test_tombstone_without_draft_and_legacy_valid_journal_still_save(draft):
    first = active.save(TOKEN, draft, expected_revision=0, base_snapshot_revision=0)
    path = active._directory(TOKEN, draft.profile.contract, draft.profile.key, PERIOD) / "working.json"
    legacy = json.loads(path.read_bytes())
    legacy.pop("generation")
    path.write_bytes(library._json(legacy))
    loaded = active.load(TOKEN, draft.profile.contract, draft.profile.key, PERIOD)
    assert loaded.draft == draft and loaded.generation == ""
    same = active.save(TOKEN, draft, expected_revision=first.revision,
                       expected_generation="", base_snapshot_revision=0)
    assert same.revision == first.revision
    generation = active.discard(TOKEN, draft.profile.contract, draft.profile.key, PERIOD,
                                expected_revision=same.revision, expected_generation="")
    assert "draft" not in json.loads(path.read_bytes())
    renewed = active.save(TOKEN, draft, expected_revision=0, expected_generation=generation,
                          base_snapshot_revision=0)
    assert renewed.generation == generation
    assert active.load(TOKEN, draft.profile.contract, draft.profile.key, PERIOD).draft == draft


@pytest.mark.parametrize("value", [None, []], ids=["null-draft", "array-draft"])
def test_guided_recovery_and_retry_preserve_malformed_journal_and_current_text(monkeypatch, tmp_path, value):
    from app import web_ui
    from app.contracts import RRH_CONTRACT
    from test_monthly_report_ui import monthly, choose_report
    monkeypatch.setattr(web_ui, "device_token", lambda cookies: TOKEN)
    monthly(monkeypatch, tmp_path)
    original = active.load(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD)
    assert original is not None
    path = active._directory(TOKEN, RRH_CONTRACT, "synthetic-guided", PERIOD) / "working.json"
    damaged = json.loads(path.read_bytes())
    damaged["draft"] = value
    path.write_bytes(library._json(damaged))
    before = path.read_bytes()

    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "run_web.py", default_timeout=30).run()
    app.segmented_control[0].set_value("Monthly report").run()
    choose_report(app, synthetic_profiles()[0].facilities[0].title)
    assert not app.exception
    assert any("Unfinished browser work could not be restored" in item.value for item in app.warning)
    assert any("Automatic recovery could not keep these edits" in item.value for item in app.error)
    editor = next(item for item in app.text_area if item.label == "Activity summary")
    editor.set_value("Synthetic text stays visible despite the damaged journal").run()
    assert not app.exception
    assert next(item for item in app.text_area if item.label == "Activity summary").value == (
        "Synthetic text stays visible despite the damaged journal")
    next(button for button in app.button if button.label == "Retry browser save").click().run()
    assert not app.exception
    assert any("Automatic recovery could not keep these edits" in item.value for item in app.error)
    assert not any("Recovered your unfinished changes" in item.value for item in app.success)
    assert path.read_bytes() == before
    assert library.load_snapshot(RRH_CONTRACT, "synthetic-guided", PERIOD) is None
