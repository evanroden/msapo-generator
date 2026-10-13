"""Disabled-by-default storage primitives for a future private fixture route.

Nothing imports this module into the application or configures an authorizer.
The caller must supply a server-side verifier of the *current* authenticated
request for every operation. A cookie, subject string or this module's return
types are not authentication. Public Streamlit media/download routes must not
be used to deliver the bytes returned here.

The explicit existing storage root is never inferred from ordinary report
storage, an environment variable or the working directory. These POSIX disk
primitives do not prove that a Render disk is attached or survives redeployment.
The production Starting report importer, private transport, reset leases and
owner-approved retention policy remain separate, unconnected requirements.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
import fcntl
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Callable
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

_VAULT = "_enfra_private_fixtures_v1"
_RUNS = "_enfra_private_fixture_runs_v1"
_MARKER = ".enfra-private-fixture-storage"
_LOCK = ".admission-lock"
_TRANSACTION = ".enfra-fixture-transaction"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_PERIOD = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])\Z")
_MANIFEST_LIMIT = 64 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


class AuthorizationRequired(PermissionError):
    """No current, server-verified owner grant exists for this operation."""


class VaultIntegrityError(OSError):
    """An existing path or original failed validation; nothing is adopted."""


class VaultQuotaExceeded(OSError):
    """Admission failed without deleting an existing fixture."""


@dataclass(frozen=True)
class AccessRequest:
    operation: str
    fixture_id: str | None = None
    run_id: str | None = None
    generation: str | None = None


@dataclass(frozen=True)
class AuthorizedOwner:
    """Verifier result only; constructing this object does not authenticate."""
    subject: str


@dataclass(frozen=True)
class ReportIdentity:
    contract: str
    sites: tuple[str, ...]
    month: str
    site_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedSection:
    section: str
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixtureMetadata:
    friendly_name: str
    source: ReportIdentity
    target: ReportIdentity
    scenario: str
    owner_expectations: str
    expected_content: tuple[ExpectedSection, ...]
    confirmed_at: str
    partial_file_confirmed: bool = False


@dataclass(frozen=True)
class FixtureReceipt:
    fixture_id: str
    original_sha256: str
    original_size: int
    media_type: str
    metadata: FixtureMetadata


@dataclass(frozen=True)
class FixtureOriginal:
    receipt: FixtureReceipt
    original: bytes


@dataclass(frozen=True)
class InterruptedUpload:
    staging_id: str
    verified: bool
    retained_bytes: int | None
    reason: str


@dataclass(frozen=True)
class VaultListing:
    fixtures: tuple[FixtureReceipt, ...]
    recovery: tuple[InterruptedUpload, ...] = ()


@dataclass(frozen=True)
class ReplayCopy:
    """Internal filesystem handoff; not a public download or importer result."""
    receipt: FixtureReceipt
    run_id: str
    generation: str
    original_path: Path


Authorizer = Callable[[object, AccessRequest], AuthorizedOwner | None]


def _text(value, label, maximum=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{label} must be explicit, nonempty and bounded.")


def _identity(value):
    if not isinstance(value, ReportIdentity):
        raise ValueError("Source and target identities must be explicitly confirmed.")
    _text(value.contract, "Contract", 200)
    if (not isinstance(value.sites, tuple) or not 1 <= len(value.sites) <= 100
            or len(set(value.sites)) != len(value.sites)):
        raise ValueError("Sites must be an explicit unique tuple.")
    for site in value.sites:
        _text(site, "Site", 200)
    if not isinstance(value.site_titles, tuple) or (value.site_titles and len(value.site_titles) != len(value.sites)):
        raise ValueError("Site titles must align with their canonical site identities.")
    for title in value.site_titles:
        _text(title, "Site title", 200)
    if (not isinstance(value.month, str) or not _PERIOD.fullmatch(value.month)
            or int(value.month[:4]) < 1):
        raise ValueError("Reporting month must be YYYY-MM.")


def _validate_metadata(value):
    if not isinstance(value, FixtureMetadata):
        raise ValueError("Owner-confirmed fixture metadata is required.")
    _text(value.friendly_name, "Friendly name", 200)
    _identity(value.source)
    _identity(value.target)
    _text(value.owner_expectations, "Owner expectations", 8000)
    if (not isinstance(value.expected_content, tuple) or not 1 <= len(value.expected_content) <= 100
            or len({item.section for item in value.expected_content
                    if isinstance(item, ExpectedSection)}) != len(value.expected_content)):
        raise ValueError("An independent expected-content manifest is required.")
    for item in value.expected_content:
        if not isinstance(item, ExpectedSection):
            raise ValueError("Invalid expected-content section.")
        _text(item.section, "Expected section", 200)
        if not item.includes and not item.excludes:
            raise ValueError("Each expected section needs an explicit expectation.")
        for values in (item.includes, item.excludes):
            if not isinstance(values, tuple) or len(values) > 100:
                raise ValueError("Expected section facts must be a bounded tuple.")
            for fact in values:
                _text(fact, "Expected fact")
    try:
        confirmed = datetime.fromisoformat(value.confirmed_at)
    except (TypeError, ValueError) as exc:
        raise ValueError("An owner confirmation timestamp is required.") from exc
    if confirmed.tzinfo is None or type(value.partial_file_confirmed) is not bool:
        raise ValueError("Confirmation requires a timezone and an explicit partial-file decision.")
    same_sites = set(value.source.sites) == set(value.target.sites)
    same_contract = value.source.contract == value.target.contract
    if value.scenario == "AUTH01":
        source_year, source_month = map(int, value.source.month.split("-"))
        target_year, target_month = map(int, value.target.month.split("-"))
        if not (same_contract and same_sites and
                12 * target_year + target_month == 12 * source_year + source_month + 1):
            raise ValueError("AUTH01 requires the same sites and the following month.")
    elif value.scenario == "AUTH02":
        if not same_contract or same_sites:
            raise ValueError("AUTH02 requires different selected sites in the same contract.")
    elif value.scenario == "AUTH03":
        if not (same_contract and same_sites and value.source.month == value.target.month
                and value.partial_file_confirmed):
            raise ValueError("AUTH03 requires explicit confirmation of this current-month partial file.")
    else:
        raise ValueError("An AUTH01, AUTH02 or AUTH03 scenario is required.")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid opaque fixture/run/generation identifier.")
    return value


def _check_native_package(original):
    # Bound central-directory work BEFORE ZipFile creates one Python object per
    # member. This route accepts normal DOCX packages, not ZIP64 or giant ZIP
    # catalogs. It never decompresses, extracts or approves any source content.
    offset = original.rfind(b"PK\x05\x06", max(0, len(original) - 65557))
    if offset < 0 or len(original) - offset < 22:
        raise ValueError("Fixture must be a native Starting report DOCX.")
    _, disk, central_disk, on_disk, count, central_size, central_offset, comment = struct.unpack_from("<4s4H2LH", original, offset)
    if (disk or central_disk or on_disk != count or not 1 <= count <= 10000
            or central_size > 2 * 1024 * 1024 or central_offset + central_size > offset
            or offset + 22 + comment != len(original)):
        raise ValueError("Fixture DOCX package index exceeds the safe native-reader bound.")
    try:
        with ZipFile(BytesIO(original)) as package:
            names = package.namelist()
            if (len(names) > 10000 or len(set(names)) != len(names)
                    or not {"[Content_Types].xml", "word/document.xml"}.issubset(names)):
                raise ValueError("Fixture must be a native Starting report DOCX with unique package members.")
    except BadZipFile as exc:
        raise ValueError("Fixture must be a native Starting report DOCX.") from exc


@contextmanager
def _root(path):
    # Traverse every ancestor by descriptor: checking a path and subsequently
    # opening that whole path would leave an intermediate-link replacement race.
    if not path.is_absolute() or ".." in path.parts:
        raise VaultIntegrityError("Private storage requires an explicit absolute existing root.")
    fd = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child = os.open(component, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_file(directory, name, maximum):
    fd = os.open(name, _FILE_FLAGS, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise VaultIntegrityError("Invalid private fixture file.")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise VaultIntegrityError("Private fixture exceeds its declared bound.")
        return data
    finally:
        os.close(fd)


def _write_file(directory, name, data):
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def _marked_dir(parent, name, marker, create):
    created = False
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            created = True
        except FileExistsError:
            pass
    fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    try:
        if os.fstat(fd).st_mode & 0o077:
            raise VaultIntegrityError("Private fixture directories must be owner-only.")
        if created:
            _write_file(fd, _MARKER, marker)
            os.fsync(fd)
            os.fsync(parent)
        if _read_file(fd, _MARKER, 1024) != marker:
            raise VaultIntegrityError("Private fixture storage ownership does not match.")
        yield fd
    finally:
        os.close(fd)


@contextmanager
def _admission_lock(directory):
    fd = os.open(_LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise VaultIntegrityError("Invalid private fixture admission lock.")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class FixtureVault:
    """No enabled instance exists; an approved server adapter must create one."""

    def __init__(self, storage_root: Path, *, authorize_owner: Authorizer | None = None,
                 max_fixture_bytes: int = 25 * 1024 * 1024,
                 max_owner_bytes: int = 128 * 1024 * 1024,
                 max_run_copy_bytes: int = 128 * 1024 * 1024):
        self._root = Path(storage_root)
        self._authorizer = authorize_owner
        if (type(max_fixture_bytes) is not int or type(max_owner_bytes) is not int
                or type(max_run_copy_bytes) is not int
                or not 1 <= max_fixture_bytes <= max_owner_bytes or max_run_copy_bytes < 1):
            raise ValueError("Private fixture size limits must be positive and ordered.")
        self._max_fixture = max_fixture_bytes
        self._max_owner = max_owner_bytes
        self._max_runs = max_run_copy_bytes

    def _authorize(self, context, request, expected=None):
        if context is None or self._authorizer is None:
            raise AuthorizationRequired("Owner authorization is required.")
        try:
            owner = self._authorizer(context, request)
        except Exception:
            raise AuthorizationRequired("Owner authorization could not be verified.") from None
        if (not isinstance(owner, AuthorizedOwner) or not isinstance(owner.subject, str)
                or not owner.subject.strip() or len(owner.subject) > 512
                or (expected is not None and owner != expected)):
            raise AuthorizationRequired("Owner authorization is required.")
        return owner

    @contextmanager
    def _owner_directory(self, owner, *, runs=False, create=False):
        bucket = _RUNS if runs else _VAULT
        identity = sha256(owner.subject.encode("utf-8")).hexdigest()
        with _root(self._root) as root:
            with _marked_dir(root, bucket, (bucket + "|1").encode("ascii"), create) as parent:
                with _marked_dir(parent, identity, (bucket + "|1|" + identity).encode("ascii"), create) as child:
                    yield child, self._root / bucket / identity

    def _load(self, directory, fixture_id):
        fd = os.open(_identifier(fixture_id), _DIRECTORY_FLAGS, dir_fd=directory)
        try:
            if os.fstat(fd).st_mode & 0o077:
                raise VaultIntegrityError("Private fixture entry is not owner-only.")
            encoded = _read_file(fd, "manifest.json", _MANIFEST_LIMIT)
            value = json.loads(encoded)
            details = value["metadata"]
            metadata = FixtureMetadata(
                friendly_name=details["friendly_name"],
                source=ReportIdentity(details["source"]["contract"], tuple(details["source"]["sites"]), details["source"]["month"],
                                      tuple(details["source"].get("site_titles", ()))),
                target=ReportIdentity(details["target"]["contract"], tuple(details["target"]["sites"]), details["target"]["month"],
                                      tuple(details["target"].get("site_titles", ()))),
                scenario=details["scenario"], owner_expectations=details["owner_expectations"],
                expected_content=tuple(ExpectedSection(item["section"], tuple(item["includes"]), tuple(item["excludes"]))
                                       for item in details["expected_content"]),
                confirmed_at=details["confirmed_at"], partial_file_confirmed=details["partial_file_confirmed"],
            )
            _validate_metadata(metadata)
            digest = value["original_sha256"]
            if (type(value["schema"]) is not int or value["schema"] != 1 or value["fixture_id"] != fixture_id
                    or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or value["media_type"] != "application/vnd.openxmlformats-officedocument.wordprocessingml.document"):
                raise VaultIntegrityError("Invalid private fixture manifest identity.")
            name = digest + ".docx"
            if set(os.listdir(fd)) != {"manifest.json", name, _TRANSACTION}:
                raise VaultIntegrityError("Private fixture entry has unexpected content.")
            transaction = _read_file(fd, _TRANSACTION, 4096)
            if json.loads(transaction) != {"schema": 1, "kind": "fixture", "target": fixture_id,
                                           "files": {name: value["original_size"], "manifest.json": len(encoded)}}:
                raise VaultIntegrityError("Private fixture commit record does not match.")
            original = _read_file(fd, name, self._max_fixture)
            if (type(value["original_size"]) is not int or value["original_size"] != len(original)
                    or sha256(original).hexdigest() != digest):
                raise VaultIntegrityError("Private fixture original hash/size does not match.")
            receipt = FixtureReceipt(fixture_id, digest, len(original), value["media_type"], metadata)
            return FixtureOriginal(receipt, original), len(encoded) + len(transaction)
        except (KeyError, TypeError, ValueError) as exc:
            raise VaultIntegrityError("Private fixture manifest is invalid.") from exc
        finally:
            os.close(fd)

    def _scan(self, directory):
        receipts, recovery, total = [], [], 0
        for name in sorted(os.listdir(directory)):
            if name in {_MARKER, _LOCK}:
                continue
            if name.startswith(".pending-") and _ID.fullmatch(name[len(".pending-"):]):
                status = self._pending(directory, name)
                recovery.append(status)
                total += status.retained_bytes or 0
                continue
            if not _ID.fullmatch(name):
                raise VaultIntegrityError("Uncommitted or unrecognized vault content requires review.")
            original, manifest_size = self._load(directory, name)
            receipts.append(original.receipt)
            total += len(original.original) + manifest_size
        return VaultListing(tuple(receipts), tuple(recovery)), total

    def _pending(self, parent, name):
        fd = None
        try:
            fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
            if os.fstat(fd).st_mode & 0o077:
                raise VaultIntegrityError("Interrupted upload is not private.")
            encoded = _read_file(fd, _TRANSACTION, 4096)
            transaction = json.loads(encoded)
            _identifier(transaction["target"])
            files = transaction["files"]
            if (set(transaction) != {"schema", "kind", "target", "files"}
                    or type(transaction["schema"]) is not int or transaction["schema"] != 1
                    or transaction["kind"] != "fixture" or not isinstance(files, dict)
                    or len(files) != 2 or "manifest.json" not in files):
                raise VaultIntegrityError("Interrupted upload marker is invalid.")
            for filename, size in files.items():
                bound = _MANIFEST_LIMIT if filename == "manifest.json" else self._max_fixture
                if (filename != "manifest.json" and not re.fullmatch(r"[0-9a-f]{64}\.docx", filename)
                        or type(size) is not int or not 1 <= size <= bound):
                    raise VaultIntegrityError("Interrupted upload file record is invalid.")
            actual = set(os.listdir(fd))
            if not actual.issubset({_TRANSACTION, *files}):
                raise VaultIntegrityError("Interrupted upload contains unknown content.")
            total = len(encoded)
            for filename in actual - {_TRANSACTION}:
                child = os.open(filename, _FILE_FLAGS, dir_fd=fd)
                try:
                    info = os.fstat(child)
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or info.st_mode & 0o077 or info.st_size > files[filename]):
                        raise VaultIntegrityError("Interrupted upload file is unsafe.")
                    total += info.st_size
                finally:
                    os.close(child)
            return InterruptedUpload(name[len(".pending-"):], True, total,
                                     "Interrupted private upload retained; owner recovery review is required.")
        except (OSError, KeyError, TypeError, ValueError):
            return InterruptedUpload(name[len(".pending-"):], False, None,
                                     "Unrecognized interrupted upload retained; new uploads are blocked pending review.")
        finally:
            if fd is not None:
                os.close(fd)

    def list(self, context) -> VaultListing:
        request = AccessRequest("list")
        owner = self._authorize(context, request)
        result = VaultListing(())
        identity = sha256(owner.subject.encode("utf-8")).hexdigest()
        with _root(self._root) as root:
            if _VAULT in os.listdir(root):
                with _marked_dir(root, _VAULT, (_VAULT + "|1").encode("ascii"), False) as bucket:
                    if identity in os.listdir(bucket):
                        with _marked_dir(bucket, identity, (_VAULT + "|1|" + identity).encode("ascii"), False) as directory:
                            with _admission_lock(directory):
                                result, _ = self._scan(directory)
        self._authorize(context, request, owner)
        return result

    def _read_operation(self, context, fixture_id, operation):
        request = AccessRequest(operation, fixture_id)
        owner = self._authorize(context, request)
        with self._owner_directory(owner) as (directory, _):
            original, _ = self._load(directory, fixture_id)
        self._authorize(context, request, owner)
        return original

    def read(self, context, fixture_id) -> FixtureOriginal:
        return self._read_operation(context, fixture_id, "read")

    def download(self, context, fixture_id) -> bytes:
        """Authorized bytes only; this does not install a transport/URL."""
        return self._read_operation(context, fixture_id, "download").original

    def upload(self, context, original: bytes, metadata: FixtureMetadata) -> FixtureReceipt:
        request = AccessRequest("upload")
        owner = self._authorize(context, request)
        _validate_metadata(metadata)
        if not isinstance(original, bytes) or not original or len(original) > self._max_fixture:
            raise VaultQuotaExceeded("Fixture original exceeds the upload limit.")
        _check_native_package(original)
        fixture_id, digest = uuid4().hex, sha256(original).hexdigest()
        receipt = FixtureReceipt(fixture_id, digest, len(original),
                                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document", metadata)
        manifest = _json_bytes({"schema": 1, **asdict(receipt)})
        if len(manifest) > _MANIFEST_LIMIT:
            raise ValueError("Fixture manifest exceeds its private metadata limit.")
        with self._owner_directory(owner, create=True) as (directory, _):
            with _admission_lock(directory):
                listing, used = self._scan(directory)
                if any(not pending.verified for pending in listing.recovery):
                    raise VaultIntegrityError("Unrecognized interrupted uploads require review before another upload.")
                transaction = self._transaction("fixture", fixture_id, {digest + ".docx": original, "manifest.json": manifest})
                if used + len(original) + len(manifest) + len(transaction) > self._max_owner:
                    raise VaultQuotaExceeded("Private fixture vault is full; existing originals were preserved.")
                self._install(directory, fixture_id, {digest + ".docx": original, "manifest.json": manifest},
                              lambda: self._authorize(context, request, owner), kind="fixture")
        return receipt

    @staticmethod
    def _transaction(kind, name, files):
        return _json_bytes({"schema": 1, "kind": kind, "target": name,
                            "files": {filename: len(data) for filename, data in files.items()}})

    @staticmethod
    def _install(parent, name, files, reauthorize, *, kind):
        files = {_TRANSACTION: FixtureVault._transaction(kind, name, files), **files}
        space = os.fstatvfs(parent)
        needed = sum(len(data) + 4096 for data in files.values()) + 4096
        if space.f_bavail * space.f_frsize < needed:
            raise VaultQuotaExceeded("Private storage has insufficient free space; existing files were preserved.")
        staging = ".pending-" + uuid4().hex
        os.mkdir(staging, 0o700, dir_fd=parent)
        fd = os.open(staging, _DIRECTORY_FLAGS, dir_fd=parent)
        installed = False
        try:
            for filename, data in files.items():
                _write_file(fd, filename, data)
            os.fsync(fd)
            reauthorize()
            # The admission lock serializes every writer. Never replace even
            # an empty destination left by an earlier interrupted operation.
            if name in os.listdir(parent):
                raise VaultIntegrityError("An immutable fixture/run already exists.")
            os.rename(staging, name, src_dir_fd=parent, dst_dir_fd=parent)
            installed = True
            os.fsync(parent)
        finally:
            try:
                if not installed:
                    # Only our uncommitted new files are cleaned. No stored fixture,
                    # run, history or original can be selected by this cleanup.
                    for filename in files:
                        try:
                            os.unlink(filename, dir_fd=fd)
                        except FileNotFoundError:
                            pass
                    os.rmdir(staging, dir_fd=parent)
            finally:
                os.close(fd)

    @staticmethod
    def _run_bytes(directory, depth=0):
        if depth > 32 or len(os.listdir(directory)) > 10000:
            raise VaultIntegrityError("Disposable fixture storage needs review before another copy.")
        total = 0
        for name in os.listdir(directory):
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
                try:
                    total += FixtureVault._run_bytes(fd, depth + 1)
                finally:
                    os.close(fd)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total += info.st_size
            else:
                raise VaultIntegrityError("Disposable fixture storage contains an unsafe path.")
        return total

    def replay_copy(self, context, fixture_id, *, run_id, generation) -> ReplayCopy:
        """Copy original bytes into a fresh disposable namespace; do not import.

        The future runner must bind/revalidate its generation before each job
        and call the SAME production importer. This return value is not a reset
        lease, permission to use live standing data, or an AUTH acceptance pass.
        """
        request = AccessRequest("replay-copy", fixture_id, run_id, generation)
        owner = self._authorize(context, request)
        _identifier(run_id)
        _identifier(generation)
        with self._owner_directory(owner) as (directory, _):
            original, _ = self._load(directory, fixture_id)
        lineage = _json_bytes({"schema": 1, "fixture_id": fixture_id,
                               "original_sha256": original.receipt.original_sha256,
                               "run_id": run_id, "generation": generation})
        with self._owner_directory(owner, runs=True, create=True) as (directory, path):
            with _admission_lock(directory):
                files = {"original.docx": original.original, "lineage.json": lineage}
                transaction = self._transaction("run-copy", run_id, files)
                if self._run_bytes(directory) + sum(map(len, files.values())) + len(transaction) > self._max_runs:
                    raise VaultQuotaExceeded("Disposable fixture copies are full; no saved fixture was removed.")
                self._install(directory, run_id, files,
                              lambda: self._authorize(context, request, owner), kind="run-copy")
        return ReplayCopy(original.receipt, run_id, generation, path / run_id / "original.docx")
