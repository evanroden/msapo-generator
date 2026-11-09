"""Pick SQLite's journal mode from where the database file actually lives.

WAL keeps readers and the writer out of each other's way, but SQLite documents
that it "does not work over a network filesystem": its shared-memory index is
only coherent on one host. Render's persistent disk is local, so the learning
database has always used WAL there. A host that keeps the data folder on a
network share (an Azure Files NFS volume, for example) must use the rollback
journal instead, which relies only on the share's byte-range locks.

EPC_SQLITE_JOURNAL_MODE ("wal" or "delete") overrides the detection when a
deployment knows better than /proc/self/mountinfo.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_NETWORK_FILESYSTEMS = frozenset({"cifs", "smb3", "smbfs"})
_MODES = {"wal": "WAL", "delete": "DELETE"}


def _unescape(field: str) -> str:
    # mountinfo writes space, tab, newline and backslash as octal escapes.
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)


def filesystem_type(path: Path, mountinfo: str | None = None) -> str:
    """The filesystem type of the mount holding ``path``, or "" if unknown."""
    if mountinfo is None:
        try:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            return ""
    target = str(path)
    best_point, best_type = "", ""
    for line in mountinfo.splitlines():
        fields = line.split(" ")
        try:
            point = _unescape(fields[4])
            kind = fields[fields.index("-", 6) + 1]
        except (IndexError, ValueError):
            continue
        inside = point == "/" or target == point or target.startswith(point.rstrip("/") + "/")
        if inside and len(point) >= len(best_point):
            best_point, best_type = point, kind
    return best_type


def on_network_filesystem(path: Path, mountinfo: str | None = None) -> bool:
    kind = filesystem_type(path, mountinfo)
    return kind.startswith("nfs") or kind in _NETWORK_FILESYSTEMS


def journal_mode(path: Path, mountinfo: str | None = None) -> str:
    """"WAL" on a local disk, "DELETE" on network storage or when configured."""
    override = os.getenv("EPC_SQLITE_JOURNAL_MODE", "").strip().lower()
    if override in _MODES:
        return _MODES[override]
    return "DELETE" if on_network_filesystem(path, mountinfo) else "WAL"
