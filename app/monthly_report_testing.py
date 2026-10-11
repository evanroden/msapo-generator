"""Server-side physical namespace for synthetic Monthly Report testing.

One opaque browser identity receives its own isolated disk subtree. Production
paths never appear within that subtree; errors fail closed. Streamlit query
parameters select the test interface, not a storage namespace.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
import os
import re
import shutil

_SCOPE: ContextVar[str | None] = ContextVar("enfra_monthly_qa_scope", default=None)
_COOKIE = re.compile(r"[0-9a-f]{32}\Z")
_BUCKET = "_enfra_monthly_report_qa_v1"
_SENTINEL = ".enfra-qa-namespace"


def scope() -> str | None:
    return _SCOPE.get()


@contextmanager
def isolated(browser_token: str):
    """Bind one server request and its copied async contexts to a QA identity."""
    if not isinstance(browser_token, str) or not _COOKIE.fullmatch(browser_token):
        raise ValueError("Isolated testing requires this browser's valid device identity.")
    identity = sha256(("monthly-qa-v1:" + browser_token).encode("ascii")).hexdigest()[:32]
    lease = _SCOPE.set(identity)
    try:
        yield identity
    finally:
        _SCOPE.reset(lease)


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


def data_dir(base: Path) -> Path:
    """Called by memory._data_dir, which is the shared persistence boundary."""
    identity = scope()
    if identity is None:
        return Path(base)
    target = _location(base, identity)
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    sentinel = target / _SENTINEL
    if sentinel.is_symlink():
        raise OSError("Isolated report ownership marker is not safe.")
    if not sentinel.exists():
        # A pre-existing directory that has no marker must never be adopted.
        if any(target.iterdir()):
            raise OSError("Unrecognized test files found; existing files were preserved.")
        with sentinel.open("x", encoding="ascii") as stream:
            stream.write(identity)
            stream.flush()
            os.fsync(stream.fileno())
    if sentinel.read_text(encoding="ascii") != identity:
        raise OSError("Isolated report ownership marker does not match.")
    return target


def reset(base: Path) -> None:
    """Delete only this verified isolated browser namespace, never production."""
    identity = scope()
    if identity is None:
        raise ValueError("Test reset requires an active isolated test context.")
    target = _location(base, identity)
    if not target.exists():
        return
    sentinel = target / _SENTINEL
    if sentinel.is_symlink() or not sentinel.is_file() or sentinel.read_text(encoding="ascii") != identity:
        raise OSError("Test reset refused an unrecognized storage namespace.")
    # Reject symlinks inside the test namespace rather than following or
    # deleting anything that may point to another directory.
    for directory, directories, files in os.walk(target, followlinks=False):
        for name in (*directories, *files):
            if (Path(directory) / name).is_symlink():
                raise OSError("Test reset refused a linked file or directory.")
    shutil.rmtree(target)
