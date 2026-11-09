"""Local-only retrospective #291 policy comparison on exact Git snapshots.

No fetching, service calls, browser, production data, policy edits or cleanup.
Run from a complete clone. Each invocation owns a NEW output directory and
preserves the before failure and after result. See docs/DIRECTORY_RETENTION_291.md.
"""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile

REPO = Path(__file__).resolve().parents[1]
BEFORE = "45ecc27b7948423049404a70ed58d3f1155c6c2b"
sys.path.insert(0, str(REPO))
from scripts.directory_retention_fixture import FIXTURE_NAME, FIXTURE_SHA, write_fixture

FIXTURE_GENERATOR = REPO / "scripts/directory_retention_fixture.py"
PROBE = REPO / "scripts/directory_retention_policy_probe.py"
HISTORICAL_FIXTURE_SHA = "32f56e5c991c91eb0d328858848b1c998ff4422e7abdef6aca1d22478ad4bf8e"


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(REPO), *args], timeout=60)


def resolve(ref: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        raise ValueError("Use an exact full commit SHA, not a moving ref")
    actual = git("rev-parse", "--verify", ref + "^{commit}").decode().strip()
    if actual != ref:
        raise ValueError("Commit identity mismatch")
    return actual


def snapshot(commit: str, dest: Path) -> dict:
    """Extract files only from a local exact commit, never links or traversal."""
    dest.mkdir()
    with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", commit))) as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            if name.is_absolute() or ".." in name.parts or not name.parts:
                raise ValueError("Unsafe archived path")
            path = dest.joinpath(*name.parts)
            if item.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif item.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as src, path.open("xb") as out:
                    out.write(src.read())
            else:
                raise ValueError("Only regular files and directories are permitted")
    return verify_snapshot(commit, dest)


def verify_snapshot(commit: str, dest: Path) -> dict:
    count = 0
    for entry in git("ls-tree", "-rz", commit).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, expected = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise ValueError("Unsupported source tree entry")
        path = dest / os.fsdecode(name)
        if path.is_symlink():
            raise ValueError("Source snapshot changed to a symlink")
        data = path.read_bytes()
        actual = sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != expected.decode():
            raise ValueError("Source blob differs: " + os.fsdecode(name))
        count += 1
    return {"commit": commit, "tree": git("rev-parse", commit + "^{tree}").decode().strip(),
            "verified_tracked_blobs": count}


def valid_observation(record: dict, commit: str, phase: str) -> bool:
    preserved = ("before_action_raw_exact", "preview_and_unconfirmed_not_persisted",
                 "history_unchanged", "archived_state_unchanged", "fingerprint_preserved",
                 "ordinary_root_unchanged", "synthetic_only")
    return (record.get("source_sha") == commit and record.get("source_snapshot") == phase
            and record.get("fixture_sha256") == FIXTURE_SHA
            and record.get("fixture_age_days") == 31
            and record.get("native_browser") is False
            and record.get("real_calendar_elapsed") is False
            and all(record.get(k) is True for k in preserved))


def checked_fixture(output: Path) -> Path:
    fixture = output / FIXTURE_NAME
    if (fixture.is_symlink() or fixture.resolve() != fixture or not fixture.is_file()
            or fixture.stat().st_size > 65536 or sha256(fixture.read_bytes()).hexdigest() != FIXTURE_SHA):
        raise ValueError("Synthetic fixture identity changed")
    return fixture


def run_probe(output: Path, phase: str, commit: str) -> dict:
    fixture = checked_fixture(output)
    folder = output / phase
    folder.mkdir()
    source = folder / "source"
    provenance = snapshot(commit, source)
    home = folder / "home"
    home.mkdir()
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT") if k in os.environ}
    env.update(HOME=str(home), PYTHONDONTWRITEBYTECODE="1", ANTHROPIC_API_KEY="test-key-not-used",
               OPENAI_API_KEY="", SMARTSHEET_API_MODE="disabled", STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
               RETENTION_COMPARISON_OUTPUT=str(output), RETENTION_COMPARISON_SOURCE=str(source),
               RETENTION_COMPARISON_PHASE=phase, RETENTION_COMPARISON_SHA=commit,
               RETENTION_COMPARISON_FIXTURE=str(fixture), RETENTION_COMPARISON_FIXTURE_SHA=FIXTURE_SHA)
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--confcutdir=" + str(PROBE.parent),
               "--basetemp=" + str(folder / "pytest-data"), "--junitxml=" + str(folder / "results.xml"), str(PROBE)]
    with (folder / "pytest.log").open("xb") as log:
        result = subprocess.run(command, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    assert verify_snapshot(commit, source) == provenance
    checked_fixture(output)
    record = json.loads((folder / "observation.json").read_text())
    expected_retained = phase == "before"
    correct = (valid_observation(record, commit, phase)
               and all(record.get(k) is expected_retained for k in
                       ("raw_remaining", "stamp_remaining", "unreferenced_pool_remaining")))
    if phase == "before":
        correct = correct and result.returncode == 1 and "Approved-policy oracle: eligible raw workbook must expire" in (folder / "pytest.log").read_text()
    else:
        correct = correct and result.returncode == 0
    return {**provenance, "phase": phase, "pytest_exit_code": result.returncode,
            "expected_policy_outcome_verified": correct,
            "pytest_log_sha256": sha256((folder / "pytest.log").read_bytes()).hexdigest(),
            "observation_sha256": sha256((folder / "observation.json").read_bytes()).hexdigest()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default=BEFORE)
    parser.add_argument("--after", required=True, help="Exact candidate/source commit SHA")
    parser.add_argument("--output", type=Path, required=True, help="New disposable output directory; must not exist")
    args = parser.parse_args(argv)
    before, after = resolve(args.before), resolve(args.after)
    if before != BEFORE or before == after:
        raise ValueError("Before must be the audited pre-policy commit and distinct from after")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_fixture(output)
    checked_fixture(output)
    results = [run_probe(output, phase, commit) for phase, commit in (("before", before), ("after", after))]
    checked_fixture(output)
    manifest = {"results": results, "fixture_sha256": FIXTURE_SHA, "python": sys.version,
                "fixture_generation": "openpyxl cells with fixed document properties and deterministic ZIP metadata",
                "fixture_generator_sha256": sha256(FIXTURE_GENERATOR.read_bytes()).hexdigest(),
                "historical_fixture_sha256": HISTORICAL_FIXTURE_SHA,
                "fixture_matches_historical_bytes": False,
                "probe_sha256": sha256(PROBE.read_bytes()).hexdigest(),
                "same_current_dependency_environment": True, "historical_dependencies_not_reconstructed": True,
                "comparison_is_retrospective": True, "fixture_age_is_injected": True,
                "native_browser": False, "production_request": False}
    with (output / "comparison.json").open("x") as file:
        json.dump(manifest, file, indent=2)
    print(json.dumps(manifest, indent=2))
    return 0 if all(r["expected_policy_outcome_verified"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
