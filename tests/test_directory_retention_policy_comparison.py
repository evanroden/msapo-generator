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


def test_generated_fixture_is_deterministic_despite_zip_clock(monkeypatch):
    from hashlib import sha256
    import time
    import zipfile
    from scripts import directory_retention_fixture as fixture
    monkeypatch.setattr(zipfile.time, "localtime", lambda *a: time.struct_time((2020, 2, 3, 4, 5, 6, 0, 1, -1)))
    first = fixture.workbook_bytes()
    monkeypatch.setattr(zipfile.time, "localtime", lambda *a: time.struct_time((2040, 8, 9, 10, 11, 12, 0, 1, -1)))
    second = fixture.workbook_bytes()
    assert first == second
    assert sha256(first).hexdigest() == fixture.FIXTURE_SHA == comparison.FIXTURE_SHA
    assert fixture.FIXTURE_SHA != comparison.HISTORICAL_FIXTURE_SHA


def test_generated_workbook_has_original_invented_cells_and_visibility():
    from io import BytesIO
    from zipfile import ZipFile, ZIP_STORED
    from openpyxl import load_workbook
    from scripts import directory_retention_fixture as fixture
    raw = fixture.workbook_bytes()
    workbook = load_workbook(BytesIO(raw))
    expected = [
        ("Active Contracts", "visible", {
            "A6": "Contract", "B6": "Synthetic Retention", "C6": "INACTIVE Synthetic Closed",
            "A7": "Address", "B7": "100 Example Way", "A9": "Executive Director",
            "B9": "Synthetic Accepted Executive", "C9": "Synthetic Inactive Person", "A10": "Phone",
            "B10": "202-555-0100", "A11": "Email", "B11": "executive@example.invalid", "C11": "inactive@example.invalid"}),
        ("Synthetic Retention Sites", "visible", {
            "A6": "Facility", "B6": "Synthetic North", "A7": "Address", "B7": "200 Example Way",
            "A9": "Facility Director", "B9": "Synthetic Accepted Site Lead", "A10": "Phone",
            "B10": "202-555-0101", "A11": "Email", "B11": "site@example.invalid"}),
        ("Hidden Retention Archive", "hidden", {
            "A6": "Facility", "B6": "Synthetic Hidden Site", "A9": "Facility Director", "B9": "Synthetic Hidden Person"}),
        ("Index", "visible", {"A1": "Synthetic excluded index marker"}),
    ]
    assert [(sheet.title, sheet.sheet_state, {c.coordinate: c.value for row in sheet for c in row if c.value is not None})
            for sheet in workbook] == expected
    assert all(c.data_type == "s" and c.number_format == "General"
               for sheet in workbook for row in sheet for c in row if c.value is not None)
    assert workbook.properties.created == workbook.properties.modified == fixture.FIXED_TIME
    assert workbook.properties.creator == "Synthetic Directory Retention QA"
    workbook.close()
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        assert all(info.date_time == fixture.ZIP_TIME and info.compress_type == ZIP_STORED
                   and info.create_system == 3 and info.external_attr == 0o600 << 16
                   for info in archive.infolist())


def test_generator_emits_only_once_into_new_empty_owned_output(tmp_path, monkeypatch):
    from scripts import directory_retention_fixture as fixture
    output = tmp_path / "owned"
    output.mkdir()
    path = fixture.write_fixture(output)
    assert path == output / fixture.FIXTURE_NAME and list(output.iterdir()) == [path]
    original = path.read_bytes()
    monkeypatch.setattr(fixture, "workbook_bytes", lambda: pytest.fail("No regeneration on reuse"))
    with pytest.raises(ValueError, match="new empty"):
        fixture.write_fixture(output)
    assert path.read_bytes() == original
    linked = tmp_path / "linked"
    linked.symlink_to(output, target_is_directory=True)
    with pytest.raises(ValueError):
        fixture.write_fixture(linked)


