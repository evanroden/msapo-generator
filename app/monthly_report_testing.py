"""Server-side physical namespace for synthetic Monthly Report testing.

One opaque browser identity receives its own isolated disk subtree. Production
paths never appear within that subtree; errors fail closed. Streamlit query
parameters select the test interface, not a storage namespace.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4
from hashlib import sha256
from pathlib import Path
import os
import re
import shutil
import time

_SCOPE: ContextVar[str | None] = ContextVar("enfra_monthly_qa_scope", default=None)
_LEASE: ContextVar[str | None] = ContextVar("enfra_monthly_qa_generation", default=None)
_COOKIE = re.compile(r"[0-9a-f]{32}\Z")
_BUCKET = "_enfra_monthly_report_qa_v1"
_SENTINEL = ".enfra-qa-namespace"
# Owner policy (#292): another browser's isolated copy idle this long may be
# reclaimed. Ordinary use refreshes the marker's time at most this often.
IDLE_SECONDS = 24 * 60 * 60
_ACTIVITY_SECONDS = 10 * 60
_MEASURE_LIMIT = 20000


def scope() -> str | None:
    return _SCOPE.get()


def generation() -> str | None:
    """The current test-session lease; changes after a verified QA reset."""
    return _LEASE.get()


def capture_namespace():
    """Capture only our storage identity/lease for a later UI callback.

    A whole ``copy_context`` also captures Streamlit's render/fragment state.
    Restoring that inside a fragment can register its widgets outside the
    fragment and turn every preview request into a full editor rerun. Worker
    threads may still copy their context; UI callbacks must retain the current
    framework context and bind only these two application-owned variables.
    """
    identity, lease = scope(), generation()

    @contextmanager
    def activate():
        chosen = _SCOPE.set(identity)
        previous_generation = _LEASE.set(lease)
        try:
            yield
        finally:
            _LEASE.reset(previous_generation)
            _SCOPE.reset(chosen)

    return activate


@contextmanager
def isolated(browser_token: str):
    """Bind one server request and its copied async contexts to a QA identity."""
    if not isinstance(browser_token, str) or not _COOKIE.fullmatch(browser_token):
        raise ValueError("Isolated testing requires this browser's valid device identity.")
    identity = sha256(("monthly-qa-v1:" + browser_token).encode("ascii")).hexdigest()[:32]
    chosen = _SCOPE.set(identity)
    previous_generation = _LEASE.set(None)
    try:
        yield identity
    finally:
        _LEASE.reset(previous_generation)
        _SCOPE.reset(chosen)


def _location(base: Path, identity: str) -> Path:
    # Fail closed if the existing storage root is absent (for example, Render
    # disk mount is unavailable). Never use a live root as a fallback.
    base = Path(base)
    if not base.is_dir() or base.is_symlink():
        raise OSError("Isolated report storage is unavailable; no live data was used.")
    parent = base / _BUCKET
    target = parent / identity
    if parent.is_symlink() or target.is_symlink():
        raise OSError("Isolated report storage path cannot be a link.")
    if parent.exists() and not parent.is_dir():
        raise OSError("Isolated report storage path is invalid.")
    if target.exists() and not target.is_dir():
        raise OSError("Isolated report storage namespace is invalid.")
    if not target.resolve().is_relative_to(base.resolve()) or target.resolve() == base.resolve():
        raise OSError("Isolated report path did not pass its containment check.")
    return target


def _marker(sentinel: Path, identity: str) -> str:
    """Validate both test owner and a non-reusable namespace generation."""
    if sentinel.is_symlink() or not sentinel.is_file():
        raise OSError("Unrecognized test storage marker; live records were untouched.")
    values = sentinel.read_text(encoding="ascii").split("|")
    if (len(values) != 2 or values[0] != identity
            or not _COOKIE.fullmatch(values[1])):
        raise OSError("Isolated report ownership/generation does not match.")
    return values[1]


def data_dir(base: Path) -> Path:
    """Shared persistence boundary; old preview jobs cannot recreate a reset."""
    identity = scope()
    if identity is None:
        return Path(base)
    target = _location(base, identity)
    expected = _LEASE.get()
    if not target.exists():
        if expected is not None:
            raise OSError("This isolated test was reset during a running task; retry on a new test session.")
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
    sentinel = target / _SENTINEL
    if not sentinel.exists():
        # Existing unmarked content is never adopted, including after a crash.
        if expected is not None or any(target.iterdir()):
            raise OSError("Unrecognized test files found; existing files were preserved.")
        generation = uuid4().hex
        try:
            with sentinel.open("x", encoding="ascii") as stream:
                stream.write(identity + "|" + generation)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass  # Another first-use tab installed its own valid marker.
    generation = _marker(sentinel, identity)
    if expected is not None and expected != generation:
        raise OSError("The isolated test changed while this task was running; stale work was blocked.")
    _LEASE.set(generation)
    try:
        # Viewing writes nothing else, so record use on the existing marker.
        if time.time() - sentinel.stat().st_mtime > _ACTIVITY_SECONDS:
            os.utime(sentinel)
    except OSError:
        pass  # recording activity never blocks the request
    return target


def _last_change(target: Path) -> float | None:
    """Newest change anywhere in a namespace; None when it cannot be measured safely."""
    newest, seen, unreadable = target.lstat().st_mtime, 0, []
    for directory, directories, files in os.walk(target, onerror=unreadable.append, followlinks=False):
        for name in (*directories, *files):
            seen += 1
            path = Path(directory) / name
            if seen > _MEASURE_LIMIT or path.is_symlink():
                return None
            try:
                newest = max(newest, path.lstat().st_mtime)
            except FileNotFoundError:
                continue
    return None if unreadable else newest


_SET_ASIDE = ".reclaimed-"
_DISCARDING = ".discarding-"


def set_aside_idle(base: Path, identity: str, generation: str, *, now: float | None = None,
                   idle_seconds: float = IDLE_SECONDS) -> Path | None:
    """Rename another browser's namespace aside after a day without changes.

    Returns the set-aside path, or None when the namespace must stay: this
    request's own namespace, a mismatched or invalid marker, any link, anything
    that cannot be measured, or any change seen while it was being checked.
    The caller then calls ``discard_set_aside`` or ``restore_set_aside``; a
    returning browser's stale work fails closed meanwhile. Shared originals
    live outside this bucket and are never touched.
    """
    if identity == scope() or not _COOKIE.fullmatch(identity):
        return None
    clock = time.time() if now is None else now
    try:
        target = _location(base, identity)
        if not target.is_dir() or _marker(target / _SENTINEL, identity) != generation:
            return None
        if clock - (target / _SENTINEL).lstat().st_mtime < idle_seconds:
            return None  # recent use seen on the marker; no walk needed
        newest = _last_change(target)
        if newest is None or clock - newest < idle_seconds:
            return None
        tombstone = target.parent / (_SET_ASIDE + identity + "-" + uuid4().hex)
        os.rename(target, tombstone)
        # Requests resolve the namespace path each time, so nothing new lands in
        # the set-aside copy; activity during the check above shows up here.
        if _last_change(tombstone) != newest:
            restore_set_aside(base, tombstone)
            return None
    except (OSError, UnicodeError):
        return None  # anything unexpected keeps the namespace
    return tombstone


def restore_set_aside(base: Path, tombstone: Path) -> None:
    """Put a set-aside namespace back, unless its browser already started a fresh one."""
    target = _location(base, tombstone.name[len(_SET_ASIDE):].split("-", 1)[0])
    if target.exists() or target.is_symlink():
        discard_set_aside(tombstone)
    else:
        os.rename(tombstone, target)


def discard_set_aside(tombstone: Path) -> None:
    """Delete a set-aside namespace; it is renamed first so it is never restored half-deleted."""
    doomed = tombstone.with_name(_DISCARDING + tombstone.name[len(_SET_ASIDE):])
    try:
        os.rename(tombstone, doomed)
    except OSError:
        doomed = tombstone  # still delete it rather than leave it to be restored
    shutil.rmtree(doomed, ignore_errors=True)


def recover_set_aside(base: Path) -> None:
    """After an interrupted admission, restore set-aside namespaces and finish deletions."""
    bucket = Path(base) / _BUCKET
    if bucket.is_symlink() or not bucket.is_dir():
        return
    for leftover in bucket.iterdir():
        if leftover.is_symlink() or not leftover.is_dir():
            continue
        try:
            if leftover.name.startswith(_DISCARDING):
                shutil.rmtree(leftover, ignore_errors=True)
            elif leftover.name.startswith(_SET_ASIDE):
                restore_set_aside(base, leftover)
        except OSError:
            continue


def reclaim_idle(base: Path, identity: str, generation: str, *, now: float | None = None,
                 idle_seconds: float = IDLE_SECONDS) -> bool:
    """Set aside and delete another browser's idle namespace in one step."""
    tombstone = set_aside_idle(base, identity, generation, now=now, idle_seconds=idle_seconds)
    if tombstone is None:
        return False
    discard_set_aside(tombstone)
    return True


