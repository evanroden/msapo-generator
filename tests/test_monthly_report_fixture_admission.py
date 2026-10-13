"""Synthetic admission tests; no reader, production report or live service."""
from contextlib import contextmanager
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import memory
from app import monthly_report_fixture_admission as admission
from app import monthly_report_fixture_vault as storage
from app import monthly_report_testing as testing
from app.monthly_report_fixture_runs import FixtureRunContext


@contextmanager
def run(token):
    with testing.isolated(token):
        root = memory._data_dir()
        yield FixtureRunContext(testing.scope(), testing.generation(), root)


def records(root):
    return json.loads((root / admission._BUCKET / "reservations.json").read_bytes())["reservations"]


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(admission.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=2 ** 30, f_frsize=1))
    return tmp_path


def test_reservation_is_durable_and_repeated_same_generation_cannot_spend_twice(root):
    with run("a" * 32) as context:
        with admission.admit_run_copy(context, 2048) as reserved:
            assert reserved == admission.CopyReservation(context.scope, context.generation, 2048)
            assert records(root) == [{"scope": context.scope, "generation": context.generation, "added_bytes": 2048}]
        with pytest.raises(storage.VaultIntegrityError, match="already reserved"):
            with admission.admit_run_copy(context, 1):
                pytest.fail("Repeated generation reached a new install")
    assert len(records(root)) == 1


def test_failed_stage_stays_reserved_until_reset_and_never_deletes_original_or_live_data(root):
    originals = root / "synthetic-shared-originals"
    originals.mkdir()
    original = originals / "source.docx"
    original.write_bytes(b"SYNTHETIC immutable original")
    live = root / "live-canary.txt"
    live.write_bytes(b"SYNTHETIC unrelated live canary")
    hashes = {path: sha256(path.read_bytes()).hexdigest() for path in (original, live)}
    with run("a" * 32) as first:
        with pytest.raises(OSError, match="synthetic failed stage"):
            with admission.admit_run_copy(first, admission.MAX_ACTIVE_COPY_BYTES):
                first.data_root.joinpath("partial-source.bin").write_bytes(b"SYNTHETIC partial")
                raise OSError("synthetic failed stage")
    with run("b" * 32) as other:
        with pytest.raises(storage.VaultQuotaExceeded):
            with admission.admit_run_copy(other, 1):
                pytest.fail("Failed copy reservation was silently released")
    with run("a" * 32):
        testing.reset(root)
    with run("b" * 32) as other:
        with admission.admit_run_copy(other, 4096):
            pass
        assert records(root) == [{"scope": other.scope, "generation": other.generation, "added_bytes": 4096}]
    assert {path: sha256(path.read_bytes()).hexdigest() for path in hashes} == hashes
    assert not first.data_root.exists()


def test_replaced_generation_reclaims_metadata_without_removing_current_run(root):
    with run("a" * 32) as old:
        with admission.admit_run_copy(old, admission.MAX_ACTIVE_COPY_BYTES):
            pass
        testing.reset(root)
    with run("a" * 32) as current:
        assert current.generation != old.generation
        canary = current.data_root / "current-work.txt"
        canary.write_text("SYNTHETIC new-generation work")
        with admission.admit_run_copy(current, 512):
            pass
        assert records(root)[0]["generation"] == current.generation
        assert canary.read_text() == "SYNTHETIC new-generation work"


def test_stale_or_unbound_context_cannot_create_global_metadata(root):
    with run("a" * 32) as context:
        testing.reset(root)
        with pytest.raises(OSError):
            with admission.admit_run_copy(context, 512):
                pytest.fail("Reset lease admitted")
    with pytest.raises(ValueError):
        with admission.admit_run_copy(context, 512):
            pytest.fail("Unbound lease admitted")
    assert not (root / admission._BUCKET).exists()


def test_reset_between_reservation_and_yield_blocks_install_and_retains_receipt(root, monkeypatch):
    original_save = admission._save

    def reset_after_receipt(directory, reservations):
        original_save(directory, reservations)
        testing.reset(root)

    monkeypatch.setattr(admission, "_save", reset_after_receipt)
    with run("a" * 32) as context:
        with pytest.raises(OSError):
            with admission.admit_run_copy(context, 512):
                pytest.fail("Reset during reservation reached install")
    assert records(root)[0]["generation"] == context.generation
    assert not context.data_root.exists()


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, admission.MAX_ACTIVE_COPY_BYTES + 1])
def test_invalid_admission_size_never_creates_a_reservation(root, amount):
    with run("a" * 32) as context:
        with pytest.raises(storage.VaultQuotaExceeded):
            with admission.admit_run_copy(context, amount):
                pytest.fail("Invalid count reached install")
    assert not (root / admission._BUCKET).exists()


