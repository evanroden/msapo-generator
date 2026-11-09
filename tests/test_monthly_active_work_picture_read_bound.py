"""An active browser picture is read within its existing size budget.

All report data and picture bytes are synthetic. The shared report library
must remain untouched by a failed private-browser restoration.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from app import monthly_report_active_work as active
from app import monthly_report_library as library
from app.monthly_report_model import ResolvedBlock
from test_monthly_report_active_work import DEVICE_A, DEVICE_B, make_draft, _image


def stage(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    original = _image()
    name = library.asset_reference(original, "png")
    draft = replace(make_draft(), blocks=(
        ResolvedBlock("improvements", "This month", asset_hashes=(name,)),))
    saved = active.save(DEVICE_A, draft, expected_revision=0,
                        base_snapshot_revision=0, assets={name: original})
    folder = active._directory(DEVICE_A, draft.profile.contract,
                               draft.profile.key, draft.period)
    return draft, saved, original, folder / "assets" / name, folder / "working.json"


def test_valid_active_picture_restores_and_other_browser_stays_isolated(monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    assert dict(active.load(DEVICE_A, draft.profile.contract,
                            draft.profile.key, draft.period).assets) == {
                                library.asset_reference(raw, "png"): raw}
    assert active.load(DEVICE_B, draft.profile.contract,
                       draft.profile.key, draft.period) is None
    assert active.load(DEVICE_A, "Another synthetic contract",
                       draft.profile.key, draft.period) is None
    assert saved.revision == 1 and picture.read_bytes() == raw
    assert library.load_snapshot(draft.profile.contract,
                                 draft.profile.key, draft.period) is None


def test_restoration_reads_only_maximum_plus_one_and_closes_stream(monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    opened, read_sizes = [], []
    original_open = Path.open

    class ObservedStream:
        closed = False

        def __enter__(self):
            return self

        def read(self, size=-1):
            read_sizes.append(size)
            return raw

        def __exit__(self, *args):
            self.closed = True

    def observed_open(self, *args, **kwargs):
        if self == picture:
            stream = ObservedStream()
            opened.append(stream)
            return stream
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    loaded = active.load(DEVICE_A, draft.profile.contract,
                         draft.profile.key, draft.period)
    assert loaded.draft == draft and dict(loaded.assets) == {
        library.asset_reference(raw, "png"): raw}
    assert read_sizes == [len(raw) + 1]
    assert len(opened) == 1 and opened[0].closed
    assert saved.revision == loaded.revision


def test_post_stat_growth_is_rejected_before_hashing_without_changing_history(
        monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    actual_stat = Path.stat
    original_reference = library.asset_reference
    changed = []

    def growing_stat(self, *args, **kwargs):
        info = actual_stat(self, *args, **kwargs)
        if self == picture and not changed:
            changed.append(True)
            picture.unlink()
            picture.write_bytes(raw + b"one more byte")
        return info

    def safe_hash(data, suffix):
        assert len(data) <= library.MAX_ASSET_BYTES, (
            "Oversized browser pictures must not reach SHA computation.")
        return original_reference(data, suffix)

    monkeypatch.setattr(Path, "stat", growing_stat)
    monkeypatch.setattr(library, "asset_reference", safe_hash)
    with pytest.raises(library.LibraryError, match="exceeds the file limit"):
        active.load(DEVICE_A, draft.profile.contract,
                    draft.profile.key, draft.period)
    assert changed and journal.read_bytes() == before
    assert library.load_snapshot(draft.profile.contract,
                                 draft.profile.key, draft.period) is None


def test_opened_stream_over_limit_is_refused_before_digest_with_stream_closed(
        monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    original_open = Path.open
    streams, sizes = [], []

    class GrownStream:
        closed = False

        def __enter__(self):
            return self

        def read(self, size=-1):
            sizes.append(size)
            assert size == len(raw) + 1
            return raw + b"!"

        def __exit__(self, *args):
            self.closed = True

    def swapped_open(self, *args, **kwargs):
        if self == picture:
            item = GrownStream()
            streams.append(item)
            return item
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", swapped_open)
    with pytest.raises(library.LibraryError, match="exceeds the file limit"):
        active.load(DEVICE_A, draft.profile.contract,
                    draft.profile.key, draft.period)
    assert sizes == [len(raw) + 1] and streams[0].closed
    assert journal.read_bytes() == before
    # Path.read_bytes() opens through Path.open, which is still swapped for the
    # picture here; read the untouched file through the original opener.
    with original_open(picture, "rb") as handle:
        assert handle.read() == raw


def test_unchanged_oversized_file_still_refused_by_early_limit(monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    picture.unlink()
    picture.write_bytes(raw + b"too large")
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(raw))
    with pytest.raises(library.LibraryError, match="exceeds the file limit"):
        active.load(DEVICE_A, draft.profile.contract,
                    draft.profile.key, draft.period)


def test_digest_corruption_and_missing_picture_preserve_existing_errors(monkeypatch, tmp_path):
    draft, saved, raw, picture, journal = stage(monkeypatch, tmp_path)
    before = journal.read_bytes()
    picture.unlink()
    picture.write_bytes(b"not-the-original-image")
    with pytest.raises(library.LibraryError, match="integrity"):
        active.load(DEVICE_A, draft.profile.contract,
                    draft.profile.key, draft.period)
    picture.unlink()
    with pytest.raises(library.LibraryError, match="could not be restored"):
        active.load(DEVICE_A, draft.profile.contract,
                    draft.profile.key, draft.period)
    assert journal.read_bytes() == before
    assert library.load_snapshot(draft.profile.contract,
                                 draft.profile.key, draft.period) is None
