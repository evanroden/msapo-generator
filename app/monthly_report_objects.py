"""Immutable, global monthly-report objects with compatible per-profile links."""

from contextlib import contextmanager
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import time

from app.memory import _data_dir


_NAME = re.compile(r"([0-9a-f]{64})\.(png|jpg|jpeg|pdf|docx|xlsx|csv|eml|msg|heic|heif|hif|webp|tif|tiff|bmp)\Z")


def object_path(path):
    match = _NAME.fullmatch(path.name)
    root = (_data_dir() / "monthly_reports").resolve()
    if not match or not path.parent.resolve().is_relative_to(root):
        return None
    digest = match[1]
    return root / "objects" / digest[:2] / digest


def _sync(directory):
    if os.name != "nt":
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _publish_link(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".pending-", delete=False) as f:
            temporary = Path(f.name)
        temporary.unlink()
        os.link(source, temporary)
        os.replace(temporary, destination)
        _sync(destination.parent)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _store(path, incoming):
    from app.monthly_report_library import LibraryError, _locked
    target = object_path(path)
    if target is None:
        raise LibraryError("Invalid shared monthly-report object path.")
    digest = target.name
    # Only immutable content enters this pool. Mutable manifests/caches remain
    # independent, and profile locks are always acquired before object locks.
    with _locked(target.parent):
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise LibraryError("Shared report object is invalid; existing data was preserved.")
            with target.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != digest:
                    raise LibraryError("Shared report object failed verification; existing data was preserved.")
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".pending-", delete=False) as output:
                    temporary = Path(output.name)
                    hasher = hashlib.sha256()
                    with incoming() as stream:
                        while chunk := stream.read(1024 * 1024):
                            hasher.update(chunk)
                            output.write(chunk)
                    if hasher.hexdigest() != digest:
                        raise LibraryError("Shared report object does not match its content reference.")
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, 0o444)
                os.replace(temporary, target)
                _sync(target.parent)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        if path.exists() and not path.is_symlink() and os.path.samefile(path, target):
            return
        # Hard links share bytes, not mutable settings. All app changes publish
        # a new digest/path; no pooled file is ever edited in place.
        _publish_link(target, path)


def store_bytes(path, raw):
    from app.monthly_report_library import LibraryError
    target = object_path(path)
    if target is None or hashlib.sha256(raw).hexdigest() != target.name:
        raise LibraryError("Invalid shared monthly-report content reference.")

    @contextmanager
    def incoming():
        with BytesIO(raw) as stream:
            yield stream

    _store(path, incoming)


def store_file(path, source):
    from app.monthly_report_library import LibraryError
    target = object_path(path)
    with source.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256").hexdigest()
    if target is None or digest != target.name:
        raise LibraryError("Invalid shared monthly-report original reference.")
    _store(path, lambda: source.open("rb"))


def consolidate_existing(*, max_files=100, max_bytes=256 * 1024 * 1024, seconds=10.0):
    """Incrementally link verified legacy objects; never delete a user record.

    Safe to repeat after interruption. Bounded scans and streaming hashes keep
    large archives off the heap. A failed link leaves the original path intact.
    """
    root = _data_dir() / "monthly_reports"
    changed = scanned = processed = reclaimed = 0
    deadline = time.monotonic() + seconds
    complete = True
    for directory, dirs, files in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if not (base / d).is_symlink()
                   and (base / d) != root / "objects"]
        for name in files:
            scanned += 1
            if scanned > 50000 or time.monotonic() >= deadline:
                return dict(changed=changed, reclaimed=reclaimed, complete=False)
            path = base / name
            target = object_path(path)
            if target is None or path.is_symlink():
                continue
            if target.exists() and os.path.samefile(path, target):
                continue
            size = path.stat().st_size
            if changed >= max_files or processed + size > max_bytes:
                return dict(changed=changed, reclaimed=reclaimed, complete=False)
            before = path.stat()
            existed = target.exists()
            store_file(path, path)
            # A formerly independent duplicate is now a shared link. Creating
            # the first canonical copy has no net byte saving.
            if existed and before.st_nlink == 1:
                reclaimed += size
            processed += size
            changed += 1
    return dict(changed=changed, reclaimed=reclaimed, complete=complete)
