"""A33 synthetic upload controls: no real client sources or screenshots."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import resource
import subprocess
import sys
import time
import tracemalloc

import pytest

from app import monthly_report_sources as sources
from app.monthly_report_model import synthetic_profiles
from app.monthly_report_streamed_upload import (
    ingest_uploaded_selection, stage_upload,
)

MIB = 1024 * 1024
CHUNK = b"0123456789ABCDEF" * (MIB // 16)


class GeneratedUpload:
    """Virtual file: no upload-sized original Python allocation."""

    def __init__(self, name, size, *, advertised=None, fail_after=None):
        self.name = name
        self.real_size = size
        self.size = size if advertised is None else advertised
        self.offset = 0
        self.fail_after = fail_after

    def seek(self, offset, whence=0):
        assert whence == 0
        self.offset = offset
        return self.offset

    def read(self, count=-1):
        if self.fail_after is not None and self.offset >= self.fail_after:
            raise KeyboardInterrupt("request abandoned during transfer")
        if count < 0:
            raise AssertionError("unbounded read")
        take = min(count, self.real_size - self.offset)
        self.offset += take
        return CHUNK[:take]

    def getvalue(self):
        raise AssertionError("eager full upload was requested")


class MemoryUpload(GeneratedUpload):
    def __init__(self, name, data):
        self.data = data
        super().__init__(name, len(data))

    def read(self, count=-1):
        if count < 0:
            raise AssertionError("unbounded read")
        chunk = self.data[self.offset:self.offset + count]
        self.offset += len(chunk)
        return chunk


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    return synthetic_profiles()[0]


@pytest.mark.parametrize("mib", [30, 128])
def test_large_synthetic_staging_keeps_heap_bounded_and_hash_exact(mib):
    upload = GeneratedUpload("synthetic.docx", mib * MIB)
    before_wall, before_cpu = time.perf_counter(), time.process_time()
    before_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    first_status = []
    tracemalloc.start()
    try:
        with stage_upload(upload, mib * MIB,
                          on_progress=lambda n: first_status.append(
                              time.perf_counter() - before_wall) if not first_status else None) as staged:
            assert staged.size == mib * MIB
            with staged.path.open("rb") as f:
                assert hashlib.file_digest(f, "sha256").hexdigest() == staged.sha256
            expected = hashlib.sha256()
            for _ in range(mib):
                expected.update(CHUNK)
            assert staged.sha256 == expected.hexdigest()
            path = staged.path
        _, peak_heap = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"A33 {mib} MiB: wall_s={time.perf_counter()-before_wall:.3f} "
          f"cpu_s={time.process_time()-before_cpu:.3f} "
          f"rss_peak_kib={rss_kib} rss_growth_kib={rss_kib-before_rss} "
          f"first_progress_s={first_status[0] if first_status else -1:.3f} "
          f"python_heap_peak_bytes={peak_heap}")
    assert first_status and peak_heap < 16 * MIB
    assert not path.exists()  # anonymous descriptor is gone on context exit
    assert upload.offset == 0


def test_advertised_size_cannot_bypass_actual_limit_and_failure_reclaims_stage():
    upload = GeneratedUpload("fake.pdf", 2 * MIB + 1, advertised=MIB)
    with pytest.raises(ValueError, match="2 MiB"):
        with stage_upload(upload, 2 * MIB):
            pytest.fail("over-limit bytes were admitted")
    assert upload.offset == 0
    with pytest.raises(ValueError, match="2 MiB"):
        with stage_upload(GeneratedUpload("fake.pdf", 3 * MIB), 2 * MIB):
            pytest.fail("over-limit advertised size was admitted")


def test_mixed_files_duplicate_edit_retry_and_original_roundtrip(profile):
    one = b"Completed synthetic HVAC inspection for Demonstration Site A."
    two = b"Completed synthetic boiler inspection for Demonstration Site B."
    broken = b"%PDF-1.7\nsynthetic damaged body"
    checkpoints = []
    files = [
        MemoryUpload("first.txt", one),
        MemoryUpload("damaged.pdf", broken),
        MemoryUpload("unsupported.exe", b"no"),
        MemoryUpload("second.txt", two),
    ]
    current, messages, receipts = ingest_uploaded_selection(
        profile, files, on_checkpoint=lambda items: checkpoints.append(tuple(items)))
    assert [r[1] for r in receipts] == ["accepted", "rejected", "rejected", "accepted"]
    assert len(current) == 2 and len(checkpoints) == 2
    assert [c.source.filename for c in current] == ["first.txt", "second.txt"]
    assert sources.source_bytes(profile, current[0].source) == one
    assert sources.source_bytes(profile, current[1].source) == two
    broken_path = sources._path(profile, hashlib.sha256(broken).hexdigest(), ".pdf")
    assert not broken_path.exists()
    assert any("damaged.pdf" in m for m in messages)

    reviewed = replace(current[0], source=replace(
        current[0].source, classification="Vendor service", vendor="Synthetic Test Vendor"))
    accepted = (reviewed, current[1])
    duplicate, _, statuses = ingest_uploaded_selection(
        profile, [MemoryUpload("renamed.txt", one)], accepted)
    assert statuses[0][1] == "duplicate"
    assert duplicate == accepted  # provenance and accepted human fields are intact
    assert sources.source_bytes(profile, reviewed.source) == one

    # Valid replacement of a failed file uses the same chooser, with no stale
    # failure capable of overwriting a previously accepted source.
    retried, _, statuses = ingest_uploaded_selection(
        profile, [MemoryUpload("damaged.txt", b"Completed synthetic retry.")], duplicate)
    assert statuses[0][1] == "accepted"
    assert len(retried) == 3
    assert all(c.source.id in {r.source.id for r in retried} for c in accepted)
    assert sources.ingest(profile, "reload.txt", one)[0].source.sha256 == reviewed.source.sha256


def test_mid_read_keyboard_interrupt_keeps_checkpoint_and_no_named_partial(profile):
    first = b"Completed synthetic filter cleaning."
    checkpoints = []
    current, _, _ = ingest_uploaded_selection(
        profile, [MemoryUpload("accepted.txt", first)],
        on_checkpoint=lambda items: checkpoints.append(items))
    assert len(checkpoints) == 1
    with pytest.raises(KeyboardInterrupt, match="abandoned"):
        ingest_uploaded_selection(
            profile, [GeneratedUpload("interrupted.txt", 4 * MIB, fail_after=2 * MIB)],
            current)
    assert sources.source_bytes(profile, checkpoints[-1][0].source) == first
    target_dir = sources._path(profile, "0" * 64, ".txt").parent
    assert all(not p.name.startswith(".pending-") for p in target_dir.iterdir())


@pytest.mark.skipif(sys.platform != "linux", reason="anonymous descriptor crash guarantee is Linux-specific")
def test_process_death_leaves_no_stage_file(tmp_path):
    # os._exit bypasses Python finally blocks and TemporaryDirectory cleanup.
    # A Linux anonymous TemporaryFile still leaves no pathname on disk.
    script = """
