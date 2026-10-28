"""Saved logo reuse and restore enforce their existing byte budget *while* reading.

All inputs are synthetic. Simulated source growth happens after the stat
precheck; the production helper never writes or trims retained source bytes.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app import monthly_report_branding as branding
from test_monthly_report_branding import collection


class MeteredRead:
    def __init__(self, stream, calls):
        self.stream = stream
        self.calls = calls

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def read(self, size=-1):
        self.calls.append(size)
        if size < 0:
            raise AssertionError("A saved logo was read without a byte limit")
        return self.stream.read(size)


def watch_logo_open(monkeypatch, path, calls, *, grow=False, substitute=None):
    """Instrument just the exact PNG read; locks and other files stay native."""
    opening = Path.open
    opened = []

    def open_asset(candidate, mode="r", *args, **kwargs):
        if candidate == path and mode == "rb":
            opened.append(candidate)
            if grow:
                # This mutation of a synthetic fixture occurs AFTER stat().
                # A byte added here must be rejected by the bounded read,
                # not only by a later image/fingerprint validation.
                with opening(candidate, "ab") as stream:
                    stream.write(b"!")
            actual = (BytesIO(substitute) if substitute is not None
                      else opening(candidate, mode, *args, **kwargs))
            return MeteredRead(actual, calls)
        return opening(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_asset)
    return opened


@pytest.fixture
def installed(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    logos, assets = collection()
    state = branding.save_branding(
        logos, assets, expected_revision=0, actor="Synthetic Initial Editor",
        confirmed=True,
    )
    logo, = logos
    raw = assets[logo.asset]
    path = branding._path() / "assets" / logo.asset
    assert path.read_bytes() == raw
    return state, logo, raw, path


def test_exact_size_saved_logo_read_is_bounded_and_byte_identical(
        installed, monkeypatch):
    state, logo, raw, path = installed
    calls = []
    with monkeypatch.context() as scope:
        scope.setattr(branding, "MAX_IMAGE_BYTES", len(raw))
        opened = watch_logo_open(scope, path, calls)
        assert branding.read_logo(logo) == raw
    assert opened == [path]
    assert calls == [len(raw) + 1]
    assert path.read_bytes() == raw
    assert branding.load_branding() == state


def test_oversized_metadata_precheck_refuses_without_any_source_open(
        installed, monkeypatch):
    state, logo, raw, path = installed
    calls = []
    with monkeypatch.context() as scope:
        scope.setattr(branding, "MAX_IMAGE_BYTES", len(raw) - 1)
        opened = watch_logo_open(scope, path, calls)
        with pytest.raises(branding.LogoArtworkError, match="size limit"):
            branding.read_logo(logo)
    assert opened == [] and calls == []
    assert path.read_bytes() == raw
    assert branding.load_branding() == state


def test_growing_file_between_stat_and_open_is_rejected_before_decoding(
        installed, monkeypatch):
    state, logo, original, path = installed
    calls = []
    try:
        with monkeypatch.context() as scope:
            scope.setattr(branding, "MAX_IMAGE_BYTES", len(original))
            opened = watch_logo_open(scope, path, calls, grow=True)
            scope.setattr(branding, "_image",
                          lambda *_: pytest.fail("Over-limit artwork reached the image decoder"))
            with pytest.raises(branding.LogoArtworkError, match="size limit"):
                branding.read_logo(logo)
        assert opened == [path] and calls == [len(original) + 1]
        assert path.read_bytes() == original + b"!"
    finally:
        # Only repair the intentionally altered synthetic fixture.
        path.write_bytes(original)
    assert branding.read_logo(logo) == original
    assert branding.load_branding() == state


def test_same_length_swapped_artwork_cannot_bypass_original_sha(
        installed, monkeypatch):
    state, logo, raw, path = installed
    different = bytes([raw[0] ^ 1]) + raw[1:]
    assert different != raw and len(different) == len(raw)
    calls = []
    with monkeypatch.context() as scope:
        scope.setattr(branding, "MAX_IMAGE_BYTES", len(raw))
        opened = watch_logo_open(scope, path, calls, substitute=different)
        with pytest.raises(branding.LogoArtworkError, match="fingerprint"):
            branding.read_logo(logo)
    assert opened == [path] and calls == [len(raw) + 1]
    assert path.read_bytes() == raw
    assert branding.load_branding() == state
    assert branding.read_logo(logo) == raw


def test_restore_reads_existing_logo_with_same_cap_and_preserves_history(
        installed, monkeypatch):
    state, logo, raw, path = installed
    initial_history = (branding._path() / "history" / "00000001.json").read_bytes()
    calls = []
    with monkeypatch.context() as scope:
        scope.setattr(branding, "MAX_IMAGE_BYTES", len(raw))
        opened = watch_logo_open(scope, path, calls)
        saved = branding.restore_branding(
            1, expected_revision=1, actor="Synthetic Restorer", confirmed=True)
    assert saved.revision == 2 and saved.action == "restore:1"
    assert opened == [path] and calls == [len(raw) + 1]
    assert path.read_bytes() == raw
    assert (branding._path() / "history" / "00000001.json").read_bytes() == initial_history
    assert branding.load_branding(1) == state
    assert branding.load_branding() == saved


def test_growing_existing_logo_cannot_publish_a_new_shared_collection(
        installed, monkeypatch):
    state, logo, original, path = installed
    manifest = (branding._path() / "manifest.json").read_bytes()
    initial_history = (branding._path() / "history" / "00000001.json").read_bytes()
    calls = []
    try:
        with monkeypatch.context() as scope:
            scope.setattr(branding, "MAX_IMAGE_BYTES", len(original))
            opened = watch_logo_open(scope, path, calls, grow=True)
            scope.setattr(branding, "_image",
                          lambda *_: pytest.fail("Over-limit restore reached image validation"))
            with pytest.raises(branding.LogoArtworkError, match="size limit"):
                branding.restore_branding(
                    1, expected_revision=1, actor="Synthetic Restorer", confirmed=True)
        assert opened == [path] and calls == [len(original) + 1]
    finally:
        path.write_bytes(original)
    assert (branding._path() / "manifest.json").read_bytes() == manifest
    assert (branding._path() / "history" / "00000001.json").read_bytes() == initial_history
    assert not (branding._path() / "history" / "00000002.json").exists()
    assert branding.load_branding() == state
    assert branding.read_logo(logo) == original
    # No stale new revision was written: an intentional corrected retry works.
    saved = branding.restore_branding(
        1, expected_revision=1, actor="Synthetic Restorer", confirmed=True)
    assert saved.revision == 2
    assert branding.read_logo(logo) == original


def test_unreadable_asset_does_not_publish_a_new_version_and_healthy_choice_survives(
        installed, monkeypatch):
    state, logo, original, path = installed
    before = (branding._path() / "manifest.json").read_bytes()
    path.unlink()
    with pytest.raises(branding.LogoArtworkError, match="could not be read"):
        branding.restore_branding(
            1, expected_revision=1, actor="Synthetic Restorer", confirmed=True)
    assert (branding._path() / "manifest.json").read_bytes() == before
    assert branding.load_branding() == state
    assert not (branding._path() / "history" / "00000002.json").exists()
    path.write_bytes(original)
    assert branding.read_logo(logo) == original