def reset(base: Path) -> None:
    """Delete only this verified isolated browser namespace, never production."""
    identity = scope()
    if identity is None:
        raise ValueError("Test reset requires an active isolated test context.")
    target = _location(base, identity)
    if not target.exists():
        if _LEASE.get() is not None:
            raise OSError("The current QA run was already reset.")
        return
    _marker(target / _SENTINEL, identity)
    if _LEASE.get() is not None and _LEASE.get() != _marker(target / _SENTINEL, identity):
        raise OSError("An older test session may not reset another generation.")
    # Reject symlinks inside the test namespace rather than following or
    # deleting anything that may point to another directory.
    for directory, directories, files in os.walk(target, followlinks=False):
        for name in (*directories, *files):
            if (Path(directory) / name).is_symlink():
                raise OSError("Test reset refused a linked file or directory.")
    # Converter/preview tasks may remove volatile children during rmtree.
    # Treat a missing child as already cleaned, but NEVER ignore a surviving
    # namespace, symlink, missing authorization, or an earlier lease mismatch.
    def disappeared_child(_operation, path, exc):
        if isinstance(exc, FileNotFoundError) and Path(path) != target:
            return
        raise exc

    try:
        shutil.rmtree(target, onexc=disappeared_child)
    except OSError:
        # A late cleanup error can arrive *after* rmtree removed the entire
        # verified QA namespace. The former code showed "reset failed", then
        # attempted a same-generation render against that now-missing path.
        # Only treat this as complete if the EXACT isolated root is genuinely
        # absent after the exception. Every partial removal still fails closed.
        # The old lease remains invalid, and only a new isolated() request can
        # establish a new generation. No live-root path is consulted here.
        if target.exists() or target.is_symlink():
            raise
    if target.exists() or target.is_symlink():
        raise OSError("The isolated namespace could not be completely reset.")
