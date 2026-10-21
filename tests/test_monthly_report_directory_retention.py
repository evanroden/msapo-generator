"""Uploaded directory workbooks are kept 30 days after their latest import (Refs #291).

Revisions, history and the workbook fingerprint stay; only the raw file is
erased, and pooled bytes still linked elsewhere are kept. Synthetic data only.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path

import pytest

from app import monthly_report_directory as directory
from app import monthly_report_directory_retention as retention
from app import monthly_report_library as library
from app.monthly_report_objects import object_path
from test_monthly_report_directory_batch import prepared, save

NOW = datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))


def imported():
    raw, plan = prepared()
    save(plan, raw)
    return raw, hashlib.sha256(raw).hexdigest()


def link(digest):
    return library._root() / "directory_sources" / (digest + ".xlsx")


def stamp(digest):
    return library._root() / "directory_sources" / (digest + ".imported")


def test_a_confirmed_import_is_kept_30_days_then_erased_while_history_stays():
    raw, digest = imported()
    before = directory.load_directory("Synthetic Contract")
    assert link(digest).read_bytes() == raw and stamp(digest).exists()
    assert retention.expire(now=NOW + timedelta(days=29)) == ()
    assert link(digest).exists()
    assert retention.expire(now=NOW + timedelta(days=31)) == (digest,)
    assert not link(digest).exists() and not stamp(digest).exists()
    assert not object_path(link(digest)).exists()
    assert directory.load_directory("Synthetic Contract") == before
    assert directory.load_directory("Synthetic Contract", 1) == before
    assert before.source_sha256 == digest


def test_a_reimport_restarts_the_period():
    raw, digest = imported()
    stamp(digest).write_text((NOW - timedelta(days=40)).isoformat(), encoding="ascii")
    retention.store_import(digest, raw)
    assert retention.expire(now=NOW + timedelta(days=10)) == ()
    assert link(digest).exists()


def test_bytes_shared_with_another_upload_stay_available():
    raw, digest = imported()
    other = library._root() / "library" / "synthetic" / "sources" / (digest + ".xlsx")
    library._atomic_write(other, raw)
    assert retention.expire(now=NOW + timedelta(days=31)) == (digest,)
    assert not link(digest).exists()
    assert other.read_bytes() == raw and object_path(link(digest)).exists()


def test_workbooks_stored_before_the_policy_start_their_period_at_the_first_sweep():
    raw = b"synthetic legacy workbook bytes"
    digest = hashlib.sha256(raw).hexdigest()
    library._atomic_write(link(digest), raw)
    assert retention.expire(now=NOW) == ()
    assert link(digest).exists() and stamp(digest).exists()
    assert retention.expire(now=NOW + timedelta(days=31)) == (digest,)


def test_a_failed_erase_is_kept_and_retried(monkeypatch):
    _, digest = imported()
    target, original = link(digest), Path.unlink

    def refuse(self, missing_ok=False):
        if self == target:
            raise PermissionError("synthetic refusal")
        return original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)
    assert retention.expire(now=NOW + timedelta(days=31)) == ()
    assert target.exists() and stamp(digest).exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert retention.expire(now=NOW + timedelta(days=31)) == (digest,)


def test_an_unreadable_import_time_never_erases_the_workbook():
    _, digest = imported()
    stamp(digest).write_text("not a time", encoding="ascii")
    assert retention.expire(now=NOW + timedelta(days=365)) == ()
    assert link(digest).exists()


def last_swept(hours_ago):
    stamp_time = (NOW - timedelta(hours=hours_ago)).timestamp()
    os.utime(library._root() / "directory_sources" / ".last-sweep", (stamp_time, stamp_time))


def test_a_later_directory_save_applies_the_retention():
    _, digest = imported()
    stamp(digest).write_text((NOW - timedelta(days=31)).isoformat(), encoding="ascii")
    last_swept(2)
    directory.save_directory("Synthetic Other", (), expected_revision=0, actor="Synthetic Editor", confirmed=True,
                             contract_contacts=(directory.DirectoryContact("Administrator", "Synthetic Administrator"),))
    assert not link(digest).exists()
    assert directory.load_directory("Synthetic Contract").source_sha256 == digest


def test_an_import_time_without_a_zone_is_unreadable_not_a_crash():
    _, digest = imported()
    stamp(digest).write_text((NOW - timedelta(days=90)).replace(tzinfo=None).isoformat(), encoding="ascii")
    assert retention.expire(now=NOW) == ()
    assert link(digest).exists()


def test_a_pooled_copy_that_could_not_be_removed_is_retried(monkeypatch):
    raw, digest = imported()
    pooled, original = object_path(link(digest)), Path.unlink

    def refuse(self, missing_ok=False):
        if self == pooled:
            raise PermissionError("synthetic refusal")
        return original(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refuse)
    assert retention.expire(now=NOW + timedelta(days=31)) == ()
    assert not link(digest).exists() and stamp(digest).exists() and pooled.exists()
    monkeypatch.setattr(Path, "unlink", original)
    retention.expire(now=NOW + timedelta(days=31))
    assert not pooled.exists() and not stamp(digest).exists()


def test_routine_expiry_runs_at_most_hourly_and_from_directory_listings():
    _, digest = imported()  # the save itself ran a sweep
    stamp(digest).write_text((NOW - timedelta(days=31)).isoformat(), encoding="ascii")
    directory.directory_contracts()
    assert link(digest).exists()  # swept less than an hour ago
    last_swept(2)
    directory.directory_contracts()
    assert not link(digest).exists()
    assert retention.expire_quietly(force=True) == ()
