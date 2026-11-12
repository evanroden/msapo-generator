"""Fenced, content-verified MSAPO filesystem/SQLite migration rehearsal.

Preparation is offline. This is the POSIX/SQLite adapter only; it MUST NOT be
used as a PostgreSQL/Azure SQL/Blob importer without the approved A03 contract.
The operator is responsible for stopping/fencing ALL writers before snapshot.
No connector, Render endpoint, Azure credential or network client is used.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

from scripts import migrate_data as legacy


class RehearsalError(Exception):
    """Safety check stopped the preparation."""


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_signature(root: Path) -> dict:
    """Spot concurrent writes in addition to (not instead of) external fencing."""
    if not root.is_dir() or root.is_symlink():
        raise RehearsalError("The source must be a real directory")
    result = {}
    for rel, path, kind in legacy._walk(root):
        st = path.lstat()
        result[rel] = (kind, st.st_size if kind == "file" else 0,
                       st.st_mtime_ns, st.st_ctime_ns, st.st_ino)
    return result


def _attestation(path: Path, classification: str) -> None:
    """Require an operator-signed change record; this file is NOT proof of a fence."""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RehearsalError("Missing or invalid write-freeze attestation") from exc
    if (not isinstance(obj, dict) or obj.get("classification") != classification
            or obj.get("writers_fenced") is not True
            or not isinstance(obj.get("change_id"), str) or not obj["change_id"].strip()
            or not isinstance(obj.get("fenced_utc"), str) or not obj["fenced_utc"].strip()):
        raise RehearsalError("Write-freeze attestation is incomplete or scope does not match")
    # Freeze ticket and operator identity deliberately never enter public reports.


def _safe_archive(archive: Path) -> dict:
    """Original archive validation plus structural and duplicate-member checks."""
    if not archive.is_file() or archive.is_symlink():
        raise RehearsalError("Archive missing or not a regular file")
    try:
        with tarfile.open(archive, "r:gz") as tar:
            names = [member.name for member in tar]
            if len(names) != len(set(names)) or names.count(legacy.MANIFEST) != 1:
                raise RehearsalError("Duplicate archive member")
            manifest = legacy._read_manifest(tar)
            files = manifest.get("files", [])
            directories = manifest.get("directories", [])
            links = manifest.get("links", [])
            if not all(isinstance(x, list) for x in (files, directories, links)):
                raise RehearsalError("Invalid archive manifest collection")
            all_paths = [rec["path"] for rec in files + directories + links]
            if len(all_paths) != len(set(all_paths)):
                raise RehearsalError("Duplicate logical archive path")
            if any(x.get("reason") != "SQLite companion; the database copy is self-contained"
                   for x in manifest.get("skipped", [])):
                raise RehearsalError("Archive omitted changing or missing files")
            if manifest.get("totals", {}).get("files") != len(files):
                raise RehearsalError("File count disagrees with manifest")
        return legacy.verify(archive)
    except (EOFError, OSError, KeyError, TypeError, ValueError, tarfile.TarError, legacy.MigrationError) as exc:
        raise RehearsalError("Invalid or corrupt migration archive") from exc


def snapshot(source: Path, archive: Path, freeze: Path, classification: str = "synthetic") -> dict:
    if classification not in ("synthetic", "authoritative"):
        raise RehearsalError("Unknown data classification")
    _attestation(freeze, classification)
    source = source.resolve(strict=True)
    archive = archive.absolute()
    if source == archive or source in archive.parents:
        raise RehearsalError("Archive must be outside source")
    before = _source_signature(source)
    try:
        manifest = legacy.export(source, archive)
        after = _source_signature(source)
        if before != after:
            raise RehearsalError("Source changed during snapshot; preserve freeze and retry")
        _safe_archive(archive)
        return manifest
    except BaseException:
        archive.unlink(missing_ok=True)
        Path(str(archive) + ".sha256").unlink(missing_ok=True)
        raise


def _expected_files(manifest: dict) -> dict:
    expected = {x["path"]: x for x in manifest["files"]}
    for link in manifest.get("links", []):
        expected[link["path"]] = expected[link["target"]]
    return expected


def _db_checks(path: Path) -> dict:
    """Content-free relational evidence, with schema and FK validation."""
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RehearsalError("SQLite integrity failure")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise RehearsalError("SQLite foreign-key relationship failure")
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        rows = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            rows[table] = int(con.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
        return {"user_version": con.execute("PRAGMA user_version").fetchone()[0],
                "schema_version": con.execute("PRAGMA schema_version").fetchone()[0],
                "tables": rows}
    finally:
        con.close()


def _inventory(root: Path, manifest: dict) -> dict:
    expected = _expected_files(manifest)
    actual = {rel: (path, kind) for rel, path, kind in legacy._walk(root)}
    file_paths = {rel for rel, (_, kind) in actual.items() if kind == "file"}
    if file_paths != set(expected):
        raise RehearsalError("Target files missing or unexpected (no data overwritten)")
    expected_dirs = {item["path"] for item in manifest["directories"]}
    if {rel for rel, (_, kind) in actual.items() if kind == "directory"} != expected_dirs:
        raise RehearsalError("Target directory relationship mismatch")
    for rel, record in expected.items():
        path = root / rel
        if _digest(path) != record["sha256"]:
            raise RehearsalError("Restored file hash mismatch")
    for link in manifest.get("links", []):
        if not os.path.samefile(root / link["path"], root / link["target"]):
            raise RehearsalError("Restored hard-link relationship mismatch")
    db = {}
    for record in manifest["files"]:
        if record["kind"] == "sqlite":
            db[record["path"]] = _db_checks(root / record["path"])
    # Check the current revision against its saved latest history where present.
    history_pairs = 0
    for rel in expected:
        path = Path(rel)
        if path.name != "manifest.json" or not rel.startswith("monthly_reports/"):
            continue
        if "/library/" not in "/" + rel and "/directory/" not in "/" + rel:
            continue
        try:
            value = json.loads((root / rel).read_text(encoding="utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise RehearsalError("Saved report manifest is invalid") from exc
        rev = value.get("revision")
        if not isinstance(rev, int) or rev < 0 or value.get("schema") != 1:
            raise RehearsalError("Unsupported saved report revision/schema")
        history = path.parent / "history" / f"{rev:08d}.json"
        if history.as_posix() in expected:
            if _digest(root / history) != _digest(root / rel):
                raise RehearsalError("Current manifest and latest history differ")
            history_pairs += 1
    by_category = Counter()
    for rel in expected:
        parts = Path(rel).parts
        if len(parts) >= 2 and parts[0] == "monthly_reports":
            by_category[parts[1]] += 1
        else:
            by_category["other_authoritative"] += 1
    return {"database_tables": db, "history_relationships_checked": history_pairs,
            "category_file_counts": dict(sorted(by_category.items()))}


def reconcile(archive: Path, target: Path) -> dict:
    manifest = _safe_archive(archive)
    if not target.is_dir() or target.is_symlink():
        raise RehearsalError("Restore target missing")
    inv = _inventory(target, manifest)
    return {"status": "matched", "format": manifest["format"],
            "archive_sha256": _digest(archive),
            "files": len(manifest["files"]), "hard_links": len(manifest.get("links", [])),
            "directories": len(manifest["directories"]), "bytes": manifest["totals"]["bytes"],
            **inv}


@contextlib.contextmanager
def _locked_import(target: Path):
    marker = target.parent / ("." + target.name + ".msapo-import.lock")
    fd = os.open(marker, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        with os.fdopen(fd, "r+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
    finally:
        pass  # Lock file is intentionally retained, separate from imported data.


def import_posix(archive: Path, target: Path) -> dict:
    """Atomic target-directory promotion: never replace any existing data."""
    manifest = _safe_archive(archive)
    target = target.absolute()
    if not target.parent.is_dir() or target.name in ("", ".", ".."):
        raise RehearsalError("Use a not-yet-created target under an existing directory")
    if target.is_symlink():
        raise RehearsalError("Refusing symbolic-link target")
    with _locked_import(target):
        if target.exists():
            # Idempotent retry only if *everything* is already equal.
            return {**reconcile(archive, target), "import_state": "already_imported"}
        stage = target.parent / ("." + target.name + ".msapo-stage-" + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        try:
            legacy.restore(archive, stage)
            result = reconcile(archive, stage)
            if target.exists():
                raise RehearsalError("Target appeared during import; refusing replacement")
            os.rename(stage, target)  # Same-parent atomic publish on supported POSIX mounts.
            return {**result, "import_state": "imported"}
        finally:
            if stage.exists():
                shutil.rmtree(stage)


def main(argv=None) -> int:
    cli = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = cli.add_subparsers(dest="command", required=True)
    exp = commands.add_parser("snapshot")
    exp.add_argument("--source", type=Path, required=True)
    exp.add_argument("--archive", type=Path, required=True)
    exp.add_argument("--freeze-attestation", type=Path, required=True)
    exp.add_argument("--classification", choices=("synthetic", "authoritative"), default="synthetic")
    imp = commands.add_parser("import-posix")
    imp.add_argument("--archive", type=Path, required=True)
    imp.add_argument("--target", type=Path, required=True)
    rec = commands.add_parser("reconcile")
    rec.add_argument("--archive", type=Path, required=True)
    rec.add_argument("--target", type=Path, required=True)
    ver = commands.add_parser("verify")
    ver.add_argument("--archive", type=Path, required=True)
    args = cli.parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot(args.source, args.archive, args.freeze_attestation, args.classification)
            result = {"status": "snapshot_verified", "archive_sha256": _digest(args.archive),
                      "files": result["totals"]["files"]}
        elif args.command == "import-posix":
            result = import_posix(args.archive, args.target)
        elif args.command == "reconcile":
            result = reconcile(args.archive, args.target)
        else:
            m = _safe_archive(args.archive)
            result = {"status": "verified", "archive_sha256": _digest(args.archive),
                      "files": m["totals"]["files"]}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (RehearsalError, legacy.MigrationError, OSError, sqlite3.DatabaseError) as exc:
        print("REJECTED: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

