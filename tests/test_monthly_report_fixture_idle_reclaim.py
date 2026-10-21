"""Another browser's isolated test copy idle for 24 hours is reclaimed (Refs #292).

Owner policy: an abandoned copy may be discarded after a day without use; shared
originals and active or current-browser work never are. Synthetic data only.
"""
from contextlib import contextmanager
import contextvars
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


def full_copy(token, size=admission.MAX_ACTIVE_COPY_BYTES):
    with run(token) as context:
        with admission.admit_run_copy(context, size):
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


def test_an_interrupted_admission_restores_set_aside_copies_once(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    tombstone = testing.set_aside_idle(root, abandoned.scope, abandoned.generation)
    assert tombstone is not None and not abandoned.data_root.exists()  # crash before commit
    doomed = root / testing._BUCKET / (".discarding-" + "c" * 32 + "-synthetic")
    (doomed / "nested").mkdir(parents=True)
    calls = []
    recover = testing.recover_set_aside
    monkeypatch.setattr(testing, "recover_set_aside",
                        lambda base, reserved: calls.append(base) or recover(base, reserved))
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)  # observe recovery only
    with run(B) as other, pytest.raises(storage.VaultQuotaExceeded):
        with admission.admit_run_copy(other, 1):
            pytest.fail("The restored copy still holds its budget")
    # Once on entry and once to settle the failed admission, never per reservation.
    assert calls == [root, root] and abandoned.data_root.exists() and not doomed.exists()


def test_a_failed_admission_puts_set_aside_copies_back(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    monkeypatch.setattr(admission.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=1, f_frsize=1))
    with run(B) as other, pytest.raises(storage.VaultQuotaExceeded, match="free space"):
        with admission.admit_run_copy(other, 1024):
            pytest.fail("Admission without free space reached the install")
    assert (abandoned.data_root / "synthetic-copy.bin").exists()
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert [item["scope"] for item in reservations(root)] == [abandoned.scope]


def test_a_recent_marker_skips_the_full_scan(root, monkeypatch):
    recent = full_copy(A)
    age(recent.data_root, 25)
    os.utime(recent.data_root / testing._SENTINEL)  # just visited
    monkeypatch.setattr(testing, "_last_change", lambda target: pytest.fail("scanned a recently used namespace"))
    assert testing.set_aside_idle(root, recent.scope, recent.generation) is None


def test_activity_during_the_check_puts_the_namespace_back(root, monkeypatch):
    busy = full_copy(A)
    age(busy.data_root, 25)
    rename = os.rename

    def visit_then_rename(source, destination):
        if Path(source) == busy.data_root:
            (busy.data_root / "synthetic-new-edit.bin").write_bytes(b"SYNTHETIC edit during the check")
        rename(source, destination)

    monkeypatch.setattr(testing.os, "rename", visit_then_rename)
    assert not testing.reclaim_idle(root, busy.scope, busy.generation)
    assert (busy.data_root / "synthetic-new-edit.bin").exists()
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))


def test_an_unreadable_subtree_is_never_treated_as_idle(root, monkeypatch):
    hidden = full_copy(A)
    age(hidden.data_root, 25)
    (hidden.data_root / "synthetic-locked").mkdir()
    age(hidden.data_root, 25)
    scandir = os.scandir

    def unreadable(path):
        if Path(path).name == "synthetic-locked":
            raise PermissionError("synthetic unreadable folder")
        return scandir(path)

    monkeypatch.setattr(testing.os, "scandir", unreadable)
    assert not testing.reclaim_idle(root, hidden.scope, hidden.generation)
    assert hidden.data_root.exists()


def test_reclaim_waits_for_a_returning_request_recording_its_use(root, monkeypatch):
    returning = full_copy(A)
    age(returning.data_root, 25)
    outcome, utime = [], os.utime

    def reclaim_meanwhile(path, *args, **kwargs):
        if Path(path).name == testing._SENTINEL:  # the request is recording its use
            outcome.append(contextvars.Context().run(testing.reclaim_idle, root, returning.scope, returning.generation))
        return utime(path, *args, **kwargs)

    monkeypatch.setattr(testing.os, "utime", reclaim_meanwhile)
    with run(A) as context:
        assert context.data_root.exists()
    assert outcome == [False] and (returning.data_root / "synthetic-copy.bin").exists()


def test_a_request_that_finds_its_namespace_moved_fails_closed(root, monkeypatch):
    returning = full_copy(A)
    age(returning.data_root, 25)
    marker = testing._marker

    def reclaimed_right_after_the_check(sentinel, identity):
        generation = marker(sentinel, identity)
        contextvars.Context().run(testing.reclaim_idle, root, returning.scope, returning.generation)
        return generation

    monkeypatch.setattr(testing, "_marker", reclaimed_right_after_the_check)
    with testing.isolated(A), pytest.raises(OSError, match="reset during a running task"):
        memory._data_dir()


