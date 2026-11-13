"""Offline, synthetic-only cutover rehearsal. No Render/Azure endpoints are used."""
import hashlib
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

from scripts import azure_data_rehearsal as move


def _fixture(tmp_path):
    src = tmp_path / "synthetic-render"
    library = src / "monthly_reports" / "library" / "synthetic-contract" / "test-site"
    (library / "history").mkdir(parents=True)
    record = {"schema": 1, "revision": 1, "profile": {"contract": "Synthetic", "key": "test-site"},
              "versions": [], "current": [], "audit": []}
    payload = json.dumps(record, sort_keys=True).encode()
    (library / "manifest.json").write_bytes(payload)
    (library / "history" / "00000001.json").write_bytes(payload)
    imports = library / "imports"
    imports.mkdir()
    (imports / "original.pdf").write_bytes(b"%PDF-1.4\nSYNTHETIC ONLY\n%%EOF\n")
    pictures = src / "monthly_reports" / "objects"
    pictures.mkdir(parents=True)
    pooled = pictures / "cached.png"
    pooled.write_bytes(b"synthetic-pixel-bytes")
    (library / "cached.png").hardlink_to(pooled)
    active = src / "monthly_reports" / "active_work" / "synthetic-browser" / "synthetic-contract"
    active.mkdir(parents=True)
    (active / "working.json").write_text('{"schema":1,"kind":"browser_active_work_v1"}')
    for name, schema, values in (
        ("epc_memory.db", "CREATE TABLE contacts(id TEXT PRIMARY KEY, last_used TEXT)",
         ("synthetic-contact", "2026-11-11T00:00:00Z")),
        ("smartsheet_submissions.db", "CREATE TABLE submissions(submission_key TEXT PRIMARY KEY, status TEXT)",
         ("synthetic-submit-key", "pending")),
    ):
        with sqlite3.connect(src / name) as con:
            con.execute(schema)
            con.execute("INSERT INTO " + ("contacts" if name.startswith("epc") else "submissions") +
                        " VALUES (?,?)", values)
    freeze = tmp_path / "fence.json"
    freeze.write_text(json.dumps({"classification": "synthetic", "writers_fenced": True,
                                  "change_id": "SYNTHETIC-ONLY", "fenced_utc": "2026-11-11T18:00:00Z"}))
    return src, freeze


def test_snapshot_import_reopen_report_and_reconcile(tmp_path):
    src, freeze = _fixture(tmp_path)
    archive = tmp_path / "snapshot.tar.gz"
    move.snapshot(src, archive, freeze)
    target = tmp_path / "isolated-azure-candidate"
    first = move.import_posix(archive, target)
    assert first["import_state"] == "imported"
    assert first["database_tables"]["smartsheet_submissions.db"]["tables"]["submissions"] == 1
    assert first["history_relationships_checked"] == 1
    assert move.reconcile(archive, target)["status"] == "matched"
    assert move.import_posix(archive, target)["import_state"] == "already_imported"
    saved = target / "monthly_reports" / "library" / "synthetic-contract" / "test-site"
    assert json.loads((saved / "manifest.json").read_bytes())["revision"] == 1
    assert (saved / "imports" / "original.pdf").read_bytes() == (src / "monthly_reports" /
           "library" / "synthetic-contract" / "test-site" / "imports" / "original.pdf").read_bytes()
    assert os.path.samefile(saved / "cached.png", target / "monthly_reports" / "objects" / "cached.png")
    with sqlite3.connect(target / "smartsheet_submissions.db") as con:
        assert con.execute("SELECT submission_key,status FROM submissions").fetchone() == (
            "synthetic-submit-key", "pending")
    assert not [p for p in target.iterdir() if p.name.startswith(".msapo-")]


def test_snapshot_requires_a_real_external_write_fence_record(tmp_path):
    src, freeze = _fixture(tmp_path)
    freeze.write_text('{"classification":"synthetic","writers_fenced":false}')
    with pytest.raises(move.RehearsalError, match="attestation"):
        move.snapshot(src, tmp_path / "missing.tar.gz", freeze)


def test_source_changes_during_snapshot_are_rejected_and_archive_removed(tmp_path, monkeypatch):
    src, freeze = _fixture(tmp_path)
    original_export = move.legacy.export
    def racing_export(root, output):
        result = original_export(root, output)
        (root / "monthly_reports" / "new-record.json").write_text("changed during copy")
        return result
    monkeypatch.setattr(move.legacy, "export", racing_export)
    archive = tmp_path / "racy.tar.gz"
    with pytest.raises(move.RehearsalError, match="changed"):
        move.snapshot(src, archive, freeze)
    assert not archive.exists() and not Path(str(archive) + ".sha256").exists()


def test_corrupted_transfer_refused_with_no_target_changes(tmp_path):
    src, freeze = _fixture(tmp_path)
    archive = tmp_path / "good.tar.gz"
    move.snapshot(src, archive, freeze)
    archive.write_bytes(archive.read_bytes()[:-100])
    target = tmp_path / "candidate"
    with pytest.raises(move.RehearsalError):
        move.import_posix(archive, target)
    assert not target.exists()


def test_interrupted_import_rolls_back_stage_and_can_resume(tmp_path, monkeypatch):
    src, freeze = _fixture(tmp_path)
    archive = tmp_path / "good.tar.gz"
    move.snapshot(src, archive, freeze)
    target = tmp_path / "candidate"
    original_restore = move.legacy.restore
    def failing_restore(archive_path, stage):
        original_restore(archive_path, stage)
        raise OSError("synthetic interruption after staged restore")
    monkeypatch.setattr(move.legacy, "restore", failing_restore)
    with pytest.raises(OSError, match="interruption"):
        move.import_posix(archive, target)
    assert not target.exists()
    assert not list(tmp_path.glob(".candidate.msapo-stage-*"))
    monkeypatch.setattr(move.legacy, "restore", original_restore)
    assert move.import_posix(archive, target)["import_state"] == "imported"


def test_existing_accepted_target_never_overwritten(tmp_path):
    src, freeze = _fixture(tmp_path)
    archive = tmp_path / "good.tar.gz"
    move.snapshot(src, archive, freeze)
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "accepted-document.pdf").write_bytes(b"accepted data must survive")
    with pytest.raises(move.RehearsalError, match="Target files"):
        move.import_posix(archive, target)
    assert (target / "accepted-document.pdf").read_bytes() == b"accepted data must survive"


def test_changed_restored_file_is_a_reconciliation_failure(tmp_path):
    src, freeze = _fixture(tmp_path)
    archive = tmp_path / "good.tar.gz"
    move.snapshot(src, archive, freeze)
    target = tmp_path / "candidate"
    move.import_posix(archive, target)
    (target / "monthly_reports" / "objects" / "cached.png").write_bytes(b"tampered")
    with pytest.raises(move.RehearsalError, match="hash mismatch"):
        move.reconcile(archive, target)

