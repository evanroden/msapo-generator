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
import os
import re
import time

from app import monthly_report_library as library
from app.monthly_report_objects import object_path

RETENTION_DAYS = 30
SWEEP_SECONDS = 60 * 60
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_LAST_SWEEP = ".last-sweep"


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


def _import_time(stamp):
    """The recorded import time, or None when it is unreadable or has no zone."""
    try:
        imported = datetime.fromisoformat(stamp.read_text(encoding="ascii"))
    except (OSError, ValueError):
        return None
    return imported if imported.tzinfo is not None else None


def expire(*, now=None, days=RETENTION_DAYS):
    """Erase directory workbooks whose latest import is older than the period.

    Returns the erased fingerprints. Each import time is removed last, so a
    file or pooled copy that cannot be removed now is retried on the next sweep;
    an unreadable import time never erases anything.
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
            if not stamp.exists():
                library._atomic_write(stamp, now.isoformat().encode("ascii"))
                continue
            imported = _import_time(stamp)
            if imported is None or now - imported < timedelta(days=days):
                continue
            try:
                library._qa_path_guard(link)
                link.unlink(missing_ok=True)
                _release_pooled_copy(link)
                stamp.unlink(missing_ok=True)
            except OSError:
                continue
            erased.append(digest)
        for stamp in sorted(folder.glob("*.imported")):
            link = folder / (stamp.stem + ".xlsx")
            if not _DIGEST.fullmatch(stamp.stem) or link.exists():
                continue
            try:  # finish an erase whose pooled copy could not be removed before
                _release_pooled_copy(link)
                stamp.unlink(missing_ok=True)
            except OSError:
                continue
        library._atomic_write(folder / _LAST_SWEEP, now.isoformat().encode("ascii"))
    return tuple(erased)


def expire_quietly(*, force=False):
    """Routine expiry from saves and directory listings, at most hourly unless forced.

    Storage problems never block the caller; the next routine call retries.
    """
    try:
        if not force and time.time() - os.stat(_sources() / _LAST_SWEEP).st_mtime < SWEEP_SECONDS:
            return ()
    except FileNotFoundError:
        pass
    except OSError:
        return ()
    try:
        return expire()
    except (OSError, ValueError, library.LibraryError):
        return ()
