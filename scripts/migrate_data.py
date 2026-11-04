"""Move the whole EPC_DATA_DIR between hosts with checked, all-or-nothing steps.

Run inside the app's container (the image's Python, standard library only):

    python scripts/migrate_data.py export  --source /test1 --output /tmp/msapo-data.tar.gz
    python scripts/migrate_data.py verify  --archive /tmp/msapo-data.tar.gz
    python scripts/migrate_data.py restore --archive /tmp/msapo-data.tar.gz --target /test1

export   Copies every file. SQLite databases are copied with SQLite's backup
         API, so each copy is consistent even while the app is in use, and is a
         single self-contained file (rollback journal, no -wal/-shm). Their
         companion -wal/-shm/-journal files are therefore not archived. Writes
         made after the export finishes are not included: export in a quiet
         window and switch users over right after.
verify   Checks every archived file against the manifest's size and SHA-256.
restore  Verifies again while extracting into a staging folder on the target,
         runs SQLite's integrity check on every database, then moves the
         restored entries into place. It refuses a non-empty target unless
         --replace-existing is given; existing entries are then moved aside
         into .pre-restore-<time>/, never deleted. Restart the app afterwards
         so it reopens the restored databases.

Export never changes the data, and nothing in the target is replaced until
every check has passed. Export needs free space outside the data folder for
the archive (roughly the folder's size before compression).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import stat
import sys
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

FORMAT = "msapo-data-archive-v1"
MANIFEST = "MANIFEST.json"
DATA = "data"
SQLITE_HEADER = b"SQLite format 3\x00"
SQLITE_COMPANIONS = ("-wal", "-shm", "-journal")
SKIPPED_ROOT_ENTRIES = {"lost+found"}
CHUNK = 1024 * 1024


class MigrationError(Exception):
    """A check failed; the message says what to do."""


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _stash_name(prefix: str) -> str:
    return prefix + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def _ignored_in_target(name: str) -> bool:
    return name in SKIPPED_ROOT_ENTRIES or name.startswith((".pre-restore-", ".msapo-restore-staging-"))


def _walk(source: Path):
    """Yield (relative POSIX path, absolute path, kind) in a stable order."""
    problems = []
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        if root_path == source:
            directories[:] = [d for d in directories if d not in SKIPPED_ROOT_ENTRIES]
        directories.sort()
        for name in sorted(directories):
            absolute = root_path / name
            if absolute.is_symlink():
                problems.append(f"symbolic link: {absolute}")
                continue
            yield absolute.relative_to(source).as_posix(), absolute, "directory"
        for name in sorted(files):
            absolute = root_path / name
            mode = absolute.lstat().st_mode
            if stat.S_ISLNK(mode):
                problems.append(f"symbolic link: {absolute}")
            elif not stat.S_ISREG(mode):
                problems.append(f"not a regular file: {absolute}")
            else:
                yield absolute.relative_to(source).as_posix(), absolute, "file"
    if problems:
        raise MigrationError("The data folder holds entries this tool will not copy:\n  "
                             + "\n  ".join(problems))


def _add_bytes(archive: tarfile.TarFile, name: str, stream, mode: int, mtime: float, digest_into: dict) -> None:
    """Spool ``stream`` while hashing, so the manifest describes exactly what was archived."""
    digest = hashlib.sha256()
    with tempfile.SpooledTemporaryFile(max_size=64 * CHUNK) as spool:
        size = 0
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            spool.write(chunk)
            size += len(chunk)
        spool.seek(0)
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = size, mode, int(mtime)
        archive.addfile(info, spool)
    digest_into.update(size=size, sha256=digest.hexdigest())


def _open_for_reading(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
        connection.execute("PRAGMA schema_version").fetchone()
        return connection
    except sqlite3.OperationalError:
        # A WAL database cannot be opened read-only while its -shm file is
        # absent (the app is stopped). A normal open only lets SQLite tidy its
        # own log, which it does routinely; no data changes.
        return sqlite3.connect(path, timeout=30)


def _check_integrity(connection: sqlite3.Connection, name) -> None:
    """SQLite reports damage either as a result row or, when badly damaged, as an error."""
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as error:
        result = str(error)
    if result != "ok":
        raise MigrationError(f"SQLite integrity check failed for {name}: {result}")


def _backup_sqlite(path: Path, workdir: Path) -> Path:
    copy = workdir / "copy.sqlite"
    copy.unlink(missing_ok=True)
    source = _open_for_reading(path)
    target = sqlite3.connect(copy)
    try:
        source.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")
        _check_integrity(target, path)
    except sqlite3.DatabaseError as error:
        raise MigrationError(f"Could not copy the SQLite database {path}: {error}") from None
    finally:
        target.close()
        source.close()
    return copy


def export(source: Path, output: Path) -> dict:
    source = source.resolve()
    output = output.resolve()
    if not source.is_dir():
        raise MigrationError(f"Source folder not found: {source}")
    if output == source or source in output.parents:
        raise MigrationError("Write the archive outside the data folder, for example under /tmp.")
    if output.exists():
        raise MigrationError(f"{output} already exists; choose a new name.")
    entries = list(_walk(source))
    databases = {rel for rel, absolute, kind in entries if kind == "file" and _is_sqlite(absolute)}
    companions = {db + suffix for db in databases for suffix in SQLITE_COMPANIONS}
    manifest = {"format": FORMAT, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": str(source), "directories": [], "files": [], "skipped": []}
    partial = output.with_name(output.name + ".partial")
    try:
        with tempfile.TemporaryDirectory() as workdir, tarfile.open(partial, "w:gz") as archive:
            for rel, absolute, kind in entries:
                if kind == "directory":
                    manifest["directories"].append(rel)
                    continue
                if rel in companions:
                    manifest["skipped"].append({"path": rel, "reason": "SQLite companion; the database copy is self-contained"})
                    continue
                info = absolute.stat()
                record = {"path": rel, "mode": stat.S_IMODE(info.st_mode), "mtime": info.st_mtime,
                          "kind": "sqlite" if rel in databases else "file"}
                if rel in databases:
                    copy = _backup_sqlite(absolute, Path(workdir))
                    with copy.open("rb") as stream:
                        _add_bytes(archive, f"{DATA}/{rel}", stream, record["mode"], info.st_mtime, record)
                else:
                    try:
                        stream = absolute.open("rb")
                    except FileNotFoundError:
                        # Removed by the app (retention, temporary output) after the walk.
                        manifest["skipped"].append({"path": rel, "reason": "removed during export"})
                        continue
                    with stream:
                        _add_bytes(archive, f"{DATA}/{rel}", stream, record["mode"], info.st_mtime, record)
                manifest["files"].append(record)
            manifest["totals"] = {"files": len(manifest["files"]), "databases": len(databases),
                                  "directories": len(manifest["directories"]),
                                  "bytes": sum(item["size"] for item in manifest["files"])}
            encoded = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST)
            info.size, info.mode, info.mtime = len(encoded), 0o600, int(time.time())
            archive.addfile(info, io.BytesIO(encoded))
        os.replace(partial, output)
    finally:
        partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with output.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    Path(str(output) + ".sha256").write_text(f"{digest.hexdigest()}  {output.name}\n", encoding="ascii")
    manifest["archive_sha256"] = digest.hexdigest()
    return manifest


def _safe_member(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != DATA or len(path.parts) < 2:
        raise MigrationError(f"Unsafe or unexpected archive entry: {name!r}")
    return PurePosixPath(*path.parts[1:]).as_posix()


def _read_manifest(archive: tarfile.TarFile) -> dict:
    try:
        member = archive.getmember(MANIFEST)
    except KeyError:
        raise MigrationError("The archive has no manifest; it was not made by this tool.") from None
    manifest = json.loads(archive.extractfile(member).read())
    if manifest.get("format") != FORMAT:
        raise MigrationError(f"Unknown archive format {manifest.get('format')!r}.")
    return manifest


def _members(archive_path: Path, write_into: Path | None = None) -> dict:
    """Check every member against the manifest; optionally write files under ``write_into``."""
    with tarfile.open(archive_path, "r:gz") as archive:
        manifest = _read_manifest(archive)
        expected = {item["path"]: item for item in manifest["files"]}
        seen = set()
        for member in archive:
            if member.name == MANIFEST:
                continue
            rel = _safe_member(member.name)
            if not member.isfile():
                raise MigrationError(f"Archive entry is not a regular file: {member.name!r}")
            record = expected.get(rel)
            if record is None or rel in seen:
                raise MigrationError(f"Archive entry not described by the manifest: {rel}")
            seen.add(rel)
            digest, size = hashlib.sha256(), 0
            stream = archive.extractfile(member)
            destination = None
            if write_into is not None:
                destination = write_into / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                handle = open(destination, "xb")
            try:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    if destination is not None:
                        handle.write(chunk)
            finally:
                if destination is not None:
                    handle.close()
            if size != record["size"] or digest.hexdigest() != record["sha256"]:
                raise MigrationError(f"{rel} does not match the manifest (damaged in transfer?).")
            if destination is not None:
                os.chmod(destination, record["mode"] & 0o777)
                # Retention and clean-up rules judge age by modification time.
                os.utime(destination, (record["mtime"], record["mtime"]))
        missing = sorted(set(expected) - seen)
        if missing:
            raise MigrationError("Files listed in the manifest are missing: " + ", ".join(missing[:10]))
    return manifest


def verify(archive_path: Path) -> dict:
    return _members(archive_path)


def restore(archive_path: Path, target: Path, *, replace_existing: bool = False) -> dict:
    target = target.resolve()
    if not target.is_dir():
        raise MigrationError(f"Target folder not found: {target} (mount the share first).")
    existing = sorted(entry.name for entry in target.iterdir() if not _ignored_in_target(entry.name))
    if existing and not replace_existing:
        raise MigrationError("The target folder is not empty (" + ", ".join(existing[:10])
                             + "). Stop the app and pass --replace-existing to move those entries aside.")
    staging = target / _stash_name(".msapo-restore-staging-")
    staging.mkdir()
    try:
        manifest = _members(archive_path, write_into=staging)
        for rel in manifest["directories"]:
            (staging / rel).mkdir(parents=True, exist_ok=True)
        for item in manifest["files"]:
            if item["kind"] != "sqlite":
                continue
            connection = sqlite3.connect((staging / item["path"]).as_uri() + "?mode=ro", uri=True)
            try:
                _check_integrity(connection, item["path"])
            finally:
                connection.close()
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    stash = None
    if existing:
        stash = target / _stash_name(".pre-restore-")
        stash.mkdir()
        for name in existing:
            os.replace(target / name, stash / name)
    for entry in sorted(staging.iterdir()):
        os.replace(entry, target / entry.name)
    staging.rmdir()
    manifest["moved_aside"] = str(stash) if stash else ""
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    exporting = commands.add_parser("export", help="archive the data folder")
    exporting.add_argument("--source", type=Path, required=True)
    exporting.add_argument("--output", type=Path, required=True)
    verifying = commands.add_parser("verify", help="check an archive against its manifest")
    verifying.add_argument("--archive", type=Path, required=True)
    restoring = commands.add_parser("restore", help="restore an archive into an empty data folder")
    restoring.add_argument("--archive", type=Path, required=True)
    restoring.add_argument("--target", type=Path, required=True)
    restoring.add_argument("--replace-existing", action="store_true",
                           help="move existing entries aside into .pre-restore-<time>/ first")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            result = export(args.source, args.output)
            print(f"Exported {result['totals']['files']} files ({result['totals']['databases']} SQLite databases, "
                  f"{result['totals']['bytes']:,} bytes) to {args.output.resolve()}")
            print(f"Archive SHA-256: {result['archive_sha256']} (also in {args.output.resolve()}.sha256)")
            if result["skipped"]:
                print(f"Not copied: {len(result['skipped'])} entries (SQLite companions, or files removed during export).")
        elif args.command == "verify":
            result = verify(args.archive)
            print(f"Archive OK: {result['totals']['files']} files match the manifest "
                  f"(exported {result['created_utc']} from {result['source']}).")
        else:
            result = restore(args.archive, args.target, replace_existing=args.replace_existing)
            print(f"Restored {result['totals']['files']} files ({result['totals']['databases']} SQLite databases "
                  f"passed their integrity check) into {args.target.resolve()}.")
            if result["moved_aside"]:
                print(f"Previous contents were moved to {result['moved_aside']}.")
            print("Restart the app now so it reopens the restored databases.")
    except MigrationError as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
