"""Real Starting-report copy failures and process death, synthetic roots only.

The generic admission API intentionally retains arbitrary partial reservations.
These tests cover the production opt-in transaction, without changing the
separate process-regression module recovered by PRs #674/#793.
"""
from contextlib import contextmanager
from hashlib import sha256
from io import BytesIO
import json
import multiprocessing
import os
from pathlib import Path
import time

from docx import Document
import pytest

from app import memory
from app import monthly_report_fixture_admission as admission
from app import monthly_report_fixture_runs as runs
from app import monthly_report_fixture_vault as vault
from app import monthly_report_testing as testing
from app.monthly_report_model import Facility, ReportProfile
from app.monthly_report_shared_fixtures import SharedFixtureLibrary
from app.monthly_report_start import report_key


def profile():
    sites = (Facility("synthetic-rollback-site", "Synthetic Rollback Site"),)
    return ReportProfile("Synthetic Rollback Contract", report_key(sites), "Synthetic Report", sites)


@contextmanager
def run(token):
    with testing.isolated(token * 32):
        root = memory._data_dir()
        yield runs.FixtureRunContext(testing.scope(), testing.generation(), root)


def age(root):
    stamp = time.time() - 25 * 3600
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        os.utime(path, (stamp, stamp), follow_symlinks=False)
    os.utime(root, (stamp, stamp))


