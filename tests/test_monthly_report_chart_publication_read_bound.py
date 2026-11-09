"""Publishing a chart cannot read an existing picture beyond its current cap."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import monthly_report_library as library, monthly_report_org_chart_defaults as charts
from test_monthly_report_org_chart_defaults import scopes, publish, picture, fresh, with_chart
from test_monthly_report_org_chart_defaults_ui import start, button


@pytest.fixture(autouse=True)
def synthetic_model_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")


def files():
    """Fingerprint actual stored bytes without another large allocation."""
    root = library._root()
    result = {}
    for path in root.rglob("*"):
        if path.is_file() and path.name != ".write-lock":
            with path.open("rb") as source:
                result[str(path.relative_to(root))] = (
                    path.stat().st_size, hashlib.file_digest(source, "sha256").hexdigest())
    return result


def asset_path(draft, block):
    return charts._path(draft.profile.contract) / "assets" / block.asset_hashes[0]


def replace_test_asset(path, raw):
    # Replace only this temporary link, never mutate an immutable saved original.
    path.unlink()
    path.write_bytes(raw)


def save(draft, block, assets, *, revision=1, scope="contract"):
    return charts.save_default(draft, block, assets, scope=scope,
        expected_revision=revision, expected_fingerprint=block.fingerprint, confirmed=True)


@contextmanager
def observe_reads(monkeypatch, target, *, open_error=None, read_error=None):
    observed = SimpleNamespace(requests=[], lengths=[], streams=[])
    original_open = Path.open

    class ObservedFile:
        def __init__(self, source):
            self.source = source
            observed.streams.append(source)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.source.__exit__(*args)

        def read(self, size=-1):
            observed.requests.append(size)
            if read_error is not None:
                raise read_error
            raw = self.source.read(size)
            observed.lengths.append(len(raw))
            return raw

        def __getattr__(self, name):
            return getattr(self.source, name)

    def observed_open(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if path == target and mode == "rb":
            if open_error is not None:
                raise open_error
            return ObservedFile(original_open(path, *args, **kwargs))
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as current:
        current.setattr(Path, "open", observed_open)
        yield observed


def assert_bounded(observed, cap):
    assert observed.requests, "The pre-existing file must still be verified."
    assert sum(observed.lengths) <= cap + 1, observed.lengths
    assert all(0 <= amount <= cap + 1 for amount in observed.requests), observed.requests
    assert all(stream.closed for stream in observed.streams)


def test_publish_control_bounds_the_real_limit_and_preserves_report_history_and_retry(scopes, monkeypatch):
    profile, _, other, _ = scopes
    draft, block, assets = publish(profile)
    publish(other, "green")
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    manifest = charts._path(profile.contract) / "manifest.json"
    original_manifest = manifest.read_bytes()
    history = charts._path(profile.contract) / "history" / "00000001.json"
    original_history = history.read_bytes()
    target = asset_path(draft, block)
    original = assets[block.asset_hashes[0]]
    cap = library.MAX_ASSET_BYTES
    assert cap == 30 * 1024 * 1024
    app = start(draft, dict(assets))
    app.checkbox[0].check().run()
    assert not button(app, "Publish chart default").disabled
    replace_test_asset(target, b"x" * (cap + 4096))
    before = files()

    with observe_reads(monkeypatch, target) as observed:
        button(app, "Publish chart default").click().run()
    assert not app.exception
    assert any("size or integrity" in warning.value for warning in app.warning)
    assert app.session_state["draft"] == draft
    assert app.session_state["assets"] == assets
    assert manifest.read_bytes() == original_manifest and history.read_bytes() == original_history
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    assert files() == before

    # Restoring only the temporary failed copy enables the ordinary explicit
    # retry. Neither attempt replaces a saved report or another contract's chart.
    other_prefix = str(charts._path(other.contract).relative_to(library._root())) + "/"
    other_before = {name: value for name, value in before.items() if name.startswith(other_prefix)}
    replace_test_asset(target, original)
    app.run()
    app.checkbox[0].check().run()
    button(app, "Publish chart default").click().run()
    assert not app.exception and charts.load_defaults(profile.contract).revision == 2
    assert app.session_state["draft"] == draft and app.session_state["assets"] == assets
    assert history.read_bytes() == original_history
    assert library.load_snapshot(profile.contract, profile.key, draft.period) == saved
    assert charts.read_asset(profile.contract, block.asset_hashes[0]) == original
    after = files()
    assert {name: value for name, value in after.items() if name.startswith(other_prefix)} == other_before
    assert_bounded(observed, cap)


@pytest.mark.parametrize("scope", ["contract", "site"])
def test_exact_size_valid_existing_picture_publishes_without_rewriting_it(scopes, monkeypatch, scope):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    original = target.read_bytes()
    old_stat = target.stat()
    history = charts._path(draft.profile.contract) / "history" / "00000001.json"
    first_history = history.read_bytes()
    saved = library.save_snapshot(draft, expected_revision=0, assets=tuple(assets.items()))
    # A small, real PNG makes the exact inclusive boundary cheap to exercise;
    # the preceding UI case independently checks the unchanged production cap.
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", len(original))
    with observe_reads(monkeypatch, target) as observed:
        result = save(draft, block, assets, scope=scope)
    assert result.revision == 2 and target.read_bytes() == original
    assert (target.stat().st_ino, target.stat().st_mtime_ns) == (old_stat.st_ino, old_stat.st_mtime_ns)
    assert history.read_bytes() == first_history
    assert library.load_snapshot(draft.profile.contract, draft.profile.key, draft.period) == saved
    assert sum(observed.lengths) == len(original)
    assert_bounded(observed, len(original))


def test_new_picture_is_still_verified_and_written_without_an_existing_file_read(scopes, monkeypatch):
    block, assets = picture("blue")
    draft = with_chart(fresh(scopes[0]), block)
    target = asset_path(draft, block)
    assert not target.exists()
    with observe_reads(monkeypatch, target, open_error=AssertionError("No old asset exists")):
        result = save(draft, block, assets, revision=0)
    assert result.revision == 1
    assert charts.read_asset(draft.profile.contract, block.asset_hashes[0]) == assets[block.asset_hashes[0]]


def test_file_growth_after_existence_check_is_bounded_without_publication(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    cap = len(assets[block.asset_hashes[0]])
    monkeypatch.setattr(library, "MAX_ASSET_BYTES", cap)
    grown = b"g" * (cap + 4096)
    expected = files()
    expected[str(target.relative_to(library._root()))] = (len(grown), hashlib.sha256(grown).hexdigest())
    real_exists = Path.exists
    changed = []

    def exists_then_grow(path):
        result = real_exists(path)
        if path == target and result and not changed:
            changed.append(True)
            replace_test_asset(target, grown)
        return result

    monkeypatch.setattr(Path, "exists", exists_then_grow)
    with observe_reads(monkeypatch, target) as observed:
        with pytest.raises(library.LibraryError, match="size or integrity"):
            save(draft, block, assets)
    assert changed and charts.load_defaults(draft.profile.contract).revision == 1
    assert files() == expected
    assert_bounded(observed, cap)


def test_same_size_corruption_still_fails_integrity_without_replacing_stored_bytes(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    raw = target.read_bytes()
    replace_test_asset(target, raw[:-1] + bytes([raw[-1] ^ 1]))
    before = files()
    with observe_reads(monkeypatch, target) as observed:
        with pytest.raises(library.LibraryError, match="size or integrity"):
            save(draft, block, assets)
    assert sum(observed.lengths) == len(raw)
    assert all(stream.closed for stream in observed.streams)
    assert files() == before


@pytest.mark.parametrize("error", [PermissionError("synthetic permission failure"),
                                  OSError("synthetic open failure")])
def test_open_failure_keeps_the_existing_oserror_and_data(scopes, monkeypatch, error):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    before = files()
    with observe_reads(monkeypatch, target, open_error=error) as observed:
        with pytest.raises(type(error)) as raised:
            save(draft, block, assets)
    assert raised.value is error and raised.value.__cause__ is None
    assert not observed.streams and files() == before


def test_read_failure_closes_the_file_and_preserves_the_existing_oserror(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    before = files()
    error = OSError("synthetic read failure")
    with observe_reads(monkeypatch, target, read_error=error) as observed:
        with pytest.raises(OSError) as raised:
            save(draft, block, assets)
    assert raised.value is error and raised.value.__cause__ is None
    assert len(observed.streams) == 1 and observed.streams[0].closed
    assert files() == before


def test_disappearance_after_existence_check_does_not_silently_replace_the_asset(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    before = files()
    del before[str(target.relative_to(library._root()))]
    real_exists = Path.exists
    removed = []

    def exists_then_remove(path):
        result = real_exists(path)
        if path == target and result and not removed:
            removed.append(True)
            target.unlink()
        return result

    with monkeypatch.context() as current:
        current.setattr(Path, "exists", exists_then_remove)
        with pytest.raises(FileNotFoundError) as raised:
            save(draft, block, assets)
    assert removed and raised.value.__cause__ is None and not target.exists()
    assert files() == before
    assert save(draft, block, assets).revision == 2
    assert target.read_bytes() == assets[block.asset_hashes[0]]


def test_stale_revision_is_refused_before_existing_asset_reads(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    before = files()
    with observe_reads(monkeypatch, target, open_error=AssertionError("Stale action read an asset")):
        with pytest.raises(library.RevisionConflict):
            save(draft, block, assets, revision=0)
    assert files() == before


def test_invalid_incoming_picture_cannot_be_replaced_by_a_good_existing_copy(scopes, monkeypatch):
    draft, block, assets = publish(scopes[0])
    target = asset_path(draft, block)
    before = files()
    with observe_reads(monkeypatch, target, open_error=AssertionError("Invalid input read an old asset")):
        with pytest.raises(library.LibraryError, match="size or integrity"):
            save(draft, block, {block.asset_hashes[0]: b"tampered incoming picture"})
    assert files() == before
