"""Global admission for initial fixture copies in disposable QA namespaces.

This metadata-only registry bounds staged source/lineage reservations, not all
generated workspace data. It grants no access to fixture originals and performs
no authentication or report save. A reservation survives a failed write and is
reclaimed after its QA generation has disappeared or been replaced by a valid
newer marker, or when another browser's namespace has been idle for 24 hours
(owner policy, #292); shared originals are never removed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
import os
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


@dataclass(frozen=True)
class CopyReservation:
    scope: str
    generation: str
    added_bytes: int


def _load(directory):
    names = set(os.listdir(directory))
    # An abandoned atomic metadata temporary does not authorize data cleanup or
    # replacement. Surface it for review rather than guessing which index won.
    if names - {storage._MARKER, storage._LOCK, _INDEX}:
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
        records, seen = [], set()
        for item in value["reservations"]:
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
    except (TypeError, ValueError) as exc:
        raise storage.VaultIntegrityError("Fixture admission metadata is invalid.") from exc


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
def admit_run_copy(context, added_bytes: int):
    """Reserve exact new source/lineage/transaction bytes around their install.

    Call only inside the already selected QA context. ``added_bytes`` must
    include the install transaction marker as well as source and lineage bytes.
    Keep the guarded operation limited to writing that copy; parsing/rendering
    should happen afterwards. The cross-process admission lock is held through
    that write so two accepted copies cannot spend the same free disk space.

    No reservation is released on normal return or failure. An existing same-
    generation reservation requires a scoped reset before another initial copy.
    """
    from app.monthly_report_fixture_runs import validate_run

    root = validate_run(context)
    if type(added_bytes) is not int or not 1 <= added_bytes <= MAX_ACTIVE_COPY_BYTES:
        raise storage.VaultQuotaExceeded("Fixture copy exceeds the global staged-source budget.")
    if root.name != context.scope or root.parent.name != testing._BUCKET:
        raise storage.VaultIntegrityError("Fixture admission requires its explicit isolated namespace.")
    reservation = CopyReservation(context.scope, context.generation, added_bytes)
    with storage._root(root.parent.parent) as base:
        with storage._marked_dir(base, _BUCKET, _MARKER, True) as directory:
            with storage._admission_lock(directory):
                validate_run(context)  # A waiting caller may have been reset.
                existing = _load(directory)
                testing.recover_set_aside(root.parent.parent, {(item.scope, item.generation) for item in existing})
                set_aside = []
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
                            set_aside.append(tombstone)
                    _admit(directory, context, reservation, retained)
                except BaseException:
                    for tombstone in set_aside:
                        try:
                            testing.restore_set_aside(root.parent.parent, tombstone)
                        except OSError:
                            pass  # recovered by the next admission
                    raise
                # Committed: a crash from here on leaves set-aside copies the index
                # no longer lists, which the next admission deletes.
                for tombstone in set_aside:
                    testing.discard_set_aside(tombstone)
                # A stale lease cannot begin its write, including if reset
                # occurred while durable reservation metadata was installed.
                validate_run(context)
                yield reservation


def _admit(directory, context, reservation, retained):
    """Check the generation, budget and free space, then commit the reservation."""
    if any((item.scope, item.generation) == (reservation.scope, reservation.generation) for item in retained):
        raise storage.VaultIntegrityError("This fixture generation already reserved a copy; reset this run before retrying.")
    if (len(retained) >= _MAX_RESERVATIONS
            or sum(item.added_bytes for item in retained) + reservation.added_bytes > MAX_ACTIVE_COPY_BYTES):
        raise storage.VaultQuotaExceeded("Active fixture copies use the 128 MiB budget; reset completed test runs "
                                         "before staging another. Copies unused for 24 hours are cleared automatically.")
    available = os.fstatvfs(directory)
    if available.f_bavail * available.f_frsize < MIN_FREE_BYTES + reservation.added_bytes:
        raise storage.VaultQuotaExceeded("Fixture staging needs 256 MiB of free space after the new source copy.")
    _save(directory, (*retained, reservation))
