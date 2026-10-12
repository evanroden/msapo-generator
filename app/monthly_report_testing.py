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

_SCOPE: ContextVar[str | None] = ContextVar("enfra_monthly_qa_scope", default=None)
_LEASE: ContextVar[str | None] = ContextVar("enfra_monthly_qa_generation", default=None)
_COOKIE = re.compile(r"[0-9a-f]{32}\Z")
_BUCKET = "_enfra_monthly_report_qa_v1"
_SENTINEL = ".enfra-qa-namespace"


def scope() -> str | None:
    return _SCOPE.get()


def generation() -> str | None:
    """The current test-session lease; changes after a verified QA reset."""
    return _LEASE.get()


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
    return target


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
    # A disposed preview/conversion task may remove a transient child such as
    # render-jobs between the symlink/ownership scan and rmtree's own walk.
    # Treat ONLY a disappearing child as already cleaned. A missing root,
    # permission error, symlink issue or surviving target remains a hard error:
    # no reset is acknowledged until the entire namespace is gone.
    def disappeared_child(_operation, path, exc):
        if isinstance(exc, FileNotFoundError) and Path(path) != target:
            return
        raise exc

    shutil.rmtree(target, onexc=disappeared_child)
    if target.exists() or target.is_symlink():
        raise OSError("The isolated namespace could not be completely reset.")