def test_a_scan_error_after_a_set_aside_puts_it_back(root):
    abandoned = full_copy(A, 1024)
    broken = full_copy("c" * 32, 1024)
    age(abandoned.data_root, 25)
    (broken.data_root / testing._SENTINEL).unlink()  # a later record cannot be checked
    with run(B) as other, pytest.raises(storage.VaultIntegrityError):
        with admission.admit_run_copy(other, 1):
            pytest.fail("Admission continued past an unreadable record")
    assert (abandoned.data_root / "synthetic-copy.bin").exists()
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))


def test_copies_released_by_a_committed_admission_are_never_restored(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    discard = testing.discard_set_aside
    monkeypatch.setattr(testing, "discard_set_aside", lambda tombstone: None)  # crash right after commit
    with run(B) as other:
        with admission.admit_run_copy(other, 4096):
            pass
    assert list((root / testing._BUCKET).glob(".reclaimed-*"))
    monkeypatch.setattr(testing, "discard_set_aside", discard)
    with run("c" * 32) as third:
        with admission.admit_run_copy(third, 1):
            pass
    assert not abandoned.data_root.exists()
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert [item["scope"] for item in reservations(root)] == [other.scope, third.scope]


def test_a_failed_check_after_the_move_puts_the_namespace_back(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    measure, rename = testing._last_change, os.rename

    def unmeasurable_once_moved(target):
        if target.name.startswith(testing._SET_ASIDE):
            raise PermissionError("synthetic unreadable copy")
        return measure(target)

    monkeypatch.setattr(testing, "_last_change", unmeasurable_once_moved)
    assert testing.set_aside_idle(root, abandoned.scope, abandoned.generation) is None
    assert (abandoned.data_root / "synthetic-copy.bin").exists()

    def refuse_putting_back(source, destination):
        if Path(destination) == abandoned.data_root:
            raise PermissionError("synthetic refusal")
        rename(source, destination)

    monkeypatch.setattr(testing.os, "rename", refuse_putting_back)
    with pytest.raises(PermissionError):  # explicit, not a silent "kept"
        testing.set_aside_idle(root, abandoned.scope, abandoned.generation)
    monkeypatch.setattr(testing.os, "rename", rename)
    testing.recover_set_aside(root, {(abandoned.scope, abandoned.generation)})
    assert (abandoned.data_root / "synthetic-copy.bin").exists()


def test_the_scan_stops_at_its_limit_inside_one_large_folder(root, monkeypatch):
    crowded = full_copy(A)
    for number in range(50):
        (crowded.data_root / f"synthetic-{number}.bin").write_bytes(b"")
    age(crowded.data_root, 25)
    read, scandir = [], os.scandir

    class Counting:
        def __init__(self, path):
            self.entries = scandir(path)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.entries.close()

        def __iter__(self):
            return self

        def __next__(self):
            entry = next(self.entries)
            read.append(entry.name)
            return entry

    monkeypatch.setattr(testing, "_MEASURE_LIMIT", 5)
    monkeypatch.setattr(testing.os, "scandir", Counting)
    assert testing._last_change(crowded.data_root) is None
    assert len(read) == 6


def test_a_save_error_after_the_index_changed_follows_the_index(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    replaced, replace, fsync = [], os.replace, os.fsync
    monkeypatch.setattr(admission.os, "replace", lambda *args, **kwargs: replaced.append(1) or replace(*args, **kwargs))

    def fail_after_replace(descriptor):
        if replaced:
            raise OSError("synthetic flush failure after the new index was installed")
        return fsync(descriptor)

    monkeypatch.setattr(admission.os, "fsync", fail_after_replace)
    with run(B) as other, pytest.raises(OSError, match="synthetic flush"):
        with admission.admit_run_copy(other, 4096):
            pytest.fail("A failed save reached the install")
    listed = [item["scope"] for item in reservations(root)]
    assert listed == [other.scope]  # the visible index released the idle copy
    assert not abandoned.data_root.exists()  # so it is not restored uncounted
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))


def test_a_run_reset_during_the_commit_keeps_the_idle_copies(root, monkeypatch):
    abandoned = full_copy(A)
    age(abandoned.data_root, 25)
    save, resets = admission._save, []

    def reset_once_after_commit(directory, records):
        save(directory, records)
        if not resets:
            resets.append(testing.reset(root))

    monkeypatch.setattr(admission, "_save", reset_once_after_commit)
    with run(B) as other, pytest.raises(OSError):
        with admission.admit_run_copy(other, 4096):
            pytest.fail("A reset run reached the install")
    assert (abandoned.data_root / "synthetic-copy.bin").exists()
    assert abandoned.scope in [item["scope"] for item in reservations(root)]
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))
