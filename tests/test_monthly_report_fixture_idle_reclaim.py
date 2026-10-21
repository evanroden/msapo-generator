"""Another browser's isolated test copy idle for 24 hours is reclaimed (Refs #292).

Owner policy: an abandoned copy may be discarded after a day without use; shared
originals and active or current-browser work never are. Synthetic data only.
"""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from app import memory
from app import monthly_report_fixture_admission as admission
from app import monthly_report_fixture_vault as storage
from app import monthly_report_testing as testing
from app.monthly_report_fixture_runs import FixtureRunContext

A, B = "a" * 32, "b" * 32


@contextmanager
def run(token):
    with testing.isolated(token):
        root = memory._data_dir()
        yield FixtureRunContext(testing.scope(), testing.generation(), root)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(admission.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=2 ** 30, f_frsize=1))
    return tmp_path


def full_copy(token):
    with run(token) as context:
        with admission.admit_run_copy(context, admission.MAX_ACTIVE_COPY_BYTES):
            context.data_root.joinpath("synthetic-copy.bin").write_bytes(b"SYNTHETIC staged copy")
    return context


def age(path, hours):
    stamp = time.time() - hours * 3600
    for directory, directories, files in os.walk(path):
        for name in (*directories, *files):
            os.utime(Path(directory) / name, (stamp, stamp), follow_symlinks=False)
    os.utime(path, (stamp, stamp))


def reservations(root):
    return json.loads((root / admission._BUCKET / "reservations.json").read_bytes())["reservations"]


def test_a_copy_idle_for_a_day_is_reclaimed_and_originals_stay(root):
    original = root / "_enfra_shared_fixtures_v1" / "synthetic" / "source.docx"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"SYNTHETIC immutable original")
    digest = sha256(original.read_bytes()).hexdigest()
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    with run(B) as other:
        with admission.admit_run_copy(other, 4096):
            pass
    assert not abandoned.data_root.exists()
    assert reservations(root) == [{"scope": other.scope, "generation": other.generation, "added_bytes": 4096}]
    assert sha256(original.read_bytes()).hexdigest() == digest
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))


def test_a_copy_used_within_the_day_still_holds_its_budget(root):
    recent = full_copy(A)
    age(recent.data_root, 23)
    with run(B) as other, pytest.raises(storage.VaultQuotaExceeded, match="cleared automatically"):
        with admission.admit_run_copy(other, 1):
            pytest.fail("A recently used copy was reclaimed")
    assert recent.data_root.exists()


def test_viewing_the_copy_counts_as_use(root):
    viewed = full_copy(A)
    age(viewed.data_root, 25)
    with run(A):
        pass  # an ordinary request in that browser's workspace
    with run(B) as other, pytest.raises(storage.VaultQuotaExceeded):
        with admission.admit_run_copy(other, 1):
            pytest.fail("A viewed copy was reclaimed")
    assert viewed.data_root.exists()


def test_the_requesting_browser_and_unsafe_namespaces_are_never_reclaimed(root):
    with run(A) as own:
        assert not testing.reclaim_idle(root, own.scope, own.generation, now=time.time() + 10 ** 7)
    linked = full_copy(B)
    (linked.data_root / "synthetic-link").symlink_to(root)
    age(linked.data_root, 48)
    assert not testing.reclaim_idle(root, linked.scope, linked.generation)
    assert not testing.reclaim_idle(root, linked.scope, "c" * 32)
    assert linked.data_root.exists()


def test_a_returning_stale_task_fails_closed_and_new_work_starts_fresh(root):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    assert testing.reclaim_idle(root, abandoned.scope, abandoned.generation)
    with testing.isolated(A):
        testing._LEASE.set(abandoned.generation)
        with pytest.raises(OSError, match="reset during a running task"):
            memory._data_dir()
    with run(A) as fresh:
        assert fresh.generation != abandoned.generation and fresh.data_root.exists()


def test_an_interrupted_removal_is_finished_on_the_next_pass(root):
    abandoned = full_copy(A)
    leftover = root / testing._BUCKET / (".reclaimed-" + "c" * 32 + "-synthetic")
    (leftover / "nested").mkdir(parents=True)
    (leftover / "nested" / "file.bin").write_bytes(b"SYNTHETIC leftover")
    assert not testing.reclaim_idle(root, abandoned.scope, abandoned.generation)  # recent: kept
    assert not leftover.exists() and abandoned.data_root.exists()
