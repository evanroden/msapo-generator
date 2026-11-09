"""Synthetic saved-library assets stay bounded even after their stat precheck."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import monthly_report_library as library
from app.monthly_report_model import ReportPeriod, synthetic_draft
from test_monthly_report_library import png, profile, replace_chart


@pytest.fixture
def saved_asset(profile):
    state = replace_chart(profile, 1, "red")
    reference, raw = png("red")
    path = library._profile_path(profile.contract, profile.key) / "assets" / reference
    return SimpleNamespace(profile=profile, state=state, reference=reference, raw=raw, path=path)


def _read(saved):
    return library.read_asset(saved.profile.contract, saved.profile.key, saved.reference)


def _metadata():
    return {str(p): p.read_bytes() for p in library._root().rglob("*.json")}


class _MeteredReader:
    def __init__(self, stream, trace, cap, error=None):
        self.stream, self.trace, self.cap, self.error = stream, trace, cap, error

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def read(self, size=-1):
        self.trace.reads.append(size)
        if self.error:
            raise self.error
        assert 0 <= size <= self.cap, "Library asset attempted an unbounded or oversized read"
        raw = self.stream.read(size)
        self.trace.returned += len(raw)
        assert self.trace.returned <= self.cap, "Library asset consumed more than its read budget"
        return raw


def _intercept(monkeypatch, saved, *, replacement=None, grow=False, error=None, stage=None):
    original = Path.open
    trace = SimpleNamespace(opens=0, reads=[], returned=0, stream=None)

    def opened(path, mode="r", *args, **kwargs):
        if path == saved.path and mode == "rb":
            trace.opens += 1
            if stage == "open":
                raise error
            if grow:
                # A real synthetic file grows after read_asset's stat precheck.
                with original(path, "ab") as writer:
                    writer.write(b"!")
            trace.stream = (BytesIO(replacement) if replacement is not None
                            else original(path, mode, *args, **kwargs))
            return _MeteredReader(trace.stream, trace, library.MAX_ASSET_BYTES + 1,
                                  error if stage == "read" else None)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    return trace


def _guard_asset_hash(monkeypatch, saved):
    original = library.hashlib.sha256

    def digest(raw=b"", *args, **kwargs):
        if raw.startswith(saved.raw) and len(raw) > library.MAX_ASSET_BYTES:
            pytest.fail("Oversized library asset reached hashing")
        return original(raw, *args, **kwargs)

    monkeypatch.setattr(library.hashlib, "sha256", digest)


def test_exact_png_limit_returns_original_bytes_and_closes_reader(saved_asset, monkeypatch):
    saved = saved_asset
    before = _metadata()
    with monkeypatch.context() as scoped:
        scoped.setattr(library, "MAX_ASSET_BYTES", len(saved.raw))
        trace = _intercept(scoped, saved)
        actual = _read(saved)
    assert type(actual) is bytes and actual == saved.raw
    assert trace.opens == 1 and trace.returned == len(saved.raw)
    assert trace.stream.closed
    assert _metadata() == before and saved.path.read_bytes() == saved.raw


def test_oversized_stat_rejects_before_open_or_hash(saved_asset, monkeypatch):
    saved = saved_asset
    with monkeypatch.context() as scoped:
        scoped.setattr(library, "MAX_ASSET_BYTES", len(saved.raw) - 1)
        trace = _intercept(scoped, saved)
        _guard_asset_hash(scoped, saved)
        with pytest.raises(library.LibraryError, match="size limit"):
            _read(saved)
    assert trace.opens == 0 and trace.reads == []
    assert saved.path.read_bytes() == saved.raw


def test_growth_after_stat_preserves_saved_history_and_restore_can_retry(saved_asset, monkeypatch):
    saved = saved_asset
    draft = synthetic_draft(saved.profile, ReportPeriod(2026, 9))
    draft = replace(draft, blocks=(*draft.blocks, saved.state.block("org_chart")))
    snapshot = library.save_snapshot(draft, expected_revision=0)
    replace_chart(saved.profile, 2, "blue")
    saved.path.unlink()  # Simulate replacement of the immutable synthetic asset link.
    saved.path.write_bytes(saved.raw)
    before = _metadata()
    restore = lambda: library.restore_block(
        saved.profile.contract, saved.profile.key, saved.state.versions[-1].id,
        expected_revision=3, actor="Synthetic Reviewer", confirmed=True)
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(library, "MAX_ASSET_BYTES", len(saved.raw))
            trace = _intercept(scoped, saved, grow=True)
            _guard_asset_hash(scoped, saved)
            with pytest.raises(library.LibraryError, match="size limit"):
                restore()
        assert trace.returned == len(saved.raw) + 1 and trace.stream.closed
        assert _metadata() == before
        assert saved.path.read_bytes() == saved.raw + b"!"
    finally:
        saved.path.write_bytes(saved.raw)  # Repair only this synthetic fixture for the retry.
    restored = restore()
    assert restored.revision == 4 and restored.block("org_chart") == saved.state.block("org_chart")
    assert _read(saved) == saved.raw
    assert library.load_snapshot_version(saved.profile.contract, saved.profile.key, draft.period, 1) == snapshot


def test_default_30_mib_limit_caps_substituted_stream_before_hashing(saved_asset, monkeypatch):
    saved = saved_asset
    cap = library.MAX_ASSET_BYTES
    assert cap == 30 * 1024 * 1024
    replacement = saved.raw + b"x" * (cap + 4096 - len(saved.raw))
    before = _metadata()
    with monkeypatch.context() as scoped:
        trace = _intercept(scoped, saved, replacement=replacement)
        _guard_asset_hash(scoped, saved)
        with pytest.raises(library.LibraryError, match="size limit"):
            _read(saved)
    assert trace.returned == cap + 1 and trace.stream.closed
    assert _metadata() == before and saved.path.read_bytes() == saved.raw
    assert _read(saved) == saved.raw


def test_same_size_substitution_still_fails_integrity_without_metadata_changes(saved_asset):
    saved = saved_asset
    changed = bytes([saved.raw[0] ^ 1]) + saved.raw[1:]
    before = _metadata()
    saved.path.unlink()  # Leave the original immutable object untouched.
    saved.path.write_bytes(changed)
    try:
        with pytest.raises(library.LibraryError, match="integrity"):
            _read(saved)
        assert saved.path.read_bytes() == changed and _metadata() == before
    finally:
        saved.path.write_bytes(saved.raw)
    assert _read(saved) == saved.raw


def test_invalid_reference_rejects_before_resolving_storage(saved_asset, monkeypatch):
    monkeypatch.setattr(library, "_profile_path", lambda *a, **k: pytest.fail("Invalid reference reached storage"))
    with pytest.raises(library.LibraryError, match="Invalid asset reference"):
        library.read_asset(saved_asset.profile.contract, saved_asset.profile.key, "../manifest.json")


@pytest.mark.parametrize("foreign", ["contract", "profile"])
def test_asset_reference_cannot_cross_profile_or_contract(saved_asset, foreign):
    saved = saved_asset
    contract = saved.profile.contract if foreign == "profile" else "Other Synthetic Contract"
    key = saved.profile.key if foreign == "contract" else "other-profile"
    with pytest.raises(library.LibraryError, match="unavailable"):
        library.read_asset(contract, key, saved.reference)
    assert _read(saved) == saved.raw


@pytest.mark.parametrize("stage,error", [
    ("stat", FileNotFoundError("Synthetic asset vanished")),
    ("open", PermissionError("Synthetic permission error")),
    ("read", OSError("Synthetic disk read error")),
])
def test_filesystem_errors_preserve_history_and_remain_retryable(saved_asset, monkeypatch, stage, error):
    saved = saved_asset
    before = _metadata()
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == saved.path and stage == "stat":
            raise error
        return original_stat(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "stat", stat)
        trace = _intercept(scoped, saved, error=error, stage=stage)
        with pytest.raises(library.LibraryError, match="unavailable") as caught:
            _read(saved)
    assert caught.value.__cause__ is error
    assert trace.stream is None or trace.stream.closed
    assert _metadata() == before and _read(saved) == saved.raw


def test_saved_snapshot_keeps_original_asset_after_library_replacement(saved_asset):
    saved = saved_asset
    draft = synthetic_draft(saved.profile, ReportPeriod(2026, 9))
    draft = replace(draft, blocks=(*draft.blocks, saved.state.block("org_chart")))
    library.save_snapshot(draft, expected_revision=0)
    latest = replace_chart(saved.profile, 2, "blue")
    before = _metadata()
    reopened = library.load_snapshot(saved.profile.contract, saved.profile.key, draft.period)
    reference = reopened.draft.blocks[-1].asset_hashes[0]
    assert library.read_asset(saved.profile.contract, saved.profile.key, reference) == saved.raw
    assert library.read_asset(saved.profile.contract, saved.profile.key,
                              latest.block("org_chart").asset_hashes[0]) == png("blue")[1]
    assert _metadata() == before
