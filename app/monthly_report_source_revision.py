"""Cheap, scoped identity proof for UI checks that do not need source bytes.

Never use this to supply source bytes or approve an upload. Final consumers
still call source_bytes() and independently hash the exact original.
"""
from collections import OrderedDict
from pathlib import Path
from stat import S_ISREG
from threading import RLock

_LOCK = RLock()
_PROOFS = OrderedDict()
_MAX_PROOFS = 64


def _stamp(path: Path, limit: int):
    from app import monthly_report_library as library
    library._qa_path_guard(path)
    status = path.lstat()
    if not S_ISREG(status.st_mode) or status.st_size > limit:
        raise ValueError("Saved source is missing, linked or exceeds its file limit.")
    return (status.st_dev, status.st_ino, status.st_mode, status.st_nlink,
            status.st_size, status.st_mtime_ns, status.st_ctime_ns)


def verified_source_revision(profile, source):
    """Rehash once; use stat/ctime only for subsequent *identity-only* UI checks.

    Any missing, replaced, corrupt, oversized or linked original fails closed.
    This proves no content or claim and stores no original bytes in memory.
    """
    from app import monthly_report_sources as sources
    path = sources._path(profile, source.sha256, source.suffix)
    limit = sources.file_size_limit(source.suffix)
    key = (str(path), source.sha256, source.suffix, limit)
    try:
        before = _stamp(path, limit)
    except (OSError, ValueError):
        with _LOCK:
            _PROOFS.pop(key, None)
        raise
    with _LOCK:
        known = _PROOFS.get(key)
        if known == before:
            _PROOFS.move_to_end(key)
            return
        _PROOFS.pop(key, None)
    # Deliberately use the existing bounded, SHA-256-verified reader. Its
    # temporary bytes are released; 128-MiB Word files are never memoized.
    sources.source_bytes(profile, source)
    after = _stamp(path, limit)
    if before != after:
        raise ValueError("Saved source changed during integrity verification.")
    with _LOCK:
        _PROOFS[key] = after
        _PROOFS.move_to_end(key)
        while len(_PROOFS) > _MAX_PROOFS:
            _PROOFS.popitem(last=False)
