"""Committed browser-save replay never reads beyond the existing picture budget.

Only generated PNG fixtures, disposable browser journals and synthetic profiles.
This is not a new replay authority: parent revision/generation and operation ID
must still match the exact atomic save, even when a stored alias is damaged.
"""
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

from app import monthly_report_active_work as active, monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_active_work import DEVICE_A, DEVICE_B, make_draft, _image


OPERATION = "c" * 32


def stage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = _image()
    name = library.asset_reference(original, "png")
    draft = replace(make_draft(), blocks=(
        ResolvedBlock("improvements", "This month", asset_hashes=(name,)),))
    saved = active.save(
        DEVICE_A, draft, expected_revision=0, expected_generation="",
        base_snapshot_revision=0, operation_id=OPERATION, assets={name: original},
    )
    folder = active._directory(DEVICE_A, draft.profile.contract,
                               draft.profile.key, draft.period)
    return draft, saved, original, name, folder / "assets" / name, folder / "working.json"


def replay(draft, raw, name, *, revision=0, operation=OPERATION):
    return active.save(
        DEVICE_A, draft, expected_revision=revision, expected_generation="",
        base_snapshot_revision=0, operation_id=operation, assets={name: raw},
    )


def test_normal_receipt_replay_preserves_revision_generation_and_all_snapshots(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    again = replay(draft, raw, name)
    assert again == saved and journal.read_bytes() == before
    assert picture.read_bytes() == raw
    assert active.load(DEVICE_B, draft.profile.contract, draft.profile.key, draft.period) is None
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_receipt_replay_reads_at_most_maximum_plus_one_and_closes(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    original_open = Path.open
    readings, streams = [], []

    class Observed(BytesIO):
        def read(self, size=-1):
            readings.append(size)
            assert size == len(raw) + 1, "Receipt replay must not read unbounded bytes"
            return super().read(size)

    def observed_open(self, *args, **kwargs):
        if self == picture and (args and args[0] == "rb" or kwargs.get("mode") == "rb"):
            stream = Observed(raw)
            streams.append(stream)
            return stream
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    assert replay(draft, raw, name) == saved
    assert readings == [len(raw) + 1]
    assert len(streams) == 1 and streams[0].closed
    assert journal.read_bytes() == before


def test_post_stat_growth_never_reads_past_cap_or_commits_a_receipt(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    original_open = Path.open
    reads = []
    changed = []

    class PostGrowth(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == len(raw) + 1, "A post-stat growth must be read only up to the limit + 1"
            return super().read(size)

    def growing_open(self, *args, **kwargs):
        if self == picture and (args and args[0] == "rb" or kwargs.get("mode") == "rb"):
            if not changed:
                changed.append(True)
                picture.unlink()
                picture.write_bytes(raw + b"synthetic grown tail")
            return PostGrowth(raw + b"synthetic grown tail")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", growing_open)
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert changed and reads == [len(raw) + 1]
    assert journal.read_bytes() == before
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_oversized_opened_stream_is_rejected_before_unbounded_copy(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    original_open = Path.open
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    reads = []

    class Substitute(BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == len(raw) + 1
            return super().read(size)

    def swapped_open(self, *args, **kwargs):
        if self == picture and (args and args[0] == "rb" or kwargs.get("mode") == "rb"):
            return Substitute(raw + b"malformed external data")
        return original_open(self, *args, **kwargs)

    previous = journal.read_bytes()
    monkeypatch.setattr(Path, "open", swapped_open)
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert reads == [len(raw) + 1] and journal.read_bytes() == previous


@pytest.mark.parametrize("corruption", ("same-size", "shorter", "oversized"))
def test_replay_refuses_corrupted_alias_without_damaging_saved_history(
        monkeypatch, tmp_path, corruption):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    original = journal.read_bytes()
    picture.unlink()
    if corruption == "same-size":
        picture.write_bytes(raw[:-1] + bytes((raw[-1] ^ 1,)))
    elif corruption == "shorter":
        picture.write_bytes(raw[:-1])
    else:
        picture.write_bytes(raw + b"too many bytes")
        monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert journal.read_bytes() == original
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) is None


def test_private_alias_symlink_cannot_satisfy_committed_receipt(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    unrelated = tmp_path / "unrelated-synthetic-image"
    unrelated.write_bytes(raw)
    picture.unlink()
    picture.symlink_to(unrelated)
    before = journal.read_bytes()
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert picture.is_symlink() and unrelated.read_bytes() == raw
    assert journal.read_bytes() == before


def test_missing_alias_remains_a_recoverable_refusal(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    picture.unlink()
    before = journal.read_bytes()
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert journal.read_bytes() == before


def test_reader_error_is_recoverable_without_mutating_any_receipt(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    original_open = Path.open
    before = journal.read_bytes()

    def denied(self, *args, **kwargs):
        if self == picture and (args and args[0] == "rb" or kwargs.get("mode") == "rb"):
            raise OSError("synthetic private-alias read refusal")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with pytest.raises(library.LibraryError, match="integrity"):
        replay(draft, raw, name)
    assert journal.read_bytes() == before


def test_stale_replay_is_refused_before_touching_saved_picture(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    original_open = Path.open

    def no_picture_read(self, *args, **kwargs):
        if self == picture:
            raise AssertionError("Stale receipt must not read picture contents")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_picture_read)
    with pytest.raises(active.ActiveWorkConflict):
        replay(draft, raw, name, revision=999)
    assert journal.read_bytes() == before


def test_other_operation_id_remains_unapproved_even_if_content_matches(monkeypatch, tmp_path):
    draft, saved, raw, name, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    with pytest.raises(active.ActiveWorkConflict):
        replay(draft, raw, name, operation="d" * 32)
    assert journal.read_bytes() == before
