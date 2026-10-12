"""Race-specific QA reset regression from failed live run 38254617731.

The old code could remove the test namespace, then claim the fixture was kept
if a volatile render-jobs child vanished during rmtree. Only disappearing
children are benign; generation, ownership and live-root guards stay strict.
"""
import errno
import inspect
import os
import shutil

import pytest

from app import monthly_report_library as library
from app import monthly_report_qa_fixture as fixture
from app import monthly_report_testing as qa
from app import monthly_report_testing_ui as ui


COOKIE = "c" * 32


def test_disappearing_render_job_child_does_not_abort_scoped_reset(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = fixture.profile()
    live = library.save_profile(profile, expected_revision=0,
                                actor="Invented live marker", confirmed=True)
    with qa.isolated(COOKIE):
        fixture.prepare("prefill")
        target = qa._location(tmp_path, qa.scope())
        volatile = target / "render-jobs" / "transient.tmp"
        volatile.parent.mkdir(parents=True, exist_ok=True)
        volatile.write_text("Invented temporary converter state")
        old_generation = qa.generation()
        original_unlink = os.unlink
        vanished = []

        def transient_disappears(name, *, dir_fd=None):
            if str(name) == "transient.tmp" and not vanished:
                original_unlink(name, dir_fd=dir_fd)
                vanished.append(True)
                raise FileNotFoundError(errno.ENOENT, "Transient file vanished", str(name))
            return original_unlink(name, dir_fd=dir_fd)

        with monkeypatch.context() as scoped:
            scoped.setattr(os, "unlink", transient_disappears)
            qa.reset(tmp_path)
        assert vanished, "The injected disappearing-child race must be exercised."
        assert not target.exists()
        with pytest.raises(OSError, match="reset"):
            library.load_snapshot(profile.contract, profile.key, fixture.PERIOD)
    with qa.isolated(COOKIE):
        assert qa.generation() is None
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None
        assert qa.generation() and qa.generation() != old_generation
        replay = fixture.prepare("replay")
        assert len(replay.sources) == 2
        assert all(fixture.compare(replay)["checks"].values())
    assert library.load_profile(profile.contract, profile.key) == live
    assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None


@pytest.mark.parametrize("error,relative", [
    (PermissionError("A private QA child cannot be removed."), "render-jobs/transient.tmp"),
    (FileNotFoundError(errno.ENOENT, "Missing test root."), "."),
])
def test_reset_refuses_real_errors_or_missing_root(monkeypatch, tmp_path, error, relative):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE):
        fixture.prepare("prefill")
        target = qa._location(tmp_path, qa.scope())

        def bad_rmtree(path, *, onexc):
            selected = target if relative == "." else target / relative
            onexc(os.unlink, str(selected), error)

        with monkeypatch.context() as scoped:
            scoped.setattr(shutil, "rmtree", bad_rmtree)
            with pytest.raises(type(error)):
                qa.reset(tmp_path)
        assert target.exists()
        assert library.load_snapshot(fixture.CONTRACT, fixture.profile().key,
                                     fixture.PERIOD) is not None


def test_ui_does_not_delete_storage_before_cache_or_claim_retention_on_error():
    source = inspect.getsource(ui.render)
    assert source.index("STORE.reset_scope()") < source.index("testing.reset(live_storage_root)")
    # The pre-reset active-job refusal may correctly say work was kept;
    # only the obsolete AFTER-deletion failure claim is disallowed.
    assert "Test reset was stopped; the current fixture was kept:" not in source
    assert "Isolated reset could not be confirmed" in source


@pytest.mark.parametrize("error", [
    FileNotFoundError(errno.ENOENT, "A last cleanup entry disappeared."),
    PermissionError(errno.EACCES, "A synthetic late cleanup error."),
])
def test_late_cleanup_error_after_exact_root_removal_is_confirmed(
        monkeypatch, tmp_path, error):
    """A removed test must not be reported as retained after rmtree finishes."""
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    profile = fixture.profile()
    # An unrelated live report with the same invented identity is immutable.
    live = library.save_profile(profile, expected_revision=0,
                                actor="Invented live author", confirmed=True)
    with qa.isolated(COOKIE):
        fixture.prepare("prefill")
        previous = qa.generation()
        target = qa._location(tmp_path, qa.scope())
        original_rmtree = shutil.rmtree

        def remove_then_raise(path, *, onexc):
            original_rmtree(path, onexc=onexc)
            assert not target.exists()
            raise type(error)(error.errno, str(error), str(path))

        with monkeypatch.context() as scoped:
            scoped.setattr(shutil, "rmtree", remove_then_raise)
            qa.reset(tmp_path)
        assert not target.exists()
        assert not target.is_symlink()
        # Same-generation and copied worker contexts remain invalidated.
        with pytest.raises(OSError, match="reset"):
            library.load_snapshot(profile.contract, profile.key, fixture.PERIOD)
    with qa.isolated(COOKIE):
        assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None
        assert qa.generation() and qa.generation() != previous
        assert all(fixture.compare(fixture.prepare("replay"))["checks"].values())
    assert library.load_profile(profile.contract, profile.key) == live
    assert library.load_snapshot(profile.contract, profile.key, fixture.PERIOD) is None


def test_late_error_with_partial_qa_directory_remains_hard_failure(
        monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    with qa.isolated(COOKIE):
        fixture.prepare("prefill")
        target = qa._location(tmp_path, qa.scope())
        scratch = target / "synthetic-cleanup.tmp"
        scratch.write_text("invented transient")
        original_rmtree = shutil.rmtree

        def remove_one_child_then_fail(path, *, onexc):
            scratch.unlink()
            raise PermissionError(errno.EACCES, "Still has files", str(path))

        with monkeypatch.context() as scoped:
            scoped.setattr(shutil, "rmtree", remove_one_child_then_fail)
            with pytest.raises(PermissionError):
                qa.reset(tmp_path)
        assert target.exists()
        assert not scratch.exists()
        assert library.load_snapshot(
            fixture.CONTRACT, fixture.profile().key, fixture.PERIOD) is not None
        # Retry stays possible after a genuine, incomplete cleanup.
        original_rmtree(target)
        assert not target.exists()
