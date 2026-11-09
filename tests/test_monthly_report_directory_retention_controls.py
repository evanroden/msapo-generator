"""Synthetic retention controls; no browser or remote writes.

Process races use spawned interpreters, unmodified product flock code, and a
scheduler-only wrapper around library._locked. The wrapper pauses AFTER the
real retention lock is acquired and reports BEFORE a contender tries it. No
lock, save, expiry, unlink, source, or parser implementation is substituted.
Injected library._now controls synthetic import timestamps, not the OS clock.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import fcntl
import json
import multiprocessing
import os
from pathlib import Path
import time
import traceback

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_retention as retention
from app import monthly_report_library as library
from app import monthly_report_testing as testing
from app.monthly_report_objects import object_path
from test_monthly_report_directory_batch import workbook, detail

NOW = datetime(2050, 6, 1, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=31)
TOKEN, OTHER = "a" * 32, "b" * 32
CONTRACT = "Synthetic Race Contract"
SHEET = "Synthetic Race Sites"
TIMEOUT = 15


def parsed(raw):
    book = directory.inspect_workbook(raw)
    sheet = next(s for s in book.sheets if s.name == SHEET)
    return directory.matrix_sites(book, sheet, *directory.suggest_matrix(sheet))


def confirmed_import(raw, revision, actor):
    return directory.save_directory(CONTRACT, parsed(raw), expected_revision=revision,
                                    actor=actor, confirmed=True, raw=raw,
                                    source_sha256=sha256(raw).hexdigest(), source_sheet=SHEET)


def records(root):
    result = {}
    for path in sorted(root.rglob("*")):
        assert not path.is_symlink()
        if path.is_file():
            assert path.stat().st_size < 1024 * 1024
            result[str(path.relative_to(root))] = sha256(path.read_bytes()).hexdigest()
    return result


def receipt(store, name, value):
    """Keep bounded synthetic observations only in this test's own tmp_path."""
    target = store["evidence"] / (name + ".json")
    with target.open("x") as stream:
        json.dump({"scope": "local injected-time and separate-process kernel-lock regression only",
                   **value}, stream, indent=2)