def test_free_space_reserve_includes_the_new_copy_before_any_install(root, monkeypatch):
    monkeypatch.setattr(admission.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=admission.MIN_FREE_BYTES + 511, f_frsize=1))
    with run("a" * 32) as context:
        with pytest.raises(storage.VaultQuotaExceeded, match="256 MiB"):
            with admission.admit_run_copy(context, 512):
                pytest.fail("Insufficient disk headroom admitted")
    assert not (root / admission._BUCKET / "reservations.json").exists()


@pytest.mark.parametrize("target", ["registry", "index", "old_namespace"])
def test_linked_storage_fails_closed_and_never_reads_or_changes_target(root, target):
    with run("a" * 32) as initial:
        with admission.admit_run_copy(initial, 512):
            pass
    outside = root / "outside"
    outside.mkdir()
    canary = outside / "canary"
    canary.write_bytes(b"SYNTHETIC untouched")
    if target == "registry":
        existing = root / admission._BUCKET
        existing.rename(root / "retained-registry")
        existing.symlink_to(outside, target_is_directory=True)
    elif target == "index":
        index = root / admission._BUCKET / "reservations.json"
        index.rename(index.with_suffix(".retained"))
        # Keep only expected filenames so the nofollow open is the rejection.
        index.with_suffix(".retained").rename(root / "retained-index.json")
        index.symlink_to(canary)
    else:
        initial.data_root.rename(root / "retained-namespace")
        initial.data_root.symlink_to(outside, target_is_directory=True)
    with run("b" * 32) as other:
        with pytest.raises(OSError):
            with admission.admit_run_copy(other, 512):
                pytest.fail("Linked storage admitted")
    assert canary.read_bytes() == b"SYNTHETIC untouched"
    assert set(path.name for path in outside.iterdir()) == {"canary"}


def test_missing_marker_does_not_masquerade_as_reset_and_release_budget(root):
    with run("a" * 32) as initial:
        with admission.admit_run_copy(initial, admission.MAX_ACTIVE_COPY_BYTES):
            pass
    initial.data_root.joinpath(testing._SENTINEL).unlink()
    before = (root / admission._BUCKET / "reservations.json").read_bytes()
    with run("b" * 32) as other:
        with pytest.raises(storage.VaultIntegrityError, match="generation marker"):
            with admission.admit_run_copy(other, 1):
                pytest.fail("Unmarked existing data was treated as reset")
    assert (root / admission._BUCKET / "reservations.json").read_bytes() == before


def test_durable_metadata_failure_never_starts_the_copy(root, monkeypatch):
    def failure(*_args):
        raise OSError("synthetic metadata durability failure")

    monkeypatch.setattr(admission, "_save", failure)
    with run("a" * 32) as context:
        with pytest.raises(OSError, match="durability failure"):
            with admission.admit_run_copy(context, 512):
                pytest.fail("Copy began without durable reservation acknowledgement")
    assert not (root / admission._BUCKET / "reservations.json").exists()


def _competing_process(root, token, start, results):
    # Separate process/module instance, same real registry lock. Only synthetic
    # reservations are made; no 70 MiB data allocation or external reader.
    os.environ["EPC_DATA_DIR"] = str(root)
    admission.os.fstatvfs = lambda _: SimpleNamespace(f_bavail=2 ** 30, f_frsize=1)
    try:
        with run(token) as context:
            start.wait(10)
            with admission.admit_run_copy(context, 70 * 1024 * 1024):
                results.put("admitted")
    except storage.VaultQuotaExceeded:
        results.put("quota")
    except Exception as exc:
        results.put(type(exc).__name__)


def test_two_independent_processes_cannot_overrun_global_budget(root):
    # Establish the marked registry before concurrent requests, then leave its
    # valid stale metadata for normal next-admission reclamation.
    with run("c" * 32) as initial:
        with admission.admit_run_copy(initial, 512):
            pass
        testing.reset(root)
    processes = multiprocessing.get_context("spawn")
    start, results = processes.Event(), processes.Queue()
    children = [processes.Process(target=_competing_process, args=(root, token * 32, start, results))
                for token in ("a", "b")]
    try:
        for child in children:
            child.start()
        start.set()
        outcomes = sorted(results.get(timeout=20) for _ in children)
        for child in children:
            child.join(timeout=10)
        assert all(child.exitcode == 0 for child in children)
        assert outcomes == ["admitted", "quota"]
        assert sum(item["added_bytes"] for item in records(root)) == 70 * 1024 * 1024
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
