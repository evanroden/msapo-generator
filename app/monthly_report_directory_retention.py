"""Uploaded contact-directory workbooks are kept 30 days after their latest import.

Nothing reads a stored workbook back: every directory revision holds the
reviewed sites and contacts, and history keeps the workbook fingerprint and
cell references. The raw file only helps check a recent import, so it is then
erased. A pooled copy still linked elsewhere (for example the same file used as
a report source) is kept. Files stored before this policy start their period at
the first sweep, so nothing is removed on deployment.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import re

from app import monthly_report_library as library
from app.monthly_report_objects import object_path

RETENTION_DAYS = 30
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _sources():
    return library._root() / "directory_sources"


@contextmanager
def _sources_locked():
    # Imports and expiry share one lock, so a re-import is never erased midway.
    # Order: contract lock, then this lock, then the object pool's lock.
    with library._locked(library._root() / "directory_locks" / "directory-sources"):
        yield


def store_import(digest, raw):
    """Keep one confirmed upload and restart its retention period."""
    with _sources_locked():
        library._atomic_write(_sources() / (digest + ".xlsx"), raw)
        library._atomic_write(_sources() / (digest + ".imported"), library._now().encode("ascii"))


def _release_pooled_copy(link):
    target = object_path(link)
    if target is None:
        return
    with library._locked(target.parent):  # the lock every pool write takes
        try:
            if target.stat().st_nlink == 1:
                target.unlink()
        except FileNotFoundError:
            pass


def expire(*, now=None, days=RETENTION_DAYS):
    """Erase directory workbooks whose latest import is older than the period.

    Returns the erased fingerprints. A file that cannot be removed now keeps
    its import time and is retried on the next sweep.
    """
    folder = _sources()
    if not folder.is_dir():
        return ()
    now = now or datetime.now(timezone.utc)
    erased = []
    with _sources_locked():
        for link in sorted(folder.glob("*.xlsx")):
            digest, stamp = link.stem, folder / (link.stem + ".imported")
            if not _DIGEST.fullmatch(digest) or link.is_symlink():
                continue
            try:
                imported = datetime.fromisoformat(stamp.read_text(encoding="ascii"))
            except FileNotFoundError:
                library._atomic_write(stamp, now.isoformat().encode("ascii"))
                continue
            except (OSError, ValueError):
                continue  # an unreadable import time never erases a workbook
            if now - imported < timedelta(days=days):
                continue
            try:
                library._qa_path_guard(link)
                link.unlink(missing_ok=True)
                _release_pooled_copy(link)
                stamp.unlink(missing_ok=True)
            except OSError:
                continue
            erased.append(digest)
        for stamp in folder.glob("*.imported"):
            if not (folder / (stamp.stem + ".xlsx")).exists():
                stamp.unlink(missing_ok=True)
    return tuple(erased)


def expire_quietly():
    """Opportunistic expiry after a save; storage problems never block saving."""
    try:
        return expire()
    except (OSError, library.LibraryError):
        return ()