import os
from app.monthly_report_streamed_upload import stage_upload
class U:
    size = 2 * 1024 * 1024
    def __init__(self): self.offset = 0
    def seek(self, n): self.offset = n
    def read(self, n):
        x = min(n, self.size - self.offset)
        self.offset += x
        return b'x' * x
with stage_upload(U(), 2 * 1024 * 1024) as stage:
    assert stage.path.read_bytes() == b'x' * (2 * 1024 * 1024)
    os._exit(47)
"""
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    child = subprocess.run([sys.executable, "-c", script], env=env,
                           capture_output=True, text=True)
    assert child.returncode == 47, child.stderr
    assert list(tmp_path.iterdir()) == []


def test_staged_source_publish_exception_does_not_erase_prior_original(profile, monkeypatch):
    from app.monthly_report_streamed_upload import publish_staged_original
    before = b"Completed synthetic prior inspection."
    accepted, _, _ = ingest_uploaded_selection(profile, [MemoryUpload("before.txt", before)])
    stored_path = sources._path(profile, accepted[0].source.sha256, ".txt")
    assert stored_path.read_bytes() == before
    with stage_upload(MemoryUpload("other.txt", b"other synthetic data"), 30 * MIB) as staged:
        def fail(*args, **kwargs):
            raise OSError("simulated disk failure")
        monkeypatch.setattr(os, "replace", fail)
        with pytest.raises(OSError, match="simulated disk"):
            publish_staged_original(sources._path(profile, staged.sha256, ".txt"), staged)
    assert stored_path.read_bytes() == before
    assert not sources._path(profile, staged.sha256, ".txt").exists()
    assert all(not p.name.startswith(".pending-") for p in stored_path.parent.iterdir())
