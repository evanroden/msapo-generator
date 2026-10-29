"""Native-art source inventory never reads beyond its narrow DOCX byte cap.

Synthetic same-site Word source and artwork come from the existing fixture.
This tests the *second* source read in native-art inventory; the first,
rederive_compatibility_view, already has its own independent byte guard.
"""
from io import BytesIO
from pathlib import Path

import pytest

from app import monthly_report_native_art_review as art
from app.monthly_report_compatibility_view import CompatibilityError
from test_monthly_report_native_art_review import sample


class _MeteredReader:
    """Fail on an unbounded read, while retaining a real context manager."""

    def __init__(self, stream, reads):
        self.stream = stream
        self.reads = reads

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def read(self, size=-1):
        self.reads.append(size)
        if size < 0:
            raise AssertionError("Native-art inventory attempted an unbounded source read")
        return self.stream.read(size)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _intercept_source_open(monkeypatch, path, opens, reads, *, replacement=None,
                           grow_on_open=False):
    original_open = Path.open

    def opened(self, mode="r", *args, **kwargs):
        if self == path and mode == "rb":
            opens.append((self, mode))
            if grow_on_open:
                # This is deliberately AFTER native-art's stat() precheck.
                # The source is a synthetic fixture; never mutate a real file.
                with original_open(self, "ab") as writer:
                    writer.write(b"!")
            if replacement is not None:
                return _MeteredReader(BytesIO(replacement), reads)
            return _MeteredReader(original_open(self, mode, *args, **kwargs), reads)
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)


def test_exact_byte_limit_reads_only_limit_plus_one_and_keeps_inventory(sample, monkeypatch):
    path, view, profile, period, expected, _ = sample
    raw = path.read_bytes()
    opens, reads = [], []
    with monkeypatch.context() as scoped:
        scoped.setattr(art, "MAX_VIEW_SOURCE_BYTES", len(raw))
        _intercept_source_open(scoped, path, opens, reads)
        actual = art._native_art_inventory(path, view, profile, period)
        assert actual == expected
    assert opens == [(path, "rb")]
    assert reads == [len(raw) + 1]
    assert path.read_bytes() == raw


def test_oversized_precheck_rejects_before_open_or_hash(sample, monkeypatch):
    path, view, profile, period, _, _ = sample
    raw = path.read_bytes()
    opens, reads = [], []
    with monkeypatch.context() as scoped:
        scoped.setattr(art, "MAX_VIEW_SOURCE_BYTES", len(raw) - 1)
        _intercept_source_open(scoped, path, opens, reads)
        with pytest.raises(CompatibilityError, match="source exceeds narrow view budget"):
            art._native_art_inventory(path, view, profile, period)
    assert not opens and not reads
    assert path.read_bytes() == raw


def test_source_growth_between_stat_and_open_is_bounded_and_retryable(sample, monkeypatch):
    path, view, profile, period, expected, _ = sample
    original = path.read_bytes()
    opens, reads = [], []
    try:
        with monkeypatch.context() as scoped:
            scoped.setattr(art, "MAX_VIEW_SOURCE_BYTES", len(original))
            _intercept_source_open(scoped, path, opens, reads, grow_on_open=True)
            # A growing file must be rejected by the byte guard, not merely
            # by its later source-hash check or by the Word parser.
            scoped.setattr(
                art, "_hash",
                lambda raw: pytest.fail("Oversized native source reached hashing"),
            )
            with pytest.raises(CompatibilityError, match="source exceeds narrow view budget"):
                art._native_art_inventory(path, view, profile, period)
        assert opens == [(path, "rb")]
        assert reads == [len(original) + 1]
        assert path.read_bytes() == original + b"!"
    finally:
        # Restore only this synthetic file. The production helper never writes.
        path.write_bytes(original)
    assert art._native_art_inventory(path, view, profile, period) == expected
    assert path.read_bytes() == original


def test_same_size_replacement_still_fails_source_hash_without_writing(sample, monkeypatch):
    path, view, profile, period, expected, _ = sample
    original = path.read_bytes()
    altered = bytes([original[0] ^ 1]) + original[1:]
    assert len(altered) == len(original) and altered != original
    opens, reads = [], []
    with monkeypatch.context() as scoped:
        scoped.setattr(art, "MAX_VIEW_SOURCE_BYTES", len(original))
        _intercept_source_open(scoped, path, opens, reads, replacement=altered)
        with pytest.raises(CompatibilityError, match="immutable original changed"):
            art._native_art_inventory(path, view, profile, period)
    assert opens == [(path, "rb")]
    assert reads == [len(original) + 1]
    assert path.read_bytes() == original
    assert art._native_art_inventory(path, view, profile, period) == expected
