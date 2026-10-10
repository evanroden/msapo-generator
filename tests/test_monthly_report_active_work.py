"""Recovery journal for in-progress monthly edits, not shared report history."""
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image

from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_model import ReportPeriod, ResolvedBlock, synthetic_draft, synthetic_profiles

DEVICE_A = 'a' * 32
DEVICE_B = 'b' * 32


def make_draft(period=ReportPeriod(2026, 9)):
    return synthetic_draft(synthetic_profiles()[0], period)


def test_active_recovery_roundtrip_without_any_completed_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    updated = replace(draft, prepared_by='Synthetic Editor', blocks=(
        ResolvedBlock('activity_summary', 'This month', text='Reviewed current synthetic pump work.'),))
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) is None
    stored = active.save(DEVICE_A, updated, expected_revision=0, base_snapshot_revision=0)
    assert stored.revision == 1
    loaded = active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period)
    assert loaded.draft == updated and loaded.revision == 1
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None
    assert library.list_profiles(draft.profile.contract) == ()
    assert DEVICE_A not in '\n'.join(str(p) for p in tmp_path.rglob('*'))


def test_active_work_is_isolated_by_browser_profile_and_reporting_month(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0)
    assert active.load(DEVICE_B, draft.profile.contract, draft.profile.key, draft.period) is None
    assert active.load(DEVICE_A, draft.profile.contract, 'other-profile', draft.period) is None
    assert active.load(DEVICE_A, 'Other contract', draft.profile.key, draft.period) is None
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, ReportPeriod(2026, 10)) is None
    assert not active.enabled('') and not active.enabled('invalid')


def test_identical_content_does_not_create_new_disk_revision(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    one = active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0)
    path = active._directory(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) / 'working.json'
    raw = path.read_bytes()
    again = active.save(DEVICE_A, draft, expected_revision=1, base_snapshot_revision=0)
    assert one.revision == again.revision == 1 and raw == path.read_bytes()
    updated = replace(draft, prepared_by='Corrected Editor')
    new = active.save(DEVICE_A, updated, expected_revision=1, base_snapshot_revision=0)
    assert new.revision == 2 and active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period).draft == updated


def test_browser_tab_stale_write_is_rejected_and_existing_work_kept(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    first = active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0)
    latest = replace(draft, prepared_by='Newer edit')
    active.save(DEVICE_A, latest, expected_revision=1, base_snapshot_revision=0)
    with pytest.raises(active.ActiveWorkConflict):
        active.save(DEVICE_A, replace(draft, prepared_by='Stale edit'), expected_revision=first.revision,
                    base_snapshot_revision=0)
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period).draft == latest


def _image():
    output = BytesIO()
    Image.new('RGB', (120, 90), 'orange').save(output, format='PNG')
    return output.getvalue()


def test_current_unsaved_picture_is_restored_with_content_integrity(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    raw = _image()
    reference = library.asset_reference(raw, 'png')
    draft = replace(draft, blocks=(ResolvedBlock('improvements', 'This month', asset_hashes=(reference,)),))
    active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0, assets={reference: raw})
    restored = active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period)
    assert dict(restored.assets) == {reference: raw}
    path = active._directory(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) / 'assets' / reference
    path.unlink()  # The immutable content-addressed copy is read-only.
    path.write_bytes(b'tampered')
    with pytest.raises(library.LibraryError, match='integrity'):
        active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period)


def test_discard_only_active_work_not_saved_history(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    saved = library.save_snapshot(draft, expected_revision=0, entered_editor='Synthetic Editor')
    one = active.save(DEVICE_A, replace(draft, prepared_by='Current browser edit'),
                      expected_revision=0, base_snapshot_revision=1)
    with pytest.raises(active.ActiveWorkConflict):
        active.discard(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period, expected_revision=0)
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period)
    active.discard(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period, expected_revision=one.revision)
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) is None
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved


def test_explicit_reset_recovers_a_corrupted_browser_journal(monkeypatch, tmp_path):
    monkeypatch.setenv('EPC_DATA_DIR', str(tmp_path))
    draft = make_draft()
    active.save(DEVICE_A, draft, expected_revision=0, base_snapshot_revision=0)
    path = active._directory(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) / 'working.json'
    path.write_text('{broken')
    with pytest.raises(library.LibraryError):
        active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period)
    active.discard(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period, expected_revision=0)
    assert active.load(DEVICE_A, draft.profile.contract, draft.profile.key, draft.period) is None
