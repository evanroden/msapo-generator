"""Immutable, no-login reference bundles alongside existing shared QA fixtures.

An archive here is a *reference source shelf*, not an AUTH scenario fixture,
source importer, authenticated vault, or working report. The same Render-backed
testing root, descriptor-safe disk routines, and fixed shared audience are used.
Anyone with the hidden shared testing URL can download these bytes. No source
bytes are put in public Git, CI logs, or static files.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import struct
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from app import monthly_report_fixture_vault as storage
from app.monthly_report_shared_fixtures import _marker

_BUCKET = "_enfra_shared_source_bundles_v1"
_MANIFEST_NAME = "ENFRA_Original_QA_Source_Manifest_2026-10-14.json"
_MAX_ARCHIVE = 96 * 1024 * 1024
_MAX_SHELF = 128 * 1024 * 1024
_MAX_SOURCE = 32 * 1024 * 1024
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().,-]{0,180}\.(?:docx|pdf)\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class SourceFile:
    filename: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class SourceBundle:
    bundle_id: str
    archive_sha256: str
    archive_size: int
    source_files: tuple[SourceFile, ...]


def validate_reference_archive(original: bytes, *, max_bytes: int = _MAX_ARCHIVE) -> tuple[SourceFile, ...]:
    """Validate every declared original without extracting or caching its contents.

    Only the owner-supplied portable bundle format is accepted. The manifest
    itself is user-supplied metadata, NOT approval to import a document, promote
    standing data, or assign an AUTH01/02/03 scenario.
    """
    if not isinstance(original, bytes) or not 1 <= len(original) <= max_bytes:
        raise storage.VaultQuotaExceeded("The reference archive exceeds its bounded upload allowance.")
    # Reject a ZIP-bomb-sized central-directory catalog before Python's
    # ZipFile allocates one ZipInfo for every claimed archive member. The
    # portable reference format holds exactly six files and two small records.
    offset = original.rfind(b"PK\x05\x06", max(0, len(original) - 65557))
    if offset < 0 or len(original) - offset < 22:
        raise ValueError("Reference bundle is not a complete ordinary ZIP.")
    (_, disk, center_disk, entries_on_disk, entries, index_size,
     index_offset, comment) = struct.unpack_from("<4s4H2LH", original, offset)
    if (disk or center_disk or entries != 8 or entries_on_disk != entries
            or index_size > 32 * 1024 or index_offset + index_size > offset
            or offset + 22 + comment != len(original)):
        raise ValueError("Reference ZIP index is malformed or exceeds its safe member bound.")
    try:
        with ZipFile(BytesIO(original)) as archive:
            members = archive.infolist()
            if not 3 <= len(members) <= 14:
                raise ValueError("Reference bundle has an unexpected member count.")
            names = [member.filename for member in members]
            if len(set(names)) != len(names) or _MANIFEST_NAME not in names or "README.md" not in names:
                raise ValueError("Reference bundle is missing its unique manifest or README.")
            total = 0
            for member in members:
                total += member.file_size
                if (member.is_dir() or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16)
                        or member.file_size > max_bytes or total > max_bytes
                        or member.compress_size > max_bytes):
                    raise ValueError("Unsafe or oversized reference archive member.")
            manifest_file = archive.getinfo(_MANIFEST_NAME)
            if manifest_file.file_size > 64 * 1024:
                raise ValueError("Reference manifest is too large.")
            manifest = json.loads(archive.read(_MANIFEST_NAME))
            if type(manifest) is not dict or manifest.get("manifest_version") != 1:
                raise ValueError("Reference source manifest has an unsupported version.")
            declared = manifest.get("source_files")
            if (type(declared) is not list or len(declared) != 6
                    or type(manifest.get("source_count")) is not int
                    or manifest["source_count"] != len(declared)):
                raise ValueError("Exactly six owner-confirmed originals are required in this bundle.")
            expected = {_MANIFEST_NAME, "README.md"}
            files = []
            for item in declared:
                if type(item) is not dict:
                    raise ValueError("Invalid declared reference file.")
                filename, digest, size = item.get("filename"), item.get("sha256"), item.get("bytes")
                if (type(filename) is not str or not _FILENAME.fullmatch(filename)
                        or type(digest) is not str or not _DIGEST.fullmatch(digest)
                        or type(size) is not int or not 1 <= size <= _MAX_SOURCE):
                    raise ValueError("Reference source name, hash or length is invalid.")
                member_name = "originals/" + filename
                if member_name in expected:
                    raise ValueError("Duplicate declared source identity.")
                expected.add(member_name)
                member = archive.getinfo(member_name)
                if member.file_size != size:
                    raise ValueError("Reference file size differs from its original manifest.")
                hash_state = sha256()
                checked = 0
                with archive.open(member) as input_stream:
                    while chunk := input_stream.read(128 * 1024):
                        hash_state.update(chunk)
                        checked += len(chunk)
                        if checked > _MAX_SOURCE:
                            raise ValueError("Reference member unexpectedly exceeded its source bound.")
                if checked != size or hash_state.hexdigest() != digest:
                    raise ValueError("Reference member does not match the owner original SHA-256.")
                files.append(SourceFile(filename, digest, size))
            if set(names) != expected:
                raise ValueError("The archive contains undeclared or extraneous members.")
            return tuple(files)
    except (BadZipFile, KeyError, RuntimeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid immutable six-source reference archive.") from exc


class SharedSourceBundles:
    """Supporting originals on the existing shared test disk, not a new importer.

    Neither upload nor download changes a disposable report, an AUTH fixture,
    standing data, pricing gates, or a saved design. The no-login audience and
    existing filesystem safety model are explicitly retained.
    """

    def __init__(self, storage_root: Path, *, max_archive_bytes: int = _MAX_ARCHIVE,
                 max_shelf_bytes: int = _MAX_SHELF):
        self._root = Path(storage_root)
        if (type(max_archive_bytes) is not int or type(max_shelf_bytes) is not int
                or max_archive_bytes < 1 or max_shelf_bytes < max_archive_bytes):
            raise ValueError("Reference archive size budgets are invalid.")
        self._max_archive = max_archive_bytes
        self._max_shelf = max_shelf_bytes
        # A shared storage engine can serve multiple strictly typed archives,
        # but each type has its OWN physical bucket, validator, and quota.
        # The existing owner-original bucket and receipts remain unchanged.
        self._bucket = _BUCKET
        self._validate_archive = validate_reference_archive
        self._file_count_bounds = (6, 6)

    @contextmanager
    def _directory(self, *, create: bool):
        with storage._root(self._root) as root:
            if not create and self._bucket not in os.listdir(root):
                yield None
                return
            with storage._marked_dir(root, self._bucket, _marker(self._bucket), create) as directory:
                yield directory

    def _receipt(self, bucket, bundle_id) -> SourceBundle:
        storage._identifier(bundle_id)
        fd = os.open(bundle_id, storage._DIRECTORY_FLAGS, dir_fd=bucket)
        try:
            if os.fstat(fd).st_mode & 0o077:
                raise storage.VaultIntegrityError("Reference bundle storage has unsafe permissions.")
            raw = storage._read_file(fd, "receipt.json", 64 * 1024)
            record = json.loads(raw)
            if type(record) is not dict or set(record) != {
                    "bundle_id", "archive_sha256", "archive_size", "source_files"}:
                raise storage.VaultIntegrityError("Reference receipt schema is invalid.")
            files = tuple(SourceFile(**item) for item in record["source_files"])
            receipt = SourceBundle(
                record["bundle_id"], record["archive_sha256"],
                record["archive_size"], files)
            if (receipt.bundle_id != bundle_id
                    or not _DIGEST.fullmatch(receipt.archive_sha256)
                    or type(receipt.archive_size) is not int
                    or not 1 <= receipt.archive_size <= self._max_archive
                    or not self._file_count_bounds[0] <= len(files) <= self._file_count_bounds[1]
                    or storage._json_bytes(asdict(receipt)) != raw):
                raise storage.VaultIntegrityError("Reference receipt does not match its entry.")
            blob = receipt.archive_sha256 + ".zip"
            txn = storage._read_file(fd, storage._TRANSACTION, 4096)
            # Read only compact transaction metadata; do not allocate an
            # archive-sized dummy buffer while listing stored receipts.
            transaction = json.loads(txn)
            if (transaction.get("schema") != 1 or transaction.get("kind") != "reference-bundle"
                    or transaction.get("target") != bundle_id
                    or transaction.get("files") != {blob: receipt.archive_size, "receipt.json": len(raw)}):
                raise storage.VaultIntegrityError("Reference archive transaction is invalid.")
            if set(os.listdir(fd)) != {blob, "receipt.json", storage._TRANSACTION}:
                raise storage.VaultIntegrityError("Reference entry contains unknown files.")
            info = os.stat(blob, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_mode & 0o077 or info.st_size != receipt.archive_size):
                raise storage.VaultIntegrityError("Reference original has unsafe disk geometry.")
            return receipt
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise storage.VaultIntegrityError("Reference archive receipt is invalid.") from exc
        finally:
            os.close(fd)

    def _scan(self, bucket) -> tuple[tuple[SourceBundle, ...], int]:
        receipts = []
        occupied = 0
        for name in sorted(os.listdir(bucket)):
            if name in {storage._MARKER, storage._LOCK}:
                continue
            # Interrupted writes are retained for investigation, not erased
            # or interpreted as an empty clean storage shelf.
            if not storage._ID.fullmatch(name):
                raise storage.VaultIntegrityError("Uncommitted shared reference bundle needs recovery review.")
            item = self._receipt(bucket, name)
            receipts.append(item)
            occupied += item.archive_size + 64 * 1024
        return tuple(receipts), occupied

    def list(self) -> tuple[SourceBundle, ...]:
        with self._directory(create=False) as bucket:
            if bucket is None:
                return ()
            with storage._admission_lock(bucket):
                found, _ = self._scan(bucket)
                return found

    def _download(self, bucket, receipt: SourceBundle) -> bytes:
        fd = os.open(receipt.bundle_id, storage._DIRECTORY_FLAGS, dir_fd=bucket)
        try:
            original = storage._read_file(fd, receipt.archive_sha256 + ".zip", self._max_archive)
        finally:
            os.close(fd)
        if len(original) != receipt.archive_size or sha256(original).hexdigest() != receipt.archive_sha256:
            raise storage.VaultIntegrityError("Shared source archive hash/size changed on disk.")
        return original

    def download(self, bundle_id: str) -> bytes:
        storage._identifier(bundle_id)
        with self._directory(create=False) as bucket:
            if bucket is None:
                raise FileNotFoundError("No shared source archives have been saved.")
            with storage._admission_lock(bucket):
                receipt = self._receipt(bucket, bundle_id)
                return self._download(bucket, receipt)

    def upload(self, original: bytes) -> SourceBundle:
        sources = self._validate_archive(original, max_bytes=self._max_archive)
        digest = sha256(original).hexdigest()
        with self._directory(create=True) as bucket:
            with storage._admission_lock(bucket):
                found, used = self._scan(bucket)
                for existing in found:
                    if existing.archive_sha256 == digest:
                        # Retry after a lost UI acknowledgment is idempotent,
                        # but only once the retained original is reverified.
                        self._download(bucket, existing)
                        return existing
                receipt = SourceBundle(uuid4().hex, digest, len(original), sources)
                record = storage._json_bytes(asdict(receipt))
                if len(record) > 64 * 1024:
                    raise ValueError("Reference metadata exceeded its bounded allowance.")
                if used + len(original) + len(record) + 4096 > self._max_shelf:
                    raise storage.VaultQuotaExceeded(
                        "Shared reference archive shelf is full; existing originals were retained.")
                storage.FixtureVault._install(
                    bucket, receipt.bundle_id,
                    {digest + ".zip": original, "receipt.json": record},
                    lambda: None, kind="reference-bundle")
                return receipt


# Synthetic CI evidence lives in a DIFFERENT disk bucket from owner DOCX/PDF
# originals. It is never interpreted as an AUTH import, standing data, or
# client report. The root, descriptor-safe atomic writes, immutable receipt
# and read-time hash checks are shared, rather than maintaining a second vault.
_EVIDENCE_BUCKET = "_enfra_shared_synthetic_evidence_v1"
_EVIDENCE_MANIFEST = re.compile(r"ENFRA_MSAPO_\d{4}-\d{2}-\d{2}_evidence_manifest\.json\Z")
_EVIDENCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().,-]{0,180}\.zip\Z")
_EVIDENCE_README = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().,-]{0,180}\.md\Z")
_MAX_EVIDENCE_ARCHIVE = 24 * 1024 * 1024
_MAX_EVIDENCE_SHELF = 64 * 1024 * 1024
_MAX_EVIDENCE_MEMBER = 10 * 1024 * 1024


def validate_synthetic_evidence_archive(original: bytes, *,
                                        max_bytes: int = _MAX_EVIDENCE_ARCHIVE) -> tuple[SourceFile, ...]:
    """Validate an exact manifest-bound evidence bundle without unpacking ZIPs.

    The manifest records original CI run/commit labels; uploading evidence
    never converts a failed run into a successful one. The archive remains
    shared/no-login and must be owner-approved for this audience.
    """
    if type(original) is not bytes or not 1 <= len(original) <= max_bytes:
        raise storage.VaultQuotaExceeded("The synthetic evidence ZIP exceeds its bounded upload limit.")
    offset = original.rfind(b"PK\x05\x06", max(0, len(original) - 65557))
    if offset < 0 or len(original) - offset < 22:
        raise ValueError("The evidence bundle is not a complete ZIP.")
    (_, disk, center_disk, disk_entries, entries, index_size,
     index_offset, comment) = struct.unpack_from("<4s4H2LH", original, offset)
    if (disk or center_disk or not 3 <= entries <= 24 or disk_entries != entries
            or index_size > 32 * 1024 or index_offset + index_size > offset
            or offset + 22 + comment != len(original)):
        raise ValueError("Synthetic evidence ZIP index is malformed or exceeds its member limit.")
    try:
        with ZipFile(BytesIO(original)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(members) != entries or len(set(names)) != entries:
                raise ValueError("Duplicate or missing ZIP members are not allowed.")
            manifests = [name for name in names if _EVIDENCE_MANIFEST.fullmatch(name)]
            readmes = {name for name in names if _EVIDENCE_README.fullmatch(name)}
            if len(manifests) != 1 or not 1 <= len(readmes) <= 3:
                raise ValueError("The bundle needs one evidence manifest and at least one README.")
            total = 0
            for member in members:
                total += member.file_size
                if (member.is_dir() or member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16)
                        or member.file_size > max_bytes or member.compress_size > max_bytes
                        or total > max_bytes):
                    raise ValueError("Unsafe, encrypted, or oversized evidence bundle member.")
                if member.filename in readmes and member.file_size > 32 * 1024:
                    raise ValueError("The evidence README exceeds the metadata limit.")
            manifest_name = manifests[0]
            if archive.getinfo(manifest_name).file_size > 64 * 1024:
                raise ValueError("Synthetic evidence manifest exceeds the metadata limit.")
            manifest = json.loads(archive.read(manifest_name))
            if type(manifest) is not dict or manifest.get("schema_version") != "enfra-evidence-v1":
                raise ValueError("Unrecognized synthetic evidence manifest version.")
            declared = manifest.get("artifacts")
            if type(declared) is not list or not 1 <= len(declared) <= 16:
                raise ValueError("The evidence manifest needs between 1 and 16 artifacts.")
            expected = {manifest_name, *readmes}
            verified = []
            for record in declared:
                if type(record) is not dict:
                    raise ValueError("Invalid evidence artifact record.")
                filename = record.get("filename")
                digest = record.get("sha256")
                size = record.get("size_bytes")
                if (type(filename) is not str or not _EVIDENCE_NAME.fullmatch(filename)
                        or type(digest) is not str or not _DIGEST.fullmatch(digest)
                        or type(size) is not int or not 1 <= size <= min(max_bytes, _MAX_EVIDENCE_MEMBER)
                        or filename in expected):
                    raise ValueError("Invalid evidence artifact name, size, or SHA-256.")
                expected.add(filename)
                member = archive.getinfo(filename)
                if member.file_size != size:
                    raise ValueError("Evidence artifact size differs from manifest.")
                hasher, count = sha256(), 0
                with archive.open(member) as stream:
                    while block := stream.read(128 * 1024):
                        count += len(block)
                        if count > _MAX_EVIDENCE_MEMBER:
                            raise ValueError("Evidence artifact is larger than its per-file bound.")
                        hasher.update(block)
                if count != size or hasher.hexdigest() != digest:
                    raise ValueError("Evidence artifact does not match declared SHA-256.")
                verified.append(SourceFile(filename, digest, size))
            if set(names) != expected:
                raise ValueError("The synthetic evidence ZIP has undeclared members.")
            return tuple(verified)
    except (BadZipFile, KeyError, RuntimeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid manifest-bound synthetic evidence ZIP.") from exc


class SharedSyntheticEvidenceBundles(SharedSourceBundles):
    """Immutable synthetic evidence shelf under the existing Render QA root."""

    def __init__(self, storage_root: Path, *, max_archive_bytes: int = _MAX_EVIDENCE_ARCHIVE,
                 max_shelf_bytes: int = _MAX_EVIDENCE_SHELF):
        super().__init__(storage_root, max_archive_bytes=max_archive_bytes,
                         max_shelf_bytes=max_shelf_bytes)
        self._bucket = _EVIDENCE_BUCKET
        self._validate_archive = validate_synthetic_evidence_archive
        self._file_count_bounds = (1, 16)
