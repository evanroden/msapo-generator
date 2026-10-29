"""Private, bounded original-photo retention; never part of export asset lookup.

An immutable raw blob can outlive a failed report CAS/save. That is preferable
than deleting recovery evidence or corrupting the last-good snapshot. A strict
quota bounds such unreferenced blobs; nothing is automatically evicted.
"""
from dataclasses import dataclass
import hashlib
import json
import stat
from pathlib import Path
import re

from app import monthly_report_library as library
from app import monthly_report_cover_storage as private

MAX_ORIGINAL_BYTES = 64 * 1024 * 1024
MAX_ORIGINAL_STORE_BYTES = 256 * 1024 * 1024
MAX_ORIGINAL_FILES = 64
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')

@dataclass(frozen=True)
class CoverOriginalRef:
    scope: str
    sha256: str
    byte_count: int


def _scope(profile):
    return hashlib.sha256(json.dumps([profile.contract, profile.key],
                                    ensure_ascii=False).encode()).hexdigest()


def _folder(profile):
    return library._profile_path(profile.contract, profile.key) / 'cover-originals'


def _verify(path, reference):
    digest = hashlib.sha256()
    count = 0
    with private.open_file(path) as source:
        while chunk := source.read(1024 * 1024):
            count += len(chunk)
            if count > MAX_ORIGINAL_BYTES:
                raise ValueError('Saved cover original failed its integrity check.')
            digest.update(chunk)
    if count != reference.byte_count or digest.hexdigest() != reference.sha256:
        raise ValueError('Saved cover original failed its integrity check.')


def cover_original_path(profile, reference):
    """Validate scope and original bytes before handing a path to the worker."""
    if not isinstance(reference, CoverOriginalRef) or reference.scope != _scope(profile):
        raise ValueError('Cover original belongs to another report profile scope.')
    if (not _DIGEST.fullmatch(reference.sha256)
            or type(reference.byte_count) is not int
            or not 0 < reference.byte_count <= MAX_ORIGINAL_BYTES):
        raise ValueError('Invalid cover original reference.')
    path = _folder(profile) / (reference.sha256 + '.original')
    _verify(path, reference)
    return path


def store_cover_original(profile, raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ORIGINAL_BYTES:
        raise ValueError('Cover original exceeds the supported file size or is empty.')
    reference = CoverOriginalRef(_scope(profile), hashlib.sha256(raw).hexdigest(), len(raw))
    folder = _folder(profile)
    with private.locked_folder(folder):
        path = folder / (reference.sha256 + '.original')
        if path.exists():
            _verify(path, reference)
            return reference
        total, count = 0, 0
        for name, info in private.entries(folder):
            if name == '.write-lock':
                continue
            count += 1
            if (count >= MAX_ORIGINAL_FILES or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or not name.endswith('.original')):
                raise ValueError('Cover original storage is full or needs maintenance; current artwork is unchanged.')
            total += info.st_size
            if total + len(raw) > MAX_ORIGINAL_STORE_BYTES:
                raise ValueError('Cover original storage is full; current artwork is unchanged.')
        if len(raw) + total > MAX_ORIGINAL_STORE_BYTES:
            raise ValueError('Cover original storage is full; current artwork is unchanged.')
        private.atomic_write(path, raw, mode=0o400)
    return reference
