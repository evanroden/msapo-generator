"""Offline fail-closed checks for the local-only retrospective #291 runner."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("retention_policy_comparison", ROOT / "scripts/compare_directory_retention_policy.py")
comparison = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparison)


def observation():
    return dict(source_sha=comparison.BEFORE, source_snapshot="before", fixture_sha256=comparison.FIXTURE_SHA,
        fixture_age_days=31, native_browser=False, real_calendar_elapsed=False,
        before_action_raw_exact=True, preview_and_unconfirmed_not_persisted=True,
        history_unchanged=True, archived_state_unchanged=True, fingerprint_preserved=True,
        ordinary_root_unchanged=True, synthetic_only=True)


def test_comparison_requires_all_preservation_evidence():
    assert comparison.valid_observation(observation(), comparison.BEFORE, "before")
    for key in observation():
        missing = observation()
        del missing[key]
        assert not comparison.valid_observation(missing, comparison.BEFORE, "before"), key


@pytest.mark.parametrize("ref", ["main", "HEAD", "-x", "df8b748", "f" * 39, "G" * 40])
def test_comparison_accepts_only_full_immutable_commit_ids(ref, monkeypatch):
    monkeypatch.setattr(comparison, "git", lambda *a: pytest.fail("Git must not be invoked for invalid refs"))
    with pytest.raises(ValueError, match="exact full commit"):
        comparison.resolve(ref)


def test_comparison_never_reuses_an_output_directory(tmp_path, monkeypatch):
    after = "a" * 40
    monkeypatch.setattr(comparison, "resolve", lambda ref: ref)
    monkeypatch.setattr(comparison, "run_probe", lambda *a: pytest.fail("Must not execute into existing evidence"))
    with pytest.raises(FileExistsError):
        comparison.main(["--after", after, "--output", str(tmp_path)])


@pytest.mark.parametrize("name,kind", [("../escape", "file"), ("/escape", "file"), ("symlink", "link")])
def test_source_extraction_rejects_traversal_and_links(tmp_path, monkeypatch, name, kind):
    import io
    import tarfile
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        item = tarfile.TarInfo(name)
        if kind == "link":
            item.type = tarfile.SYMTYPE
            item.linkname = "outside"
        tar.addfile(item)
    monkeypatch.setattr(comparison, "git", lambda *a: raw.getvalue())
    with pytest.raises(ValueError):
        comparison.snapshot(comparison.BEFORE, tmp_path / "source")
    assert not (tmp_path / "escape").exists()
