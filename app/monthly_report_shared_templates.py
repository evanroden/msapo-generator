"""Unchanged Word templates shared with agents on the existing testing disk.

Storage validates the bounded ZIP container, not report semantics or import
readiness. A template never installs a company master or creates an AUTH case.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import stat
import struct
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib

from app import monthly_report_fixture_vault as storage
from app.monthly_report_shared_source_bundles import SharedSourceBundles, SourceFile


MAX_TEMPLATE_MIB = 512
MAX_TEMPLATE_BYTES = MAX_TEMPLATE_MIB * 1024 * 1024
MAX_SHELF_BYTES = 768 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
_BUCKET = "_enfra_shared_report_templates_v1"
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().,-]{0,180}\.docx\Z", re.IGNORECASE)
_REQUIRED = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}


def validate_template(original: bytes, filename: str, *, max_bytes=MAX_TEMPLATE_BYTES):
    """Check every member's CRC in bounded chunks without extracting/parsing it."""
    if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
        raise ValueError("Use a plain Word .docx filename without folders or special characters.")
    if not isinstance(original, bytes) or not 0 < len(original) <= max_bytes:
        raise storage.VaultQuotaExceeded("The Word template exceeds its upload limit.")
    # Bound allocations before ZipFile creates one ZipInfo per index entry.
    offset = original.rfind(b"PK\x05\x06", max(0, len(original) - 65557))
    if offset < 0 or len(original) - offset < 22:
        raise ValueError("The Word template is not a complete ZIP package.")
    (_, disk, index_disk, disk_count, count, index_size,
     index_offset, comment_size) = struct.unpack_from("<4s4H2LH", original, offset)
    if (disk or index_disk or not 3 <= count <= 4096 or disk_count != count
            or index_size > 1024 * 1024 or index_offset + index_size != offset
            or offset + 22 + comment_size != len(original)):
        raise ValueError("The Word template ZIP index is malformed or too large.")
    try:
        with ZipFile(BytesIO(original)) as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            if (len(members) != count or len(set(names)) != count
                    or not _REQUIRED.issubset(names)):
                raise ValueError("The Word template needs unique, complete DOCX package members.")
            expanded = 0
            for member in members:
                name = member.filename
                parts = name.rstrip("/").split("/")
                mode = stat.S_IFMT(member.external_attr >> 16)
                expanded += member.file_size
                if (not name or name != member.orig_filename or "\\" in name
                        or any(part in ("", ".", "..") for part in parts)
                        or any(ord(char) < 32 for char in name) or ":" in name
                        or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
                        or member.flag_bits & 1
                        or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                        or member.file_size > MAX_EXPANDED_BYTES
                        or expanded > MAX_EXPANDED_BYTES
                        or member.compress_size > max_bytes):
                    raise ValueError("Unsafe or oversized Word template package member.")
                if member.is_dir() and (member.file_size or name.rstrip("/") in _REQUIRED):
                    raise ValueError("A Word template package directory contains file data.")
                checked = 0
                with archive.open(member) as stream:
                    while chunk := stream.read(256 * 1024):
                        checked += len(chunk)
                        if checked > member.file_size:
                            raise ValueError("Word template member exceeds its declared size.")
                if checked != member.file_size:
                    raise ValueError("Word template member is incomplete.")
            if any(archive.getinfo(name).file_size == 0 for name in _REQUIRED):
                raise ValueError("The Word template has an empty required package member.")
    except (BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ValueError("The Word template ZIP package failed its integrity check.") from exc
    return (SourceFile(filename, sha256(original).hexdigest(), len(original)),)


class SharedReportTemplates(SharedSourceBundles):
    """Separate immutable DOCX bucket with atomic writes and verified downloads."""

    def __init__(self, storage_root: Path, *, max_template_bytes=MAX_TEMPLATE_BYTES,
                 max_shelf_bytes=MAX_SHELF_BYTES):
        super().__init__(storage_root, max_archive_bytes=max_template_bytes,
                         max_shelf_bytes=max_shelf_bytes)
        self._bucket = _BUCKET
        self._extension = ".docx"
        self._file_count_bounds = (1, 1)

    def _receipt(self, bucket, bundle_id):
        receipt = super()._receipt(bucket, bundle_id)
        source = receipt.source_files[0]
        if (not isinstance(source.filename, str) or not _FILENAME.fullmatch(source.filename)
                or source.sha256 != receipt.archive_sha256
                or type(source.size_bytes) is not int or source.size_bytes != receipt.archive_size):
            raise storage.VaultIntegrityError("Word template receipt differs from its original identity.")
        return receipt

    def upload(self, original: bytes, filename: str):
        sources = validate_template(original, filename, max_bytes=self._max_archive)
        return self._store(original, sources)