@pytest.fixture
def store(tmp_path, monkeypatch):
    evidence = tmp_path / "synthetic-retention-receipts"
    evidence.mkdir()
    base = tmp_path / "owned-disposable-root"
    base.mkdir()
    (base / ".owned-synthetic-closure").write_text("synthetic-only")
    monkeypatch.setenv("EPC_DATA_DIR", str(base))
    monkeypatch.setattr(library, "_now", lambda: OLD.isoformat())
    raw = workbook(((SHEET, detail()),))
    digest = sha256(raw).hexdigest()
    with testing.isolated(OTHER):
        confirmed_import(raw, 0, "Synthetic Other Namespace")
        other_root = library._root().parent
    with testing.isolated(TOKEN):
        original = confirmed_import(raw, 0, "Synthetic Original Import")
        root = library._root()
        directory.save_directory("Synthetic Untouched Contract", (), expected_revision=0,
            actor="Synthetic Untouched Editor", confirmed=True,
            contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Untouched Person"),))
        unrelated_raw = b"Synthetic unrelated report source, never customer data"
        report = root / "library/synthetic-unrelated-report/sources" / (sha256(unrelated_raw).hexdigest() + ".xlsx")
        library._atomic_write(report, unrelated_raw)
    # Ordinary-root data is a synthetic canary only, never an app configuration.
    ordinary = base / "ordinary-canary"
    ordinary.write_bytes(b"Synthetic ordinary root canary unchanged")
    return {"evidence": evidence, "base": base, "root": root, "other": other_root, "raw": raw, "digest": digest,
            "original": original, "report": report, "ordinary": ordinary}


def protected(store):
    root = store["root"]
    untouched_key = library._contract_directory("Synthetic Untouched Contract")
    own_key = library._contract_directory(CONTRACT)
    revision1 = root / "directory" / own_key / "history/00000001.json"
    references = {}
    for report in sorted((root / "library").rglob("*.xlsx")):
        pool = root / "objects" / report.stem[:2] / report.stem
        assert report.stat().st_ino == pool.stat().st_ino
        assert report.stat().st_dev == pool.stat().st_dev
        assert report.read_bytes() == pool.read_bytes()
        references[str(report.relative_to(root))] = {
            "device": report.stat().st_dev, "inode": report.stat().st_ino,
            "links": report.stat().st_nlink, "sha256": sha256(report.read_bytes()).hexdigest()}
    return {"other_namespace": records(store["other"]), "report_pool_references": references,
            "unrelated_directory": records(root / "directory" / untouched_key),
            "report_sources": records(root / "library"),
            "original_revision1": sha256(revision1.read_bytes()).hexdigest(),
            "ordinary_canary": sha256(store["ordinary"].read_bytes()).hexdigest()}


def worker(base, raw, operation, gate, channel):
    """A separate interpreter executes actual product save/expiry calls."""
    try:
        os.environ["EPC_DATA_DIR"] = base
        os.environ["OPENAI_API_KEY"] = ""
        os.environ["ANTHROPIC_API_KEY"] = ""
        os.environ["SMARTSHEET_API_MODE"] = "disabled"
        library._now = lambda: NOW.isoformat()
        original_lock = library._locked
        scheduled = False
        @contextmanager
        def scheduling_lock(path):
            nonlocal scheduled
            target = Path(path).name == "directory-sources" and not scheduled
            if target:
                scheduled = True
                channel.send({"stage": "attempting", "operation": operation, "pid": os.getpid(), "ns": time.monotonic_ns()})
            with original_lock(path):  # Actual product kernel flock, untouched.
                if target:
                    channel.send({"stage": "acquired", "operation": operation, "pid": os.getpid(), "ns": time.monotonic_ns()})
                    if not gate.wait(TIMEOUT):
                        raise TimeoutError("Synthetic scheduling gate timed out")
                yield
        library._locked = scheduling_lock
        with testing.isolated(TOKEN):
            if operation == "import":
                state = confirmed_import(raw, 1, "Synthetic Newest Confirmed Import")
                result = {"revision": state.revision, "actor": state.actor}
            elif operation == "expiry":
                result = {"erased": list(retention.expire(now=NOW))}
            else:
                raise AssertionError("Unknown local test operation")
        channel.send({"stage": "done", "operation": operation, "pid": os.getpid(), "result": result})
    except BaseException:
        channel.send({"stage": "error", "operation": operation, "traceback": traceback.format_exc()[-6000:]})
        raise
    finally:
        channel.close()


def receive(channel, expected):
    assert channel.poll(TIMEOUT), "Bounded child progress timeout"
    item = channel.recv()
    assert item["stage"] == expected, item
    return item


def kernel_probe(lock):
    """Independent parent descriptor must see kernel contention while held."""
    with lock.open("a+b") as stream:
        with pytest.raises(BlockingIOError):
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("first", ["import", "expiry"])
@pytest.mark.parametrize("shared_reference", [False, True])
def test_real_process_import_expiry_orders_preserve_latest_and_other_data(store, first, shared_reference):
    root, raw, digest = store["root"], store["raw"], store["digest"]
    source = root / "directory_sources" / (digest + ".xlsx")
    stamp = source.with_suffix(".imported")
    with testing.isolated(TOKEN):
        pool = object_path(source)
        if shared_reference:
            linked_report = root / "library/synthetic-shared-report/sources" / (digest + ".xlsx")
            library._atomic_write(linked_report, raw)
            assert source.stat().st_ino == pool.stat().st_ino == linked_report.stat().st_ino
    before = protected(store)
    ctx = multiprocessing.get_context("spawn")
    first_gate, second_gate = ctx.Event(), ctx.Event()
    second_gate.set()
    first_receive, first_send = ctx.Pipe(duplex=False)
    second_receive, second_send = ctx.Pipe(duplex=False)
    second = "expiry" if first == "import" else "import"
    processes = [ctx.Process(target=worker, args=(str(store["base"]), raw, first, first_gate, first_send)),
                 ctx.Process(target=worker, args=(str(store["base"]), raw, second, second_gate, second_send))]
    observations = []
    try:
        processes[0].start()
        first_send.close()
        observations.append(receive(first_receive, "attempting"))
        observations.append(receive(first_receive, "acquired"))
        lock = root / "directory_locks/directory-sources/.write-lock"
        kernel_probe(lock)
        processes[1].start()
        second_send.close()
        observations.append(receive(second_receive, "attempting"))
        assert not second_receive.poll(0.25), "Contender passed the held real retention lock"
        kernel_probe(lock)
        released_ns = time.monotonic_ns()
        first_gate.set()
        observations.append(receive(second_receive, "acquired"))
        assert observations[-1]["ns"] >= released_ns
        observations.append(receive(first_receive, "done"))
        observations.append(receive(second_receive, "done"))
        for process in processes:
            process.join(TIMEOUT)
            assert not process.is_alive() and process.exitcode == 0
        assert processes[0].pid != processes[1].pid != os.getpid()
    finally:
        first_gate.set()
        second_gate.set()
        for process in processes:
            if process.pid is not None:
                process.join(2)
                if process.is_alive():
                    process.terminate()
                    process.join(2)
                if process.is_alive():
                    process.kill()
                    process.join(2)
        for channel in (first_receive, second_receive, first_send, second_send):
            channel.close()
    expiry = next(x["result"] for x in observations if x["stage"] == "done" and x["operation"] == "expiry")
    assert expiry["erased"] == ([digest] if first == "expiry" else [])
    assert source.read_bytes() == pool.read_bytes() == raw
    assert stamp.read_text() == NOW.isoformat()
    assert source.stat().st_ino == pool.stat().st_ino
    assert source.stat().st_nlink == (3 if shared_reference else 2)
    with testing.isolated(TOKEN):
        newest = directory.load_directory(CONTRACT)
        assert newest.revision == 2 and newest.actor == "Synthetic Newest Confirmed Import"
        assert newest.sites == store["original"].sites
        assert directory.load_directory(CONTRACT, 1) == store["original"]
        assert retention.expire(now=NOW) == ()
    assert protected(store) == before
    receipt(store, "race-" + first + "-first-shared-" + str(shared_reference).lower(),
            {"ordering": first + "-first", "shared_target_report_link": shared_reference,
             "actual_kernel_contention_probes": 2, "observations": observations,
             "source_sha256": digest, "newest_revision": newest.revision,
             "protected_before_equals_after": True, "protected": before})


def test_exact_thirty_day_boundary_injected_now(store):
    source = store["root"] / "directory_sources" / (store["digest"] + ".xlsx")
    stamp = source.with_suffix(".imported")
    before = protected(store)
    with testing.isolated(TOKEN):
        imported_at = datetime.fromisoformat(stamp.read_text())
        cutoff = imported_at + timedelta(days=30)
        assert retention.expire(now=cutoff - timedelta(microseconds=1)) == ()
        assert source.read_bytes() == store["raw"] and stamp.exists()
        assert retention.expire(now=cutoff) == (store["digest"],)
        assert not source.exists() and not stamp.exists() and not object_path(source).exists()
        assert directory.load_directory(CONTRACT, 1) == store["original"]
    assert protected(store) == before
    receipt(store, "exact-30-day-boundary", {"retained_at_cutoff_minus_one_microsecond": True,
            "expired_at_exact_cutoff": True, "injected_cutoff": cutoff.isoformat(),
            "protected_before_equals_after": True})


def test_archive_restore_after_raw_expiry_preserves_history(store):
    before = protected(store)
    source = store["root"] / "directory_sources" / (store["digest"] + ".xlsx")
    with testing.isolated(TOKEN):
        assert retention.expire(now=NOW) == (store["digest"],)
        assert not source.exists() and not object_path(source).exists()
        archived = directory.archive_directory(CONTRACT, expected_revision=1,
            actor="Synthetic Archive After Expiry", confirmed=True)
        assert archived.archived and archived.revision == 2
        restored = directory.restore_directory(CONTRACT, 1, expected_revision=2,
            actor="Synthetic Restore After Expiry", confirmed=True)
        assert restored.revision == 3 and not restored.archived and restored.action == "restore:1"
        assert restored.sites == store["original"].sites
        assert restored.source_sha256 == store["digest"]
        assert directory.load_directory(CONTRACT, 1) == store["original"]
        assert directory.load_directory(CONTRACT, 2).archived
        assert directory.load_directory(CONTRACT) == restored
        assert not source.exists() and not source.with_suffix(".imported").exists() and not object_path(source).exists()
    assert protected(store) == before
    receipt(store, "archive-restore-after-raw-expiry", {"archived_revision": 2, "restored_revision": 3,
            "original_revision1_unchanged": True, "raw_not_recreated": True,
            "protected_before_equals_after": True})
