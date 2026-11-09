"""An identical browser save cannot acknowledge a damaged retained picture.

Use only generated PNGs and disposable browser-journal directories; a repair
is driven by the caller's already digest-validated bytes, not guessed content.
"""
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_active_work import DEVICE_A, DEVICE_B, make_draft, _image


def staged(monkeypatch, tmp_path, second=False):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    first = _image()
    pictures = [first]
    if second:
        output = BytesIO()
        Image.new("RGB", (90, 80), "purple").save(output, format="PNG")
        pictures.append(output.getvalue())
    pending = {library.asset_reference(raw, "png"): raw for raw in pictures}
    draft = replace(make_draft(), blocks=(ResolvedBlock(
        "improvements", "This month", asset_hashes=tuple(pending)),))
    before = active.save(DEVICE_A, draft, expected_revision=0,
                         base_snapshot_revision=0, assets=pending)
    folder = active._directory(DEVICE_A, draft.profile.contract,
                               draft.profile.key, draft.period)
    return draft, before, pending, folder, folder / "working.json"


def alias(folder, name):
    return folder / "assets" / name


def save_again(draft, first, pending, *, revision=None, generation=None):
    return active.save(DEVICE_A, draft,
                       expected_revision=first.revision if revision is None else revision,
                       base_snapshot_revision=0, expected_generation=(
                           first.generation if generation is None else generation),
                       assets=pending)


def corrupt(path, data):
    path.unlink()
    path.write_bytes(data)


def test_normal_identical_save_keeps_bytes_revision_and_recovers(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    original = journal.read_bytes()
    again = save_again(draft, first, pending)
    assert again == first and journal.read_bytes() == original
    assert dict(active.load(DEVICE_A, draft.profile.contract,
                            draft.profile.key, draft.period).assets) == pending
    assert active.load(DEVICE_B, draft.profile.contract,
                       draft.profile.key, draft.period) is None


@pytest.mark.parametrize("damage", ("same-size", "shorter", "oversize"))
def test_same_save_repairs_only_verified_current_picture_without_new_history(
        monkeypatch, tmp_path, damage):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    previous = journal.read_bytes()
    picture = alias(folder, name)
    if damage == "same-size":
        changed = raw[:-1] + bytes((raw[-1] ^ 1,))
    elif damage == "shorter":
        changed = raw[:-1]
    else:
        changed = raw + b"damaged stored tail"
        # The production maximum is unchanged; this smaller fixture limit
        # exercises the actual overflow read without allocating 30 MiB.
        monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    corrupt(picture, changed)
    assert picture.read_bytes() != raw
    again = save_again(draft, first, pending)
    assert again == first
    assert journal.read_bytes() == previous and picture.read_bytes() == raw
    assert dict(active.load(DEVICE_A, draft.profile.contract,
                            draft.profile.key, draft.period).assets) == pending
    assert library.load_snapshot(draft.profile.contract,
                                 draft.profile.key, draft.period) is None


def test_two_pictures_only_restore_changed_alias(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path, second=True)
    (first_name, first_raw), (second_name, second_raw) = pending.items()
    healthy = alias(folder, first_name)
    damaged = alias(folder, second_name)
    untouched_before = healthy.stat()
    saved_bytes = journal.read_bytes()
    corrupt(damaged, second_raw[:-1])
    again = save_again(draft, first, pending)
    assert again == first and journal.read_bytes() == saved_bytes
    assert healthy.read_bytes() == first_raw
    assert healthy.stat().st_ino == untouched_before.st_ino
    assert damaged.read_bytes() == second_raw
    assert dict(active.load(DEVICE_A, draft.profile.contract,
                            draft.profile.key, draft.period).assets) == pending


def test_symlink_alias_is_refused_without_reading_external_bytes(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    path = alias(folder, name)
    foreign = tmp_path / "unrelated-private-file"
    foreign.write_bytes(b"synthetic different private content")
    path.unlink()
    path.symlink_to(foreign)
    before = journal.read_bytes()
    with pytest.raises(library.LibraryError, match="cannot be verified"):
        save_again(draft, first, pending)
    assert path.is_symlink() and foreign.read_bytes() == b"synthetic different private content"
    assert journal.read_bytes() == before


def test_read_error_is_recoverable_and_preserves_existing_journal(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    path = alias(folder, name)
    original_open = Path.open
    before = journal.read_bytes()

    def denied_open(self, *args, **kwargs):
        if self == path:
            raise OSError("synthetic transient reader failure")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)
    with pytest.raises(library.LibraryError, match="could not be verified"):
        save_again(draft, first, pending)
    assert journal.read_bytes() == before
    monkeypatch.setattr(Path, "open", original_open)
    assert save_again(draft, first, pending) == first


def test_failed_asset_repair_does_not_advance_journal_and_can_retry(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    path = alias(folder, name)
    corrupt(path, raw[:-1])
    before = journal.read_bytes()
    real_write = library._atomic_write

    def fail_alias(target, data):
        if target == path:
            raise OSError("synthetic atomic picture write failure")
        return real_write(target, data)

    monkeypatch.setattr(library, "_atomic_write", fail_alias)
    with pytest.raises(library.LibraryError, match="could not be restored"):
        save_again(draft, first, pending)
    assert journal.read_bytes() == before and path.read_bytes() != raw
    monkeypatch.setattr(library, "_atomic_write", real_write)
    assert save_again(draft, first, pending) == first
    assert journal.read_bytes() == before and path.read_bytes() == raw


def test_stale_writer_cannot_repair_picture_or_replace_newer_work(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    path = alias(folder, name)
    corrupt(path, raw[:-1])
    before = journal.read_bytes()
    with pytest.raises(active.ActiveWorkConflict):
        save_again(draft, first, pending, revision=0)
    assert journal.read_bytes() == before and path.read_bytes() != raw
    assert save_again(draft, first, pending) == first
    assert path.read_bytes() == raw


def test_missing_picture_retains_existing_recovery_revision_behavior(monkeypatch, tmp_path):
    draft, first, pending, folder, journal = staged(monkeypatch, tmp_path)
    (name, raw), = pending.items()
    path = alias(folder, name)
    path.unlink()
    next_copy = save_again(draft, first, pending)
    assert next_copy.revision == first.revision + 1
    assert path.read_bytes() == raw
    assert dict(active.load(DEVICE_A, draft.profile.contract,
                            draft.profile.key, draft.period).assets) == pending