def test_same_generated_file_and_bytes_used_for_both_phases(tmp_path, monkeypatch):
    from hashlib import sha256
    import json
    after = "a" * 40
    output = tmp_path / "new-evidence"
    monkeypatch.setattr(comparison, "resolve", lambda ref: ref)
    seen = []
    def probe(owned, phase, commit):
        path = comparison.checked_fixture(owned)
        seen.append((phase, commit, path, path.read_bytes()))
        return {"phase": phase, "expected_policy_outcome_verified": True}
    monkeypatch.setattr(comparison, "run_probe", probe)
    assert comparison.main(["--after", after, "--output", str(output)]) == 0
    assert [(x[0], x[1]) for x in seen] == [("before", comparison.BEFORE), ("after", after)]
    assert seen[0][2:] == seen[1][2:]
    manifest = json.loads((output / "comparison.json").read_text())
    assert manifest["fixture_sha256"] == sha256(seen[0][3]).hexdigest() == comparison.FIXTURE_SHA
    assert manifest["historical_fixture_sha256"] == "32f56e5c991c91eb0d328858848b1c998ff4422e7abdef6aca1d22478ad4bf8e"
    assert manifest["fixture_matches_historical_bytes"] is False
    assert manifest["fixture_generator_sha256"] == sha256(comparison.FIXTURE_GENERATOR.read_bytes()).hexdigest()


@pytest.mark.parametrize("mutation", ["bytes", "symlink"])
def test_changed_fixture_stops_before_phase_source_extraction(tmp_path, monkeypatch, mutation):
    from scripts import directory_retention_fixture as fixture
    path = fixture.write_fixture(tmp_path)
    if mutation == "bytes":
        path.write_bytes(b"modified synthetic data")
    else:
        other = tmp_path / "other"
        path.rename(other)
        path.symlink_to(other)
    monkeypatch.setattr(comparison, "snapshot", lambda *a: pytest.fail("Snapshot must not start after fixture drift"))
    with pytest.raises(ValueError, match="identity changed"):
        comparison.run_probe(tmp_path, "before", comparison.BEFORE)


def test_fixture_mutation_during_probe_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from scripts import directory_retention_fixture as fixture
    path = fixture.write_fixture(tmp_path)
    provenance = {"commit": comparison.BEFORE, "tree": "b" * 40, "verified_tracked_blobs": 1}
    monkeypatch.setattr(comparison, "snapshot", lambda *a: provenance)
    monkeypatch.setattr(comparison, "verify_snapshot", lambda *a: provenance)
    def run(*args, **kwargs):
        assert kwargs["env"]["RETENTION_COMPARISON_FIXTURE"] == str(path)
        assert kwargs["env"]["RETENTION_COMPARISON_FIXTURE_SHA"] == fixture.FIXTURE_SHA
        path.write_bytes(b"changed while phase ran")
        return SimpleNamespace(returncode=1)
    monkeypatch.setattr(comparison.subprocess, "run", run)
    with pytest.raises(ValueError, match="identity changed"):
        comparison.run_probe(tmp_path, "before", comparison.BEFORE)


def test_probe_keeps_pinned_fixture_and_policy_oracles():
    source = comparison.PROBE.read_text()
    assert comparison.FIXTURE_SHA in source
    assert 'assert not FIXTURE.is_symlink() and FIXTURE == BASE / "synthetic-retention.xlsx"' in source
    assert 'assert history_same and archive_same and fingerprint_same' in source
    assert 'Approved-policy oracle: eligible raw workbook must expire' in source
    assert 'assert not stamp.exists() and not pooled.exists()' in source
    assert 'assert contents(ordinary) == ordinary_before' in source


def test_fixture_is_repeatable_in_fresh_processes_with_different_timezone_and_hash_seed():
    import os
    import subprocess
    import sys
    command = [sys.executable, "-c", "from hashlib import sha256; from scripts.directory_retention_fixture import workbook_bytes; print(sha256(workbook_bytes()).hexdigest())"]
    observed = []
    for timezone, seed in (("UTC", "1"), ("Pacific/Honolulu", "98765")):
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "TZ": timezone, "PYTHONHASHSEED": seed}
        observed.append(subprocess.check_output(command, cwd=ROOT, env=env, text=True, timeout=20).strip())
    assert observed == [comparison.FIXTURE_SHA, comparison.FIXTURE_SHA]
