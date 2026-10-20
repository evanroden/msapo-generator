"""Bound repeated batch work without weakening durable identity/CAS checks."""

from dataclasses import asdict, replace
import hashlib
import json
from time import perf_counter
import tracemalloc

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_batch as batch
from app import monthly_report_library as library
from app import monthly_report_testing as testing
from test_monthly_report_directory_batch import proposed, workbook


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def prepared(count):
    cells = {"A6": "Contract", "A9": "Executive Director", "A10": "Phone", "A11": "Email"}
    for number in range(count):
        column = directory.column_name(number + 2)
        cells.update({column + "6": f"Synthetic Batch {number:03d}",
                      column + "9": f"Synthetic Person {number:03d}",
                      column + "10": "202-555-0100", column + "11": "synthetic@example.invalid"})
    raw = workbook((("Active Contracts", cells),))
    return raw, batch.prepare_workbook(directory.inspect_workbook(raw))


def save(plan, raw):
    return batch.save_workbook_plan(plan, raw, actor="Synthetic Reviewer", confirmed=True, create=proposed(plan))


@pytest.mark.parametrize("count", [1, 10, 40])
@pytest.mark.parametrize("damaged", [False, True])
def test_batch_cost_and_durable_results(count, damaged, monkeypatch):
    raw, plan = prepared(count)
    broken_path = None
    if damaged:
        for entry in plan.entries:
            directory.save_directory(entry.contract, (), expected_revision=0,
                actor="Synthetic Reviewer", confirmed=True,
                contract_contacts=(replace(entry.contract_contacts[0], phone="", email=""),))
        plan = batch.prepare_workbook(directory.inspect_workbook(raw))
        broken = plan.entries[count // 2].contract
        broken_path = directory._path(broken) / "manifest.json"
        broken_path.write_bytes(b'{"schema":1,')
    counts = {"parses": 0, "manifest_reads": 0}
    inspect, read = directory.inspect_workbook, library._read

    def counted_inspect(value):
        counts["parses"] += 1
        return inspect(value)

    def counted_read(path):
        if path.name == "manifest.json" and path.parent.parent.name == "directory":
            counts["manifest_reads"] += 1
        return read(path)

    with monkeypatch.context() as measured:
        measured.setattr(directory, "inspect_workbook", counted_inspect)
        measured.setattr(library, "_read", counted_read)
        tracemalloc.start()
        try:
            started = perf_counter()
            result = save(plan, raw)
            elapsed = perf_counter() - started
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    print(json.dumps({"contracts": count, "damaged": damaged, "workbook_bytes": len(raw),
                      **counts, "saved": len(result.saved), "failed": len(result.failed),
                      "instrumented_seconds": round(elapsed, 4), "python_peak_bytes": peak}))
    assert len(result.saved) == count - int(damaged)
    assert len(result.failed) == int(damaged)
    assert not result.blocked
    for entry in plan.entries:
        if damaged and entry.contract == broken:
            assert broken_path.read_bytes() == b'{"schema":1,'
            assert len(list((broken_path.parent / "history").glob("*.json"))) == 1
            continue
        state = directory.load_directory(entry.contract)
        assert state.revision == 1 + int(damaged)
        assert state.contract_contacts == entry.contract_contacts
    assert counts["parses"] == int(bool(result.saved))
    assert counts["manifest_reads"] <= (7 if damaged else 3) * count


def test_noop_batch_does_not_reparse_or_create_history(monkeypatch):
    raw, plan = prepared(3)
    save(plan, raw)
    plan = batch.prepare_workbook(directory.inspect_workbook(raw))
    monkeypatch.setattr(directory, "inspect_workbook", lambda raw: pytest.fail("No-op reparsed workbook"))
    result = save(plan, raw)
    assert result.unchanged == tuple(entry.contract for entry in plan.entries)
    assert all(directory.load_directory(name).revision == 1 for name in result.unchanged)


def test_concurrent_identity_created_after_preview_is_not_overwritten(monkeypatch):
    raw, plan = prepared(3)
    original = directory.save_directory
    legacy = " synthetic   batch 001 "
    created = []

    def concurrent_save(contract, *args, **kwargs):
        result = original(contract, *args, **kwargs)
        if contract == plan.entries[0].contract:
            # Emulate an old-spelling writer appearing after the batch starts.
            state = replace(result, contract=legacy)
            path = library._root() / "directory" / library._contract_directory(legacy)
            library._atomic_write(path / "manifest.json", library._json({"schema": 1, **asdict(state)}))
            created.append((path, (path / "manifest.json").read_bytes()))
        return result

    monkeypatch.setattr(directory, "save_directory", concurrent_save)
    result = save(plan, raw)
    assert result.saved == (plan.entries[0].contract, plan.entries[2].contract)
    assert result.blocked[0][0] == plan.entries[1].contract
    assert created[0][0].joinpath("manifest.json").read_bytes() == created[0][1]
    canonical = library._root() / "directory" / library._contract_directory(plan.entries[1].contract)
    assert not canonical.exists()


def test_damage_after_cached_discovery_blocks_new_identity_but_keeps_sibling(monkeypatch):
    raw, plan = prepared(3)
    original = directory.save_directory
    damaged = []

    def concurrent_damage(contract, *args, **kwargs):
        result = original(contract, *args, **kwargs)
        if contract == plan.entries[1].contract:
            # The first record has already participated in cached discovery.
            path = directory._path(plan.entries[0].contract) / "manifest.json"
            library._atomic_write(path, b'{"schema":1,')
            damaged.append(path)
        return result

    monkeypatch.setattr(directory, "save_directory", concurrent_damage)
    result = save(plan, raw)
    assert result.saved == tuple(entry.contract for entry in plan.entries[:2])
    assert result.failed[0][0] == plan.entries[2].contract
    assert "Recover its contract identity" in result.failed[0][1]
    assert damaged[0].read_bytes() == b'{"schema":1,'
    assert directory.load_directory(plan.entries[1].contract).revision == 1
    assert directory.load_directory(plan.entries[2].contract) is None


def test_stale_revision_is_checked_under_lock_even_after_initial_read(monkeypatch):
    raw, plan = prepared(2)
    original = directory.save_directory
    advanced = []

    def concurrent_update(contract, *args, **kwargs):
        if contract == plan.entries[0].contract:
            advanced.append(original(contract, (), expected_revision=0,
                actor="Another Synthetic Reviewer", confirmed=True,
                contract_contacts=(directory.DirectoryContact("Manager", "Another Person"),)))
        return original(contract, *args, **kwargs)

    monkeypatch.setattr(directory, "save_directory", concurrent_update)
    result = save(plan, raw)
    assert result.blocked[0][0] == plan.entries[0].contract
    assert result.saved == (plan.entries[1].contract,)
    assert directory.load_directory(plan.entries[0].contract) == advanced[0]


def test_reset_during_batch_cannot_recreate_namespace(tmp_path, monkeypatch):
    original = directory.save_directory
    with testing.isolated("b" * 32):
        raw, plan = prepared(3)
        root = library._root()

        def reset_after_save(*args, **kwargs):
            result = original(*args, **kwargs)
            testing.reset(tmp_path)
            return result

        monkeypatch.setattr(directory, "save_directory", reset_after_save)
        result = save(plan, raw)
        assert not result.saved and len(result.failed) == 3
        assert not root.exists()
    assert not (tmp_path / "monthly_reports").exists()


def test_forged_plan_cannot_bypass_workbook_validation():
    raw, plan = prepared(1)
    malformed = b"not a workbook"
    plan = replace(plan, workbook_sha256=hashlib.sha256(malformed).hexdigest())
    result = save(plan, malformed)
    assert not result.saved and result.failed
    assert not directory.directory_contracts()


def test_reused_inspection_still_checks_each_source_sheet():
    raw, plan = prepared(3)
    entries = list(plan.entries)
    entries[1] = replace(entries[1], source_sheets=("Missing worksheet",))
    result = save(replace(plan, entries=tuple(entries)), raw)
    assert result.saved == (entries[0].contract, entries[2].contract)
    assert result.failed[0][0] == entries[1].contract
    assert "source no longer matches" in result.failed[0][1]
    assert directory.load_directory(entries[1].contract) is None


def test_discovery_cache_eviction_keeps_results_and_is_released(monkeypatch):
    # Exercise both caps without a large fixture; eviction may repeat reads,
    # but must never change the selected identity or saved contents.
    monkeypatch.setattr(directory, "_BATCH_RECORD_LIMIT", 2)
    monkeypatch.setattr(directory, "_BATCH_RECORD_BYTES", 2048)
    raw, plan = prepared(10)
    result = save(plan, raw)
    assert result.saved == tuple(entry.contract for entry in plan.entries)
    assert directory._BATCH_READS.get() is None
    assert all(directory.load_directory(entry.contract).contract_contacts == entry.contract_contacts
               for entry in plan.entries)
    with pytest.raises(RuntimeError):
        with directory._batch_reads(raw):
            raise RuntimeError("Synthetic interrupted batch")
    assert directory._BATCH_READS.get() is None
