"""Moving EPC_DATA_DIR between hosts is complete, checked and never destructive."""
import gzip
import hashlib
import io
import json
import os
import sqlite3
import tarfile
from pathlib import Path

import pytest

from scripts import migrate_data
from scripts.migrate_data import MigrationError, export, restore, verify


def _tree(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.fixture
def data(tmp_path):
    """A synthetic data folder like /test1, with a WAL database mid-use."""
    root = tmp_path / "test1"
    (root / "monthly_reports" / "library" / "contract-a").mkdir(parents=True)
    (root / "monthly_reports" / "library" / "contract-a" / "manifest.json").write_text('{"revision": 3}')
    (root / "monthly_reports" / "objects").mkdir()
    (root / "monthly_reports" / "objects" / "ab12.png").write_bytes(os.urandom(300_000))
    (root / "monthly_reports" / "empty-but-kept").mkdir()
    (root / "lost+found").mkdir()
    old = root / "monthly_reports" / "library" / "contract-a" / "manifest.json"
    os.utime(old, (1_700_000_000, 1_700_000_000))
    os.chmod(old, 0o600)
    database = sqlite3.connect(root / "epc_memory.db")
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("CREATE TABLE learned (name TEXT)")
    database.executemany("INSERT INTO learned VALUES (?)", [("Synthetic %d" % n,) for n in range(500)])
    database.commit()
    # Kept open: the last rows live only in the -wal file, as on a running app.
    assert (root / "epc_memory.db-wal").stat().st_size > 0
    rollback = sqlite3.connect(root / "smartsheet_submissions.db")
    rollback.execute("CREATE TABLE submissions (key TEXT PRIMARY KEY)")
    rollback.execute("INSERT INTO submissions VALUES ('synthetic-1')")
    rollback.commit()
    rollback.close()
    yield root
    database.close()


def test_export_verify_restore_round_trip_keeps_everything(data, tmp_path):
    archive = tmp_path / "out" / "msapo-data.tar.gz"
    archive.parent.mkdir()
    result = export(data, archive)
    assert result["totals"]["databases"] == 2
    assert {item["path"] for item in result["skipped"]} == {"epc_memory.db-wal", "epc_memory.db-shm"}
    assert (archive.parent / "msapo-data.tar.gz.sha256").read_text().split()[0] == result["archive_sha256"]
    assert verify(archive)["totals"] == result["totals"]

    target = tmp_path / "azure-share"
    target.mkdir()
    (target / "lost+found").mkdir()
    restore(archive, target)
    # Plain files are byte-identical; the database copies are self-contained.
    plain = {k: v for k, v in _tree(data).items() if not k.startswith(("epc_memory.db", "smartsheet"))}
    assert {k: v for k, v in _tree(target).items() if k in plain} == plain
    assert (target / "monthly_reports" / "empty-but-kept").is_dir()
    assert not (target / "epc_memory.db-wal").exists()
    with sqlite3.connect(target / "epc_memory.db") as restored:
        assert restored.execute("SELECT count(*) FROM learned").fetchone()[0] == 500
        assert restored.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    with sqlite3.connect(target / "smartsheet_submissions.db") as restored:
        assert restored.execute("SELECT key FROM submissions").fetchall() == [("synthetic-1",)]
    kept = target / "monthly_reports" / "library" / "contract-a" / "manifest.json"
    assert int(kept.stat().st_mtime) == 1_700_000_000
    assert kept.stat().st_mode & 0o777 == 0o600
    assert not [p for p in target.iterdir() if p.name.startswith(".")]


def test_export_never_changes_the_source(data, tmp_path):
    before = {k: v for k, v in _tree(data).items() if not k.startswith("epc_memory.db")}
    export(data, tmp_path / "a.tar.gz")
    assert {k: v for k, v in _tree(data).items() if not k.startswith("epc_memory.db")} == before


def test_export_refuses_links_and_an_archive_inside_the_data(data, tmp_path):
    with pytest.raises(MigrationError, match="outside the data folder"):
        export(data, data / "inside.tar.gz")
    (data / "link").symlink_to(tmp_path)
    with pytest.raises(MigrationError, match="symbolic link"):
        export(data, tmp_path / "b.tar.gz")
    assert not (tmp_path / "b.tar.gz").exists() and not (tmp_path / "b.tar.gz.partial").exists()


def test_restore_refuses_a_target_in_use_unless_told_and_then_moves_it_aside(data, tmp_path):
    archive = tmp_path / "a.tar.gz"
    export(data, archive)
    target = tmp_path / "share"
    target.mkdir()
    (target / "epc_memory.db").write_bytes(b"created by a fresh app start")
    with pytest.raises(MigrationError, match="not empty"):
        restore(archive, target)
    assert (target / "epc_memory.db").read_bytes() == b"created by a fresh app start"
    result = restore(archive, target, replace_existing=True)
    stash = Path(result["moved_aside"])
    assert (stash / "epc_memory.db").read_bytes() == b"created by a fresh app start"
    with sqlite3.connect(target / "epc_memory.db") as restored:
        assert restored.execute("SELECT count(*) FROM learned").fetchone()[0] == 500


def _rewrite(archive: Path, change) -> None:
    """Rebuild the archive with ``change(name, data) -> (name, data) | None`` applied."""
    with tarfile.open(archive, "r:gz") as source:
        members = [(m, source.extractfile(m).read()) for m in source]
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as rebuilt:
        for member, payload in members:
            changed = change(member.name, payload)
            if changed is None:
                continue
            name, payload = changed
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(payload), member.mode
            rebuilt.addfile(info, io.BytesIO(payload))
    archive.write_bytes(buffer.getvalue())


@pytest.mark.parametrize("damage", ["flip", "drop", "extra", "traversal"])
def test_damaged_or_hostile_archives_are_refused_before_anything_moves(data, tmp_path, damage):
    archive = tmp_path / "a.tar.gz"
    export(data, archive)
    target_object = "data/monthly_reports/objects/ab12.png"

    def change(name, payload):
        if damage == "flip" and name == target_object:
            return name, payload[:-1] + bytes([payload[-1] ^ 1])
        if damage == "drop" and name == target_object:
            return None
        return name, payload
    _rewrite(archive, change)
    if damage in ("extra", "traversal"):
        bad = "data/unlisted.txt" if damage == "extra" else "data/../../escaped.txt"
        with tarfile.open(archive, "r:gz") as source:
            members = [(m, source.extractfile(m).read()) for m in source]
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as rebuilt:
            for member, payload in [(tarfile.TarInfo(bad), b"x")] + members:
                info = tarfile.TarInfo(member.name)
                info.size = len(payload)
                rebuilt.addfile(info, io.BytesIO(payload))
        archive.write_bytes(buffer.getvalue())
    with pytest.raises(MigrationError):
        verify(archive)
    target = tmp_path / "share"
    target.mkdir()
    with pytest.raises(MigrationError):
        restore(archive, target)
    assert list(target.iterdir()) == []
    assert not (tmp_path / "escaped.txt").exists()


def test_a_database_that_fails_its_integrity_check_is_not_restored(data, tmp_path):
    archive = tmp_path / "a.tar.gz"
    export(data, archive)
    with tarfile.open(archive, "r:gz") as source:
        manifest = json.loads(source.extractfile("MANIFEST.json").read())
    record = next(item for item in manifest["files"] if item["path"] == "smartsheet_submissions.db")
    corrupt = bytearray()

    def change(name, payload):
        nonlocal corrupt
        if name == "data/smartsheet_submissions.db":
            corrupt = bytearray(payload)
            corrupt[4096:4200] = b"\xff" * 104  # damage the table page, keep the header
            record.update(size=len(corrupt), sha256=hashlib.sha256(corrupt).hexdigest())
            return name, bytes(corrupt)
        if name == "MANIFEST.json":
            return name, json.dumps(manifest).encode()
        return name, payload
    _rewrite(archive, change)  # a damaged copy whose manifest matches it
    target = tmp_path / "share"
    target.mkdir()
    with pytest.raises(MigrationError, match="integrity check"):
        restore(archive, target)
    assert list(target.iterdir()) == []


def test_command_line_reports_and_exits_nonzero_on_a_stop(data, tmp_path, capsys):
    archive = tmp_path / "a.tar.gz"
    assert migrate_data.main(["export", "--source", str(data), "--output", str(archive)]) == 0
    assert "2 SQLite databases" in capsys.readouterr().out
    assert migrate_data.main(["verify", "--archive", str(archive)]) == 0
    assert migrate_data.main(["restore", "--archive", str(archive), "--target", str(data)]) == 2
    assert "not empty" in capsys.readouterr().err
    assert gzip.open(archive).read(1)  # a readable gzip stream


def test_a_folder_the_export_cannot_read_stops_it(data, tmp_path, monkeypatch):
    real_walk = os.walk

    def walk(top, **options):
        # What os.walk reports for a subfolder it may not list (mode 0700,
        # another owner); without a handler it would be silently skipped.
        options["onerror"](PermissionError(13, "Permission denied", str(Path(top) / "locked")))
        yield from real_walk(top, **options)
    monkeypatch.setattr(migrate_data.os, "walk", walk)
    with pytest.raises(MigrationError, match="cannot read: .*locked: Permission denied"):
        export(data, tmp_path / "a.tar.gz")
    assert not (tmp_path / "a.tar.gz").exists()


@pytest.mark.parametrize("bad", ["../../outside-target", "/abs-outside", "a/../../x", "./a", ""])
def test_manifest_folders_outside_the_target_are_refused_before_anything_is_made(data, tmp_path, bad):
    archive = tmp_path / "a.tar.gz"
    export(data, archive)

    def change(name, payload):
        if name == "MANIFEST.json":
            manifest = json.loads(payload)
            manifest["directories"].append(bad)
            return name, json.dumps(manifest).encode()
        return name, payload
    _rewrite(archive, change)
    with pytest.raises(MigrationError, match="Unsafe"):
        verify(archive)
    target = tmp_path / "share" / "test1"
    target.mkdir(parents=True)
    with pytest.raises(MigrationError, match="Unsafe"):
        restore(archive, target)
    assert list(target.iterdir()) == []
    assert not (tmp_path / "outside-target").exists() and not Path("/abs-outside").exists()