def inventory(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def records(root):
    return json.loads((root / admission._BUCKET / admission._INDEX).read_text())["reservations"]


def pending(root):
    return root / admission._BUCKET / "pending-install.json"


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    selected = profile()
    metadata = vault.FixtureMetadata(
        friendly_name="Synthetic rollback fixture",
        source=vault.ReportIdentity(selected.contract, (selected.facilities[0].key,), "2026-09"),
        target=vault.ReportIdentity(selected.contract, (selected.facilities[0].key,), "2026-10"),
        scenario="AUTH01", owner_expectations="Preserve synthetic work on failed staging.",
        expected_content=(vault.ExpectedSection("Activity", includes=("Synthetic inspection",)),),
        confirmed_at="2026-11-06T09:00:00+00:00")
    doc = Document()
    doc.add_heading("Synthetic Rollback Site", 0)
    doc.add_paragraph("September 2026 Monthly Report")
    doc.add_heading("1 Monthly Activity Summary", 1)
    doc.add_paragraph("Synthetic inspection completed; synthetic follow-up remains open.")
    content = BytesIO()
    doc.save(content)
    library = SharedFixtureLibrary(tmp_path)
    receipt = library.upload(content.getvalue(), metadata)
    originals = inventory(tmp_path / "_enfra_shared_fixtures_v1")
    (tmp_path / "synthetic-live-canary").write_text("SYNTHETIC live data")
    with run("a"):
        old = runs.stage_fixture(library, receipt.fixture_id, "a" * 32, selected)
    age(old.context.data_root)
    yield tmp_path, library, receipt, old, originals
    assert inventory(tmp_path / "_enfra_shared_fixtures_v1") == originals
    assert (tmp_path / "synthetic-live-canary").read_text() == "SYNTHETIC live data"


def stage(case, token="b"):
    root, library, receipt, _old, _originals = case
    with run(token):
        return runs.stage_fixture(library, receipt.fixture_id, token * 32, profile())


@pytest.mark.parametrize("phase", ["before-index", "after-index", "source-write"])
def test_failed_actual_install_restores_idle_copy_and_releases_only_clean_new_reservation(case, monkeypatch, phase):
    root, library, receipt, old, _ = case
    before = records(root)
    save, write = admission._save, vault._write_file
    injected = []

    def failing_save(directory, selected):
        if not injected:
            injected.append(True)
            if phase == "after-index":
                save(directory, selected)
            raise OSError("synthetic index failure")
        save(directory, selected)

    def failing_write(directory, name, data):
        if name == "source.docx":
            injected.append(True)
            raise OSError("synthetic source failure")
        write(directory, name, data)

    with monkeypatch.context() as fault:
        if phase == "source-write":
            fault.setattr(vault, "_write_file", failing_write)
        else:
            fault.setattr(admission, "_save", failing_save)
        with pytest.raises(OSError, match="synthetic"):
            stage(case)
    assert injected and records(root) == before
    assert old.source_path.read_bytes() == library.download(receipt.fixture_id)
    assert not pending(root).exists()
    with run("b") as failed:
        assert not list(failed.data_root.rglob("source.docx"))
        assert not list(failed.data_root.rglob(".pending-*"))
    # No scoped reset is necessary for a clean failed installation.
    retried = stage(case)
    assert retried.source_path.read_bytes() == library.download(receipt.fixture_id)
    assert not old.context.data_root.exists()
    assert len(records(root)) == 1


def test_published_copy_followed_by_directory_fsync_error_remains_reserved(case, monkeypatch):
    root, library, receipt, old, _ = case
    fsync, failed = os.fsync, []

    def fail_after_publication(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if not failed and path.name == runs._STAGING and (path / runs._ENTRY).exists():
            failed.append(True)
            raise OSError("synthetic published-copy fsync failure")
        fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", fail_after_publication)
        with pytest.raises(OSError, match="published-copy fsync"):
            stage(case)
    assert failed and not old.context.data_root.exists() and not pending(root).exists()
    with run("b"):
        recovered = runs.read_run_fixture(library, "b" * 32)
        assert recovered.source_path.read_bytes() == library.download(receipt.fixture_id)
        assert records(root)[0]["scope"] == recovered.context.scope


def test_native_inspection_failure_retains_committed_diagnostic_copy(case, monkeypatch):
    root, library, receipt, old, _ = case
    with monkeypatch.context() as fault:
        fault.setattr(runs.starting_import, "inspect_docx",
                      lambda path: (_ for _ in ()).throw(ValueError("synthetic parser failure")))
        with pytest.raises(ValueError, match="parser failure"):
            stage(case)
    assert not old.context.data_root.exists() and not pending(root).exists()
    with run("b"):
        recovered = runs.read_run_fixture(library, "b" * 32)
        assert recovered.source_path.read_bytes() == library.download(receipt.fixture_id)
    assert len(records(root)) == 1


def _crashing_install(root, fixture_id, boundary):
    os.environ["EPC_DATA_DIR"] = str(root)
    library = SharedFixtureLibrary(Path(root))
    if boundary == "journal":
        original = admission._write_pending

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(23)

        admission._write_pending = crash
    elif boundary == "index":
        original = admission._save

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(23)

        admission._save = crash
    elif boundary == "partial":
        original = vault._write_file

        def crash(directory, name, data):
            if name == "source.docx":
                os._exit(23)
            original(directory, name, data)

        vault._write_file = crash
    elif boundary == "published":
        original = vault.FixtureVault._install

        def crash(*args, **kwargs):
            original(*args, **kwargs)
            os._exit(23)

        vault.FixtureVault._install = staticmethod(crash)
    else:
        raise AssertionError(boundary)
    with run("b"):
        runs.stage_fixture(library, fixture_id, "b" * 32, profile())


def crash(case, boundary):
    root, _, receipt, _, _ = case
    child = multiprocessing.get_context("spawn").Process(
        target=_crashing_install, args=(root, receipt.fixture_id, boundary))
    try:
        child.start()
        child.join(timeout=60)
        assert child.exitcode == 23
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
    assert pending(root).exists()


@pytest.mark.parametrize("boundary", ["journal", "index", "published"])
def test_real_process_exit_settles_by_actual_copy_commit(case, monkeypatch, boundary):
    root, library, receipt, old, _ = case
    crash(case, boundary)
    assert not old.context.data_root.exists()
    # Observe recovery without immediately selecting that restored idle copy
    # for a distinct, otherwise-authorized reclamation in this same admission.
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            (other.data_root / "synthetic-byte").write_bytes(b"S")
    assert not pending(root).exists()
    assert not list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert old.context.data_root.exists() == (boundary != "published")
    with run("b"):
        recovered = runs.read_run_fixture(library, "b" * 32)
        assert (recovered is not None) == (boundary == "published")
    assert len(records(root)) == 2
    assert sum(item["added_bytes"] for item in records(root)) <= admission.MAX_ACTIVE_COPY_BYTES


def test_partial_crash_fails_closed_until_its_browser_resets(case, monkeypatch):
    root, _, _, old, _ = case
    crash(case, "partial")
    before_index = records(root)
    tombstones = list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert len(tombstones) == 1
    with run("c") as other, pytest.raises(vault.VaultIntegrityError, match="scoped reset"):
        with admission.admit_run_copy(other, 1):
            pytest.fail("Ambiguous partial installation reached another write")
    assert records(root) == before_index and pending(root).exists() and tombstones[0].exists()
    with run("b"):
        testing.reset(root)
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert old.context.data_root.exists() and not pending(root).exists()
    assert len(records(root)) == 2


@pytest.mark.parametrize("corruption", ["journal", "index", "source"])
def test_ambiguous_recovery_never_discards_old_copy(case, corruption):
    root, _, _, _, _ = case
    crash(case, "published" if corruption == "source" else "journal")
    if corruption == "journal":
        value = json.loads(pending(root).read_text())
        value["schema"] = 2
        pending(root).write_text(json.dumps(value))
    elif corruption == "index":
        target = root / admission._BUCKET / admission._INDEX
        value = json.loads(target.read_text())
        value["reservations"] = []
        target.write_text(json.dumps(value))
    else:
        with run("b") as context:
            source = context.data_root / runs._STAGING / runs._ENTRY / "source.docx"
            source.write_bytes(b"SYNTHETIC unexpected source")
    tombstones = list((root / testing._BUCKET).glob(".reclaimed-*"))
    before = records(root)
    with run("c") as other, pytest.raises(vault.VaultIntegrityError):
        with admission.admit_run_copy(other, 1):
            pytest.fail("Unverified recovery reached a write")
    assert pending(root).exists() and records(root) == before and all(p.exists() for p in tombstones)


def test_failed_rollback_flush_retains_journal_and_prevents_blind_discard(case, monkeypatch):
    root, _, _, old, _ = case
    save, calls = admission._save, []

    def uncertain_save(directory, selected):
        calls.append(True)
        if len(calls) == 1:
            save(directory, selected)
        raise OSError("synthetic persistent reservation-write failure")

    with monkeypatch.context() as fault:
        fault.setattr(admission, "_save", uncertain_save)
        with pytest.raises(OSError, match="persistent reservation"):
            stage(case)
    assert pending(root).exists()
    assert list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert not old.context.data_root.exists()
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert old.context.data_root.exists() and not pending(root).exists()
    assert len(records(root)) == 2


def test_set_aside_directory_flush_failure_restores_before_index_can_change(case, monkeypatch):
    root, _, _, old, _ = case
    before, fsync = records(root), os.fsync

    def failing_bucket_sync(fd):
        if Path(os.readlink(f"/proc/self/fd/{fd}")).name == testing._BUCKET:
            raise OSError("synthetic set-aside directory flush failure")
        fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", failing_bucket_sync)
        with pytest.raises(OSError, match="set-aside directory"):
            stage(case)
    assert records(root) == before and old.source_path.exists() and not pending(root).exists()


def test_persistent_copy_publication_flush_failure_preserves_old_tombstone(case, monkeypatch):
    root, library, receipt, old, _ = case
    fsync = os.fsync

    def failing_publication_sync(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if path.name == runs._STAGING and (path / runs._ENTRY).exists():
            raise OSError("synthetic persistent publication flush failure")
        fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", failing_publication_sync)
        with pytest.raises(OSError, match="persistent publication"):
            stage(case)
    assert pending(root).exists() and not old.context.data_root.exists()
    tombstone, = (root / testing._BUCKET).glob(".reclaimed-*")
    assert next(tombstone.rglob("source.docx")).read_bytes() == library.download(receipt.fixture_id)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert not tombstone.exists() and not pending(root).exists()
    with run("b"):
        assert runs.read_run_fixture(library, "b" * 32) is not None


def test_incomplete_discard_keeps_journal_until_real_cleanup_succeeds(case, monkeypatch):
    root, _, _, old, _ = case
    with monkeypatch.context() as fault:
        fault.setattr(testing, "discard_set_aside", lambda path: None)
        with pytest.raises(OSError, match="could not settle"):
            stage(case)
    assert pending(root).exists() and not old.context.data_root.exists()
    assert list((root / testing._BUCKET).glob(".reclaimed-*"))
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert not pending(root).exists() and not list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert len(records(root)) == 2


def test_reset_after_reservation_restores_idle_copy_without_recreating_requester(case, monkeypatch):
    root, _, _, old, _ = case
    save, resets = admission._save, []
    before = records(root)

    def reset_once(directory, selected):
        save(directory, selected)
        if not resets:
            resets.append(True)
            testing.reset(root)

    with monkeypatch.context() as fault:
        fault.setattr(admission, "_save", reset_once)
        with run("b") as requesting, pytest.raises(OSError):
            runs.stage_fixture(case[1], case[2].fixture_id, "b" * 32, profile())
    assert records(root) == before and old.source_path.exists()
    assert not requesting.data_root.exists() and not pending(root).exists()


def test_unflushed_clean_absence_keeps_reservation_and_old_copy_protected(case, monkeypatch):
    root, _, _, old, _ = case
    write, fsync, failed = vault._write_file, os.fsync, []

    def failed_source(fd, name, data):
        if name == "source.docx":
            failed.append(True)
            raise OSError("synthetic clean source failure")
        write(fd, name, data)

    def unflushed_removal(fd):
        path = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if failed and path.name == runs._STAGING and not (path / runs._ENTRY).exists():
            raise OSError("synthetic negative-witness flush failure")
        fsync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(vault, "_write_file", failed_source)
        fault.setattr(os, "fsync", unflushed_removal)
        with pytest.raises(OSError, match="negative-witness"):
            stage(case)
    assert pending(root).exists() and not old.context.data_root.exists()
    assert list((root / testing._BUCKET).glob(".reclaimed-*"))
    assert len(records(root)) == 1 and records(root)[0]["scope"] != old.context.scope
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert old.context.data_root.exists() and not pending(root).exists()
    assert len(records(root)) == 2


def test_replaced_requesting_generation_is_preserved_during_rollback(case, monkeypatch):
    root, _, _, old, _ = case
    save, replaced = admission._save, []
    before = records(root)

    def replace_once(directory, selected):
        save(directory, selected)
        if not replaced:
            testing.reset(root)
            with run("b") as fresh:
                replaced.append(fresh)
                (fresh.data_root / "new-generation-canary").write_text("SYNTHETIC replacement")

    with monkeypatch.context() as fault:
        fault.setattr(admission, "_save", replace_once)
        with pytest.raises(OSError):
            stage(case)
    assert records(root) == before and old.source_path.exists() and not pending(root).exists()
    assert (replaced[0].data_root / "new-generation-canary").read_text() == "SYNTHETIC replacement"


@pytest.mark.parametrize("phase", ["before-journal", "before-index", "after-index", "source-write"])
def test_returning_reclaimed_browser_cannot_replace_a_copy_owed_back_on_failure(case, monkeypatch, phase):
    root, library, receipt, old, _ = case
    before, injected = records(root), []
    check, save, write = admission._check_admission, admission._save, vault._write_file

    def return_then_fail():
        injected.append(True)
        assert not old.context.data_root.exists()
        with pytest.raises(OSError, match="awaiting fixture cleanup recovery"):
            with run("a"):
                pytest.fail("A normal return silently replaced its counted set-aside generation")
        assert not old.context.data_root.exists()
        raise OSError("synthetic returning-browser admission failure")

    def fail_check(directory, reservation, retained):
        if not injected:
            return_then_fail()
        return check(directory, reservation, retained)

    def fail_save(directory, selected):
        if not injected:
            if phase == "after-index":
                save(directory, selected)
            return_then_fail()
        save(directory, selected)

    def fail_write(directory, name, data):
        if name == "source.docx" and not injected:
            return_then_fail()
        write(directory, name, data)

    with monkeypatch.context() as fault:
        if phase == "before-journal":
            fault.setattr(admission, "_check_admission", fail_check)
        elif phase == "source-write":
            fault.setattr(vault, "_write_file", fail_write)
        else:
            fault.setattr(admission, "_save", fail_save)
        with pytest.raises(OSError, match="synthetic returning-browser"):
            stage(case)
    assert injected and records(root) == before and not pending(root).exists()
    assert old.source_path.read_bytes() == library.download(receipt.fixture_id)
    with run("a") as returned:
        assert returned.generation == old.context.generation
    # The returned A is now active. B can retry without reclaiming A or reset.
    result = stage(case)
    assert result.source_path.exists() and old.source_path.exists()
    assert len(records(root)) == 2
    assert sum(item["added_bytes"] for item in records(root)) <= admission.MAX_ACTIVE_COPY_BYTES


def test_return_after_partial_crash_then_requester_reset_restores_original_generation(case, monkeypatch):
    root, library, receipt, old, _ = case
    crash(case, "partial")
    before = records(root)
    tombstone, = (root / testing._BUCKET).glob(".reclaimed-*")
    with pytest.raises(OSError, match="awaiting fixture cleanup recovery"):
        with run("a"):
            pytest.fail("Return during interrupted admission created a replacement")
    assert records(root) == before and pending(root).exists()
    assert next(tombstone.rglob("source.docx")).read_bytes() == library.download(receipt.fixture_id)
    with run("b"):
        testing.reset(root)  # explicit reset of B only, not A's hidden work
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    with run("a") as recovered:
        assert recovered.generation == old.context.generation
    assert old.source_path.read_bytes() == library.download(receipt.fixture_id)
    assert not pending(root).exists() and not tombstone.exists()
    assert len(records(root)) == 2


def test_legacy_recreated_generation_preserves_both_copies_and_counted_recovery(case, monkeypatch):
    root, library, receipt, old, _ = case
    before, save, injected = records(root), admission._save, []
    fresh_generation = "f" * 32

    def legacy_return_then_fail(directory, selected):
        if not injected:
            injected.append(True)
            # Model a pre-upgrade worker or already-existing collision. Current
            # data_dir must never do this, but recovery still cannot delete it.
            old.context.data_root.mkdir()
            (old.context.data_root / testing._SENTINEL).write_text(old.context.scope + "|" + fresh_generation)
            (old.context.data_root / "fresh-generation-canary").write_bytes(b"SYNTHETIC fresh work")
            raise OSError("synthetic pre-index failure after legacy return")
        save(directory, selected)

    with monkeypatch.context() as fault:
        fault.setattr(admission, "_save", legacy_return_then_fail)
        with pytest.raises(OSError, match="both copies were preserved"):
            stage(case)
    tombstone, = (root / testing._BUCKET).glob(".reclaimed-*")
    old_source = next(tombstone.rglob("source.docx"))
    assert old_source.read_bytes() == library.download(receipt.fixture_id)
    assert records(root) == before and pending(root).exists()
    for _ in range(2):
        with run("c") as other, pytest.raises(OSError, match="both copies were preserved"):
            with admission.admit_run_copy(other, 1):
                pytest.fail("An unsettled counted copy was pruned")
        assert old_source.exists() and records(root) == before and pending(root).exists()
    with run("a") as fresh:
        assert fresh.generation == fresh_generation
        assert (fresh.data_root / "fresh-generation-canary").read_bytes() == b"SYNTHETIC fresh work"
        # Explicitly discard this synthetic fresh generation, not automatic
        # recovery. Until this choice both generations must remain untouched.
        testing.reset(root)
    monkeypatch.setattr(testing, "set_aside_idle", lambda *args, **kwargs: None)
    with run("c") as other:
        with admission.admit_run_copy(other, 1):
            pass
    assert old.source_path.read_bytes() == library.download(receipt.fixture_id)
    assert not pending(root).exists() and not tombstone.exists()
    with run("a") as restored:
        assert restored.generation == old.context.generation


def _paused_failed_install(root, fixture_id, ready, release, outcome):
    os.environ["EPC_DATA_DIR"] = str(root)
    library = SharedFixtureLibrary(Path(root))
    original, paused = admission._save, []

    def pause_then_fail(directory, selected):
        if not paused:
            paused.append(True)
            ready.set()
            if not release.wait(30):
                raise TimeoutError("Synthetic cross-process test did not release admission")
            raise OSError("synthetic cross-process pre-index failure")
        original(directory, selected)

    admission._save = pause_then_fail
    try:
        with run("b"):
            runs.stage_fixture(library, fixture_id, "b" * 32, profile())
    except OSError as exc:
        outcome.put(str(exc))
    else:
        outcome.put("unexpected success")


def test_separate_returning_browser_process_cannot_replace_pending_copy(case):
    root, library, receipt, old, _ = case
    before = records(root)
    ctx = multiprocessing.get_context("spawn")
    ready, release, outcome = ctx.Event(), ctx.Event(), ctx.Queue()
    child = ctx.Process(target=_paused_failed_install,
                        args=(root, receipt.fixture_id, ready, release, outcome))
    try:
        child.start()
        assert ready.wait(30)
        with pytest.raises(OSError, match="awaiting fixture cleanup recovery"):
            with run("a"):
                pytest.fail("A separate returning process created a replacement")
        release.set()
        child.join(timeout=30)
        assert child.exitcode == 0
        assert outcome.get(timeout=5) == "synthetic cross-process pre-index failure"
    finally:
        release.set()
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
    assert records(root) == before and not pending(root).exists()
    assert old.source_path.read_bytes() == library.download(receipt.fixture_id)
    with run("a") as returned:
        assert returned.generation == old.context.generation
