"""Global admission for initial fixture copies in disposable QA namespaces.

This metadata-only registry bounds staged source/lineage reservations, not all
generated workspace data. It grants no access to fixture originals and performs
no authentication or report save. Generic reservations survive failed writes;
production copy installation can safely roll back a clean failure. Reservations
are reclaimed after their QA generation has disappeared or been replaced by a valid
newer marker, or when another browser's namespace has been idle for 24 hours
(owner policy, #292); shared originals are never removed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
import re
from uuid import uuid4

from app import monthly_report_fixture_vault as storage
from app import monthly_report_testing as testing


MAX_ACTIVE_COPY_BYTES = 128 * 1024 * 1024
MIN_FREE_BYTES = 256 * 1024 * 1024
_BUCKET = "_enfra_fixture_run_admission_v1"
_INDEX = "reservations.json"
_INDEX_LIMIT = 2 * 1024 * 1024
_MAX_RESERVATIONS = 4096
_MARKER = (_BUCKET + "|1").encode("ascii")
_PENDING_INSTALL = "pending-install.json"
_PENDING_LIMIT = 2 * _INDEX_LIMIT + 4096


@dataclass(frozen=True)
class CopyReservation:
    scope: str
    generation: str
    added_bytes: int


def _load(directory):
    names = set(os.listdir(directory))
    # An abandoned atomic metadata temporary does not authorize data cleanup or
    # replacement. Surface it for review rather than guessing which index won.
    if names - {storage._MARKER, storage._LOCK, _INDEX, _PENDING_INSTALL}:
        raise storage.VaultIntegrityError("Fixture admission metadata requires recovery review.")
    if _INDEX not in names:
        return ()
    try:
        value = json.loads(storage._read_file(directory, _INDEX, _INDEX_LIMIT))
        if (not isinstance(value, dict) or set(value) != {"schema", "reservations"}
                or type(value["schema"]) is not int or value["schema"] != 1
                or not isinstance(value["reservations"], list)
                or len(value["reservations"]) > _MAX_RESERVATIONS):
            raise ValueError("Invalid reservation index")
        return _records(value["reservations"])
    except (TypeError, ValueError) as exc:
        raise storage.VaultIntegrityError("Fixture admission metadata is invalid.") from exc


def _records(value):
    if not isinstance(value, list) or len(value) > _MAX_RESERVATIONS:
        raise ValueError("Invalid reservation list")
    records, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"scope", "generation", "added_bytes"}:
            raise ValueError("Invalid reservation record")
        record = CopyReservation(**item)
        storage._identifier(record.scope)
        storage._identifier(record.generation)
        identity = (record.scope, record.generation)
        if (identity in seen or type(record.added_bytes) is not int
                or not 1 <= record.added_bytes <= MAX_ACTIVE_COPY_BYTES):
            raise ValueError("Invalid reservation size/identity")
        seen.add(identity)
        records.append(record)
    return tuple(records)


def fixture_install_receipt(files):
    """Exact bytes expected at the production Starting-report commit boundary."""
    from app.monthly_report_fixture_runs import _ENTRY

    if set(files) != {"source.docx", "lineage.json"}:
        raise ValueError("Unexpected fixture installation files.")
    committed = {storage._TRANSACTION: storage.FixtureVault._transaction(
        "fixture-starting-report", _ENTRY, files), **files}
    return {name: {"size": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in committed.items()}


def _validate_receipt(receipt, reservation):
    limits = {"source.docx": 32 * 1024 * 1024, "lineage.json": 128 * 1024,
              storage._TRANSACTION: 4096}
    if not isinstance(receipt, dict) or set(receipt) != set(limits):
        raise ValueError("Invalid fixture install receipt")
    for name, item in receipt.items():
        if (not isinstance(item, dict) or set(item) != {"size", "sha256"}
                or type(item["size"]) is not int or not 1 <= item["size"] <= limits[name]
                or not isinstance(item["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None):
            raise ValueError("Invalid fixture install file receipt")
    if sum(item["size"] for item in receipt.values()) != reservation.added_bytes:
        raise ValueError("Fixture install receipt does not match its reservation")


def _write_pending(directory, before, after, reservation, receipt):
    value = {"schema": 1, "before": [asdict(item) for item in before],
             "after": [asdict(item) for item in after],
             "reservation": asdict(reservation), "files": receipt}
    encoded = storage._json_bytes(value)
    if len(encoded) > _PENDING_LIMIT:
        raise storage.VaultQuotaExceeded("Fixture installation recovery metadata is full.")
    temporary = ".install-" + uuid4().hex + ".json"
    try:
        storage._write_file(directory, temporary, encoded)
        os.replace(temporary, _PENDING_INSTALL, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _read_pending(directory):
    try:
        value = json.loads(storage._read_file(directory, _PENDING_INSTALL, _PENDING_LIMIT))
        if (not isinstance(value, dict)
                or set(value) != {"schema", "before", "after", "reservation", "files"}
                or type(value["schema"]) is not int or value["schema"] != 1):
            raise ValueError("Invalid pending fixture installation")
        before, after = _records(value["before"]), _records(value["after"])
        reservation, = _records([value["reservation"]])
        if (reservation in before or after.count(reservation) != 1
                or sum(item.added_bytes for item in after) > MAX_ACTIVE_COPY_BYTES
                or any(item not in before for item in after if item != reservation)
                or any((item.scope, item.generation) == (reservation.scope, reservation.generation)
                       for item in before)):
            raise ValueError("Pending fixture installation changed unrelated reservations")
        _validate_receipt(value["files"], reservation)
        return before, after, reservation, value["files"]
    except (KeyError, TypeError, ValueError) as exc:
        raise storage.VaultIntegrityError("Fixture installation recovery metadata is invalid.") from exc


def _committed_install(base, reservation, receipt):
    """No-follow, read-only witness; uncertainty never authorizes deletion.

    The generation may have been explicitly reset, but it is never recreated.
    A crash-left .pending directory needs that browser's scoped reset. A full
    published entry is checked against hashes fixed before the index changed.
    """
    from app.monthly_report_fixture_runs import _STAGING, _ENTRY

    try:
        bucket = os.open(testing._BUCKET, storage._DIRECTORY_FLAGS, dir_fd=base)
    except FileNotFoundError:
        os.fsync(base)
        return False
    try:
        try:
            namespace = os.open(reservation.scope, storage._DIRECTORY_FLAGS, dir_fd=bucket)
        except FileNotFoundError:
            os.fsync(bucket)
            os.fsync(base)
            return False
        try:
            marker = storage._read_file(namespace, testing._SENTINEL, 1024)
            if marker != (reservation.scope + "|" + reservation.generation).encode("ascii"):
                try:
                    identity, generation = marker.decode("ascii").split("|")
                    storage._identifier(generation)
                    if identity != reservation.scope or generation == reservation.generation:
                        raise ValueError("Mismatched generation")
                except (UnicodeError, ValueError) as exc:
                    raise storage.VaultIntegrityError("The pending fixture generation cannot be verified.") from exc
                # A valid newer generation proves an explicit scoped reset,
                # but persist its directory before releasing the old receipt.
                for descriptor in (namespace, bucket, base):
                    os.fsync(descriptor)
                return False
            if _STAGING not in os.listdir(namespace):
                for descriptor in (namespace, bucket, base):
                    os.fsync(descriptor)
                return False
            expected = storage._json_bytes({"schema": 1, "kind": "fixture-starting-report",
                                            "scope": reservation.scope, "generation": reservation.generation})
            with storage._marked_dir(namespace, _STAGING, expected, False) as staging:
                names = set(os.listdir(staging))
                if storage._MARKER in names and names <= {storage._MARKER, storage._LOCK}:
                    # _install removes uncommitted files in finally, without
                    # syncing that removal. Persist this negative witness so
                    # partial bytes cannot reappear outside the restored budget.
                    for descriptor in (staging, namespace, bucket, base):
                        os.fsync(descriptor)
                    return False
                if names != {storage._MARKER, storage._LOCK, _ENTRY}:
                    raise storage.VaultIntegrityError(
                        "Interrupted fixture installation requires its browser's scoped reset before another admission.")
                entry = os.open(_ENTRY, storage._DIRECTORY_FLAGS, dir_fd=staging)
                try:
                    if set(os.listdir(entry)) != set(receipt):
                        raise storage.VaultIntegrityError("The pending fixture commit has unexpected files.")
                    for name, item in receipt.items():
                        raw = storage._read_file(entry, name, item["size"])
                        if len(raw) != item["size"] or sha256(raw).hexdigest() != item["sha256"]:
                            raise storage.VaultIntegrityError("The pending fixture commit does not match its receipt.")
                    # _install can raise after publication when its parent
                    # fsync fails. Visibility alone must not release old work.
                    # Acknowledge the committed directory and its ancestors
                    # before treating this receipt as a durable replacement.
                    for descriptor in (entry, staging, namespace, bucket, base):
                        os.fsync(descriptor)
                    return True
                finally:
                    os.close(entry)
        finally:
            os.close(namespace)
    finally:
        os.close(bucket)


def _recover_pending(base_path, base, directory):
    """Settle the source transaction before index-only tombstone recovery."""
    if _PENDING_INSTALL not in os.listdir(directory):
        return
    before, after, reservation, receipt = _read_pending(directory)
    if _load(directory) not in (before, after):
        raise storage.VaultIntegrityError("Fixture installation recovery found an unexpected reservation index.")
    selected = after if _committed_install(base, reservation, receipt) else before
    # Even when already visible, require durability acknowledgement before
    # restoring/discarding old copies or removing the recovery journal.
    _save(directory, selected)
    testing.recover_set_aside(base_path, {(item.scope, item.generation) for item in selected})
    try:
        bucket = os.open(testing._BUCKET, storage._DIRECTORY_FLAGS, dir_fd=base)
    except FileNotFoundError:
        bucket = None
    if bucket is not None:
        try:
            identities = {(item.scope, item.generation) for item in before}
            for name in os.listdir(bucket):
                normalized = (testing._SET_ASIDE + name[len(testing._DISCARDING):]
                              if name.startswith(testing._DISCARDING) else name)
                owner = testing._SET_ASIDE_NAME.fullmatch(normalized)
                if owner and owner.groups() in identities:
                    raise OSError("Fixture recovery could not settle an existing isolated copy; retry later.")
            os.fsync(bucket)
        finally:
            os.close(bucket)
    os.unlink(_PENDING_INSTALL, dir_fd=directory)
    os.fsync(directory)


def _generation_exists(base, reservation):
    """Inspect the existing marker only; never create/adopt/reset a namespace."""
    try:
        bucket = os.open(testing._BUCKET, storage._DIRECTORY_FLAGS, dir_fd=base)
    except FileNotFoundError:
        return False
    try:
        try:
            namespace = os.open(reservation.scope, storage._DIRECTORY_FLAGS, dir_fd=bucket)
        except FileNotFoundError:
            return False
        try:
            try:
                marker = storage._read_file(namespace, testing._SENTINEL, 1024).decode("ascii")
            except (FileNotFoundError, UnicodeError) as exc:
                raise storage.VaultIntegrityError("Existing fixture namespace has no valid generation marker.") from exc
            values = marker.split("|")
            if len(values) != 2 or values[0] != reservation.scope:
                raise storage.VaultIntegrityError("Fixture namespace ownership does not match its reservation.")
            try:
                storage._identifier(values[1])
            except ValueError as exc:
                raise storage.VaultIntegrityError("Fixture namespace generation is invalid.") from exc
            return values[1] == reservation.generation
        finally:
            os.close(namespace)
    finally:
        os.close(bucket)


def _save(directory, reservations):
    encoded = storage._json_bytes({"schema": 1, "reservations": [asdict(item) for item in reservations]})
    if len(encoded) > _INDEX_LIMIT:
        raise storage.VaultQuotaExceeded("Fixture admission metadata is full; reset completed runs before staging another.")
    temporary = ".reservation-" + uuid4().hex + ".json"
    try:
        storage._write_file(directory, temporary, encoded)
        os.replace(temporary, _INDEX, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


@contextmanager
def admit_run_copy(context, added_bytes: int, *, install_receipt=None):
    """Reserve exact new source/lineage/transaction bytes around their install.

    Call only inside the already selected QA context. ``added_bytes`` must
    include the install transaction marker as well as source and lineage bytes.
    Keep the guarded operation limited to writing that copy; parsing/rendering
    should happen afterwards. The cross-process admission lock is held through
    that write so two accepted copies cannot spend the same free disk space.

    Generic callers conservatively retain reservations, including on failure.
    Production fixture staging supplies an exact install receipt: a clean
    failed installation then rolls back only its own reservation and restores
    idle copies; a verified committed copy remains reserved for diagnosis.
    """
    from app.monthly_report_fixture_runs import validate_run

    root = validate_run(context)
    if type(added_bytes) is not int or not 1 <= added_bytes <= MAX_ACTIVE_COPY_BYTES:
        raise storage.VaultQuotaExceeded("Fixture copy exceeds the global staged-source budget.")
    if root.name != context.scope or root.parent.name != testing._BUCKET:
        raise storage.VaultIntegrityError("Fixture admission requires its explicit isolated namespace.")
    reservation = CopyReservation(context.scope, context.generation, added_bytes)
    if install_receipt is not None:
        _validate_receipt(install_receipt, reservation)
    with storage._root(root.parent.parent) as base:
        with storage._marked_dir(base, _BUCKET, _MARKER, True) as directory:
            with storage._admission_lock(directory):
                validate_run(context)  # A waiting caller may have been reset.
                _recover_pending(root.parent.parent, base, directory)
                existing = _load(directory)
                testing.recover_set_aside(root.parent.parent, {(item.scope, item.generation) for item in existing})
                set_aside = {}
                try:
                    retained = []
                    for item in existing:
                        if not _generation_exists(base, item):
                            continue
                        # Idle copies are only set aside here; they are deleted once
                        # this admission is committed and restored if anything fails.
                        tombstone = (None if item.scope == context.scope
                                     else testing.set_aside_idle(root.parent.parent, item.scope, item.generation))
                        if tombstone is None:
                            retained.append(item)
                        else:
                            set_aside[tombstone] = item
                    if install_receipt is not None:
                        _check_admission(directory, reservation, retained)
                        # The old index still counts every moved copy. Persist
                        # the moves before a durable journal/new index can omit
                        # them; otherwise a lost rename could leave live data
                        # outside the recovered budget after a host failure.
                        bucket = os.open(testing._BUCKET, storage._DIRECTORY_FLAGS, dir_fd=base)
                        try:
                            os.fsync(bucket)
                            os.fsync(base)
                        finally:
                            os.close(bucket)
                        _write_pending(directory, existing, (*retained, reservation), reservation, install_receipt)
                    _admit(directory, context, reservation, retained)
                    try:
                        # A stale lease cannot begin its write, including if reset
                        # occurred while durable reservation metadata was installed.
                        validate_run(context)
                    except BaseException:
                        if set_aside and install_receipt is None:
                            # Legacy generic copies have no installation witness.
                            kept = (*retained, *set_aside.values())
                            _save(directory, (*kept, reservation) if len(kept) < _MAX_RESERVATIONS else kept)
                        raise
                except BaseException:
                    if _PENDING_INSTALL in os.listdir(directory):
                        _recover_pending(root.parent.parent, base, directory)
                        raise
                    # Put back exactly the set-aside copies the index on disk still
                    # lists; an unreadable index leaves them to the next admission.
                    listed = _listed(directory)
                    if listed is not None:
                        testing.recover_set_aside(root.parent.parent, listed)
                    raise
                try:
                    yield reservation
                finally:
                    if install_receipt is not None:
                        _recover_pending(root.parent.parent, base, directory)
                    else:
                        # Legacy committed reservation: a crash leaves old
                        # copies unlisted, so the next admission deletes them.
                        for tombstone in set_aside:
                            testing.discard_set_aside(tombstone)


def _listed(directory):
    """The (scope, generation) pairs the index on disk lists now, or None if unreadable."""
    try:
        return {(item.scope, item.generation) for item in _load(directory)}
    except (OSError, storage.VaultIntegrityError):
        return None


def _admit(directory, context, reservation, retained):
    """Check the generation, budget and free space, then commit the reservation."""
    _check_admission(directory, reservation, retained)
    _save(directory, (*retained, reservation))


def _check_admission(directory, reservation, retained):
    if any((item.scope, item.generation) == (reservation.scope, reservation.generation) for item in retained):
        raise storage.VaultIntegrityError("This fixture generation already reserved a copy; reset this run before retrying.")
    if (len(retained) >= _MAX_RESERVATIONS
            or sum(item.added_bytes for item in retained) + reservation.added_bytes > MAX_ACTIVE_COPY_BYTES):
        raise storage.VaultQuotaExceeded("Active fixture copies use the 128 MiB budget; reset completed test runs "
                                         "before staging another. Copies unused for 24 hours are cleared automatically.")
    available = os.fstatvfs(directory)
    if available.f_bavail * available.f_frsize < MIN_FREE_BYTES + reservation.added_bytes:
        raise storage.VaultQuotaExceeded("Fixture staging needs 256 MiB of free space after the new source copy.")
