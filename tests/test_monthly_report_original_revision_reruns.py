"""A26 synthetic 30/128 MiB source read controls and duplicate rehash proofs.

The large byte controls intentionally are not parseable DOCX/TXT reports:
they exercise only the unchanged source_bytes admission and identity boundary,
not genuine document/thumbnail/report acceptance.
"""
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import time

import pytest

from app import monthly_report_library as library, monthly_report_sources as sources
from app.monthly_report_model import Facility, ReportProfile, ReportSource
from app.monthly_report_source_revision import verified_source_revision


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return ReportProfile("A26 Synthetic Byte Control", "north", "Synthetic North",
                         (Facility("north", "Synthetic North"),))


def _watch_original(monkeypatch, path):
    native = Path.open
    calls = []

    def opening(self, *args, **kwargs):
        if self == path and args and args[0] == "rb":
            calls.append(True)
        return native(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opening)
    return calls


@pytest.mark.parametrize("size_mib,suffix", [(30, ".txt"), (128, ".docx")])
def test_large_unchanged_source_controls_skip_repeated_ui_identity_reads(
        profile, monkeypatch, size_mib, suffix):
    # Hash and write in one-megabyte chunks, without keeping 128 MiB in RAM.
    chunk = bytes([size_mib]) * (1024 * 1024)
    checksum = sha256()
    for _ in range(size_mib):
        checksum.update(chunk)
    digest = checksum.hexdigest()
    source = ReportSource(digest, "synthetic-large" + suffix, digest, suffix)
    path = sources._path(profile, source.sha256, source.suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        for _ in range(size_mib):
            output.write(chunk)
    assert path.stat().st_size == size_mib * 1024 * 1024
    reads = _watch_original(monkeypatch, path)
    def measured(action):
        begin_wall, begin_cpu = time.perf_counter(), time.process_time()
        action()
        return (time.perf_counter() - begin_wall, time.process_time() - begin_cpu)

    # This remains the final consumer contract: full bounded original read on
    # each call, no shortcuts. It is also the actual current-main control.
    def full_read_control():
        for _ in range(3):
            # The existing reader already hashes on every call. Never retain
            # multiple 128-MiB buffers or add a second SHA to this control.
            assert len(sources.source_bytes(profile, source)) == size_mib * 1024 * 1024
    baseline_wall, baseline_cpu = measured(full_read_control)
    assert len(reads) == 3
    reads.clear()
    cold_wall, cold_cpu = measured(lambda: verified_source_revision(profile, source))
    assert len(reads) == 1
    reads.clear()
    warm_wall, warm_cpu = measured(
        lambda: [verified_source_revision(profile, source) for _ in range(3)])
    assert reads == []
    assert path.stat().st_size == size_mib * 1024 * 1024
    # Concrete reproducible control record; workflow retains this synthetic
    # JSON artifact if the exact-head Tests job actually runs.
    artifact = Path("test-artifacts/independent-synthetic")
    artifact.mkdir(parents=True, exist_ok=True)
    (artifact / f"a26-source-control-{size_mib}mib.json").write_text(json.dumps({
        "control": "3 direct source_bytes calls vs 1 cold+3 warm identity-only calls",
        "size_mib": size_mib,
        "before_full_reads": 3,
        "after_cold_full_reads": 1,
        "after_warm_full_reads": 0,
        "baseline_wall_seconds": baseline_wall,
        "baseline_cpu_seconds": baseline_cpu,
        "cold_wall_seconds": cold_wall,
        "cold_cpu_seconds": cold_cpu,
        "warm_wall_seconds": warm_wall,
        "warm_cpu_seconds": warm_cpu,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cpu_max": Path("/sys/fs/cgroup/cpu.max").read_text().strip()
                   if Path("/sys/fs/cgroup/cpu.max").exists() else "not available",
        "memory_max": Path("/sys/fs/cgroup/memory.max").read_text().strip()
                      if Path("/sys/fs/cgroup/memory.max").exists() else "not available",
        "note": "Synthetic byte identity only; not a valid DOCX or served UI test.",
    }, indent=2))


def test_repeated_duplicate_keeps_reviewed_fields_and_stops_full_original_reads(profile, monkeypatch):
    raw = b"Synthetic North: inspected pump TEST-27.\n"
    first, _ = sources.ingest(profile, "synthetic.txt", raw)
    reviewed = replace(first, source=replace(first.source,
                       actions="Human edited: test action preserved.",
                       captions=((1, "Human caption"),)))
    path = sources._path(profile, reviewed.source.sha256, reviewed.source.suffix)
    reads = _watch_original(monkeypatch, path)
    result, notes = sources.ingest_batch(profile, (("again.txt", raw),), (reviewed,))
    assert result == (reviewed,) and notes == ("Duplicate skipped: again.txt",)
    assert reads == [True]  # first identity-only check does a real hash
    reads.clear()
    for _ in range(3):
        result, notes = sources.ingest_batch(profile, (("again.txt", raw),), result)
        assert result == (reviewed,) and notes == ("Duplicate skipped: again.txt",)
    assert reads == []


def test_corrupt_original_is_restored_on_exact_duplicate_without_losing_review(profile):
    raw = b"Synthetic North: inspected pump TEST-34.\n"
    first, _ = sources.ingest(profile, "original.txt", raw)
    first = replace(first, source=replace(first.source,
                    actions="Accepted human inspection edit"))
    path = sources._path(profile, first.source.sha256, first.source.suffix)
    verified_source_revision(profile, first.source)
    stamp = path.stat()
    path.unlink()
    path.write_bytes(b"X" * len(raw))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert len(path.read_bytes()) == len(raw)
    fixed, notes = sources.ingest_batch(profile, (("repair.txt", raw),), (first,))
    assert fixed == (first,)
    assert notes == ("Saved source restored: repair.txt. Prior reviews and report history are unchanged.",)
    assert sources.source_bytes(profile, first.source) == raw


def test_wrong_site_malformed_reference_and_missing_original_are_not_cached(profile):
    raw = b"Synthetic source for North"
    first, _ = sources.ingest(profile, "scope.txt", raw)
    source = first.source
    verified_source_revision(profile, source)
    other = replace(profile, key="south", title="South",
                    facilities=(Facility("south", "South"),))
    with pytest.raises(FileNotFoundError):
        verified_source_revision(other, source)
    with pytest.raises(ValueError, match="reference"):
        verified_source_revision(profile, replace(source, sha256="../escape"))
    path = sources._path(profile, source.sha256, source.suffix)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        verified_source_revision(profile, source)
