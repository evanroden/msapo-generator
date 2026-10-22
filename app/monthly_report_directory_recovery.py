"""Explicit, conflict-checked restoration of unreadable directory heads."""
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
import re
import stat

from app import monthly_report_directory as directory, monthly_report_library as library

MAX_HISTORY_FILES = 1000
MAX_RECOVERY_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class RecoveryReview:
    storage_key: str
    context: str
    fingerprint: str
    versions: tuple[directory.DirectoryState, ...]
    unavailable_versions: tuple[int, ...]
    next_revision: int
    damaged_sha256: str
    damaged_bytes: bytes = field(repr=False)


def review_context():
    from app.monthly_report_testing import generation
    root = library._root()  # Revalidate the namespace before reading its lease.
    return str(root.resolve()) + "|" + (generation() or "live")


def _path(storage_key):
    library._valid_key(storage_key)
    root = library._root() / "directory"
    path = root / storage_key
    library._qa_path_guard(path)
    if any(p.is_symlink() for p in (root, path, path / "history", path / "recovery")):
        raise library.LibraryError("Linked directory storage cannot be recovered here; no records were changed.")
    return path


def _bytes(path, limit):
    library._qa_path_guard(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise library.LibraryError("Recovery requires an ordinary saved file; no records were changed.")
    # Bound the actual read as well as stat: a replaced file can grow between them.
    with path.open("rb") as stream:
        raw = stream.read(min(limit, library.MAX_JSON_BYTES) + 1)
    if len(raw) > min(limit, library.MAX_JSON_BYTES):
        raise library.LibraryError("Directory recovery exceeds its read budget; no records were changed.")
    return raw


def _decoded(raw):
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("schema") != 1:
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise library.LibraryError("This saved directory version could not be read.") from exc


def _identity(value, storage_key):
    # Even a partially damaged record must not claim a different identity.
    if isinstance(value.get("contract"), str):
        if library._contract_directory(value["contract"]) != storage_key:
            raise library.LibraryError("Directory history identifies a different contract; no records were changed.")


def inspect_recovery(storage_key):
    """Read a bounded history snapshot without modifying or guessing any data."""
    path = _path(storage_key)
    damaged = _bytes(path / "manifest.json", library.MAX_JSON_BYTES)
    try:
        value = _decoded(damaged)
    except library.LibraryError:
        value = None
    if value is not None:
        _identity(value, storage_key)
        try:
            directory._state(value)
        except library.LibraryError:
            pass
        else:
            raise library.RevisionConflict("This directory can now be read. Reload it before choosing a recovery action.")

    # Reserve every revision filename, including damaged history, so recovery
    # never overwrites an old version or an interrupted write's history entry.
    files = []
    for file in (path / "history").glob("*.json"):
        if len(files) >= MAX_HISTORY_FILES:
            raise library.LibraryError("Directory history exceeds the recovery review limit.")
        if not re.fullmatch(r"[0-9]{8}\.json", file.name) or int(file.stem) < 1:
            raise library.LibraryError("Directory history has an unrecognized revision; no records were changed.")
        files.append(file)
    if not files:
        raise library.LibraryError("No saved directory history is available to recover. The unreadable record was retained.")
    budget = MAX_RECOVERY_BYTES - len(damaged)
    context = review_context()
    digest = hashlib.sha256(context.encode() + b"\0" + str(path.resolve()).encode() + b"\0" + damaged)
    versions, unavailable = [], []
    for file in sorted(files):
        raw = _bytes(file, budget)
        budget -= len(raw)
        digest.update(file.name.encode() + b"\0" + hashlib.sha256(raw).digest())
        try:
            value = _decoded(raw)
        except library.LibraryError:
            unavailable.append(int(file.stem))
            continue
        _identity(value, storage_key)
        try:
            prior = directory._state(value)
            if prior.revision != int(file.stem) or not (prior.sites or prior.contract_contacts):
                raise ValueError("Invalid historical revision or empty directory")
            directory._validate_records(prior.contract, prior.sites, prior.contract_contacts)
            if prior.source_sha256 and not re.fullmatch(r"[0-9a-f]{64}", prior.source_sha256):
                raise ValueError("Invalid source fingerprint")
        except ValueError:
            unavailable.append(int(file.stem))
            continue
        versions.append(prior)
    if not versions:
        raise library.LibraryError("No readable, valid directory version is available to recover. All existing files were retained.")
    next_revision = max(int(file.stem) for file in files) + 1
    if next_revision > 99_999_999:
        raise library.LibraryError("Directory revision limit reached; no records were changed.")
    return RecoveryReview(storage_key, context, digest.hexdigest(), tuple(versions), tuple(unavailable),
                          next_revision, hashlib.sha256(damaged).hexdigest(), damaged)


def recover_directory(review, revision, *, actor, confirmed):
    actor = library._confirmation(actor, confirmed)
    # Derive the lock from verified on-disk history, never an arbitrary caller label.
    current = inspect_recovery(review.storage_key)
    identity = directory._contract_identity(current.versions[0].contract)
    lock = library._root() / "directory_locks" / library._contract_directory(identity)
    with library._locked(lock):
        current = inspect_recovery(review.storage_key)
        if current.fingerprint != review.fingerprint:
            raise library.RevisionConflict("Directory data or history changed after review. Inspect recovery history again.")
        prior = next((state for state in current.versions if type(revision) is int and state.revision == revision), None)
        if prior is None:
            raise ValueError("Choose a readable version from the reviewed directory history.")
        path = _path(review.storage_key)
        preserved = path / "recovery" / (current.damaged_sha256 + ".bin")
        if preserved.exists():
            if _bytes(preserved, library.MAX_JSON_BYTES) != current.damaged_bytes:
                raise library.LibraryError("The retained damaged record could not be verified; no directory was replaced.")
        else:
            library._atomic_write(preserved, current.damaged_bytes)
        restored = replace(prior, revision=current.next_revision, actor=actor, updated_at=library._now(),
                           action=f"recover:{revision}:{current.damaged_sha256}")
        encoded = library._json({"schema": 1, **asdict(restored)})
        history = path / "history" / f"{restored.revision:08d}.json"
        if history.exists():
            raise library.RevisionConflict("Directory history changed during recovery. Inspect it again.")
        library._atomic_write(history, encoded)
        library._atomic_write(path / "manifest.json", encoded)
        if directory.load_directory(restored.contract, include_archived=True) != restored:
            raise library.LibraryError("Recovered directory could not be verified. Reload before retrying.")
        return restored
