"""No stale browser work after discard; failed storage never interrupts the editor."""
from dataclasses import replace

import pytest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft, synthetic_profiles
from test_monthly_report_ui import monthly

BROWSER_A = "a" * 32
BROWSER_B = "b" * 32


def draft_for(period=ReportPeriod(2026, 9)):
    return synthetic_draft(synthetic_profiles()[0], period)


def test_discard_recreate_rejects_stale_tab_and_preserves_history(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    initial = draft_for()
    history = library.save_snapshot(initial, expected_revision=0, entered_editor="Synthetic Editor")
    first = active.save(BROWSER_A, replace(initial, prepared_by="Old tab"),
                        expected_revision=0, expected_generation="", base_snapshot_revision=1)
    fresh_identity = active.discard(BROWSER_A, initial.profile.contract, initial.profile.key, initial.period,
                                    expected_revision=first.revision, expected_generation=first.generation)
    assert active.load(BROWSER_A, initial.profile.contract, initial.profile.key, initial.period) is None
    assert fresh_identity != first.generation
    assert active.current_generation(BROWSER_A, initial.profile.contract, initial.profile.key,
                                     initial.period) == fresh_identity
    # An old tab must fail even before the replacement has made its first edit.
    with pytest.raises(active.ActiveWorkConflict):
        active.save(BROWSER_A, replace(initial, prepared_by="Delayed old tab"),
                    expected_revision=first.revision, expected_generation=first.generation,
                    base_snapshot_revision=1)
    newest = replace(initial, prepared_by="New working copy")
    second = active.save(BROWSER_A, newest, expected_revision=0,
                         expected_generation=fresh_identity, base_snapshot_revision=1)
    assert second.revision > first.revision and second.generation == fresh_identity
    with pytest.raises(active.ActiveWorkConflict):
        active.save(BROWSER_A, replace(initial, prepared_by="Delayed old tab"),
                    expected_revision=first.revision, expected_generation=first.generation,
                    base_snapshot_revision=1)
    assert active.load(BROWSER_A, initial.profile.contract, initial.profile.key, initial.period).draft == newest
    assert library.load_snapshot(initial.profile.contract, initial.profile.key, initial.period) == history


def test_generation_is_isolated_by_browser_contract_site_and_month(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = draft_for()
    first = active.save(BROWSER_A, draft, expected_revision=0, base_snapshot_revision=0)
    next_generation = active.discard(BROWSER_A, draft.profile.contract, draft.profile.key, draft.period,
                                     expected_revision=first.revision, expected_generation=first.generation)
    assert next_generation != first.generation
    for browser, contract, key, month in (
        (BROWSER_B, draft.profile.contract, draft.profile.key, draft.period),
        (BROWSER_A, "Synthetic other contract", draft.profile.key, draft.period),
        (BROWSER_A, draft.profile.contract, "other-site-profile", draft.period),
        (BROWSER_A, draft.profile.contract, draft.profile.key, ReportPeriod(2026, 10)),
    ):
        assert active.current_generation(browser, contract, key, month) == ""
        assert active.load(browser, contract, key, month) is None


def test_legacy_journal_upgrades_on_next_real_edit(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = draft_for()
    one = active.save(BROWSER_A, draft, expected_revision=0, base_snapshot_revision=0)
    path = active._directory(BROWSER_A, draft.profile.contract, draft.profile.key, draft.period) / "working.json"
    data = library._read(path)
    data.pop("generation")
    library._atomic_write(path, library._json(data))
    loaded = active.load(BROWSER_A, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.generation == "" and loaded.revision == one.revision
    updated = active.save(BROWSER_A, replace(draft, prepared_by="Edited after upgrade"),
                          expected_revision=loaded.revision, expected_generation="",
                          base_snapshot_revision=0)
    assert updated.generation and updated.revision == loaded.revision + 1


def test_real_disk_failure_keeps_last_valid_journal_and_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    draft = draft_for()
    first = active.save(BROWSER_A, draft, expected_revision=0, expected_generation="",
                        base_snapshot_revision=0)
    write = library._atomic_write
    def fail_manifest(path, raw):
        if path.name == "working.json" and "active_work" in path.parts:
            raise OSError("private/test/storage/location")
        return write(path, raw)
    monkeypatch.setattr(library, "_atomic_write", fail_manifest)
    changed = replace(draft, prepared_by="Uncommitted current input")
    with pytest.raises(OSError):
        active.save(BROWSER_A, changed, expected_revision=first.revision,
                    expected_generation=first.generation, base_snapshot_revision=0)
    assert active.load(BROWSER_A, draft.profile.contract, draft.profile.key, draft.period).draft == draft
    monkeypatch.setattr(library, "_atomic_write", write)
    later = active.save(BROWSER_A, changed, expected_revision=first.revision,
                        expected_generation=first.generation, base_snapshot_revision=0)
    assert later.revision == first.revision + 1
    assert active.load(BROWSER_A, draft.profile.contract, draft.profile.key, draft.period).draft == changed


def test_oserror_at_storage_boundary_keeps_report_editor_running(monkeypatch, tmp_path):
    from app import monthly_report_guided as guided
    monkeypatch.setattr(active, "enabled", lambda _value: True)
    app = monthly(monkeypatch, tmp_path)
    write = library._atomic_write
    def fail_manifest(path, raw):
        if path.name == "working.json" and "active_work" in path.parts:
            raise OSError("/private/source/path/should-not-be-shown")
        return write(path, raw)
    monkeypatch.setattr(library, "_atomic_write", fail_manifest)
    next(w for w in app.text_area if w.label == "Activity summary").set_value(
        "Keep the synthetic repair note after a disk failure.").run()
    assert not app.exception
    assert any("could not keep these edits" in error.value.lower() for error in app.error)
    assert not any("/private/" in error.value for error in app.error)
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Keep the synthetic repair note after a disk failure.")
    assert any(x.value == "Review and download" for x in app.subheader)
    monkeypatch.setattr(library, "_atomic_write", write)
    app.run()
    assert not app.exception
    assert next(w for w in app.text_area if w.label == "Activity summary").value == (
        "Keep the synthetic repair note after a disk failure.")
    assert not any("could not keep these edits" in error.value.lower() for error in app.error)
