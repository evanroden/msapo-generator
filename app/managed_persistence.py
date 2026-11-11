"""Candidate PostgreSQL persistence boundary for Azure App Service.

This module is intentionally NOT selected by the Render runtime. A05 must approve
the managed database and credentials; A09 owns data translation and dry-run
reconciliation. In particular, a PostgreSQL row is not a POSIX Path.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import closing
from dataclasses import dataclass
from typing import Callable


MAX_RECORD_BYTES = 64 * 1024 * 1024


class ManagedStorageError(RuntimeError):
    """A transactional store could not prove the result of an operation."""


class RevisionConflict(ManagedStorageError):
    """A second writer changed the exact record since it was read."""


class RecordIntegrityError(ManagedStorageError):
    """A saved record failed integrity verification; never overwrite it."""


@dataclass(frozen=True)
class RecordKey:
    """Existing identities are kept literally, not slugged into a filesystem path.

    A blank site means contract-wide state; a blank user_scope means shared
    standing content. Callers must authorize these scopes before using a key.
    """

    namespace: str
    contract: str
    site: str
    user_scope: str
    record_id: str

    def __post_init__(self) -> None:
        for label in ("namespace", "contract", "site", "user_scope", "record_id"):
            value = getattr(self, label)
            if (not isinstance(value, str) or len(value) > 256
                    or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)):
                raise ValueError(f"Invalid {label} identity.")
        if not self.namespace or not self.contract or not self.record_id:
            raise ValueError("Namespace, contract and existing record ID are required.")

    def sql_values(self) -> tuple[str, str, str, str, str]:
        return self.namespace, self.contract, self.site, self.user_scope, self.record_id


@dataclass(frozen=True)
class VersionedRecord:
    key: RecordKey
    revision: int
    raw: bytes
    sha256: str


class PostgresRecordStore:
    """Exact-byte JSON heads and immutable versions with database-level CAS.

    connection_factory returns a fresh psycopg-compatible connection; its
    connection context commits on success and rolls back on error. The caller
    supplies Entra/managed-identity connection configuration, never a hardcoded
    connection string. All SQL identifiers are fixed; user data is parameterized.
    """

    def __init__(self, connection_factory: Callable):
        self._connection_factory = connection_factory

    @staticmethod
    def _payload(raw: bytes) -> tuple[bytes, str]:
        if not isinstance(raw, bytes) or len(raw) > MAX_RECORD_BYTES:
            raise ValueError("A bounded JSON byte payload is required.")
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Invalid saved JSON payload.") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Saved JSON payload must be an object.")
        return raw, hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _checked(key: RecordKey, row) -> VersionedRecord | None:
        if row is None:
            return None
        revision, raw, claimed_sha = row
        raw = bytes(raw)  # PostgreSQL BYTEA may be a memoryview.
        digest = hashlib.sha256(raw).hexdigest()
        if (type(revision) is not int or revision < 1 or digest != claimed_sha
                or len(raw) > MAX_RECORD_BYTES):
            raise RecordIntegrityError("Saved revision integrity check failed.")
        return VersionedRecord(key, revision, raw, digest)

    def read(self, key: RecordKey, *, revision: int | None = None) -> VersionedRecord | None:
        if not isinstance(key, RecordKey):
            raise TypeError("A scoped RecordKey is required.")
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError("A positive historical revision is required.")
        table = "epc_record_heads" if revision is None else "epc_record_versions"
        sql = (
            f"SELECT revision, payload_bytes, payload_sha256 FROM {table} "
            "WHERE namespace = %s AND contract = %s AND site = %s "
            "AND user_scope = %s AND record_id = %s"
        )
        params = key.sql_values()
        if revision is not None:
            sql += " AND revision = %s"
            params += (revision,)
        try:
            with closing(self._connection_factory()) as connection:
                with connection:
                    with closing(connection.cursor()) as cursor:
                        cursor.execute(sql, params)
                        return self._checked(key, cursor.fetchone())
        except RecordIntegrityError:
            raise
        except Exception as exc:
            raise ManagedStorageError("Could not read the managed saved record.") from exc

    def write(self, key: RecordKey, raw: bytes, *, expected_revision: int) -> VersionedRecord:
        if not isinstance(key, RecordKey):
            raise TypeError("A scoped RecordKey is required.")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("Expected revision must be a nonnegative integer.")
        raw, digest = self._payload(raw)
        values = key.sql_values()
        try:
            with closing(self._connection_factory()) as connection:
                with connection:  # Head and version must commit or roll back TOGETHER.
                    with closing(connection.cursor()) as cursor:
                        if expected_revision == 0:
                            cursor.execute(
                                "INSERT INTO epc_record_heads "
                                "(namespace, contract, site, user_scope, record_id, "
                                "revision, payload_bytes, payload_sha256) "
                                "VALUES (%s, %s, %s, %s, %s, 1, %s, %s) "
                                "ON CONFLICT DO NOTHING RETURNING revision",
                                (*values, raw, digest),
                            )
                        else:
                            cursor.execute(
                                "UPDATE epc_record_heads "
                                "SET revision = revision + 1, payload_bytes = %s, "
                                "payload_sha256 = %s, updated_at = NOW() "
                                "WHERE namespace = %s AND contract = %s AND site = %s "
                                "AND user_scope = %s AND record_id = %s "
                                "AND revision = %s RETURNING revision",
                                (raw, digest, *values, expected_revision),
                            )
                        row = cursor.fetchone()
                        if row is None:
                            raise RevisionConflict(
                                "A different writer saved this record; reload before retrying."
                            )
                        next_revision = row[0]
                        if next_revision != expected_revision + 1:
                            raise RecordIntegrityError("Unexpected managed revision result.")
                        cursor.execute(
                            "INSERT INTO epc_record_versions "
                            "(namespace, contract, site, user_scope, record_id, "
                            "revision, payload_bytes, payload_sha256) "
                            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                            (*values, next_revision, raw, digest),
                        )
            return VersionedRecord(key, next_revision, raw, digest)
        except (RevisionConflict, RecordIntegrityError):
            raise
        except Exception as exc:
            raise ManagedStorageError(
                "Managed save outcome is unavailable; reread before retrying."
            ) from exc

    def list_record_ids(
        self, *, namespace: str, contract: str, site: str = "", user_scope: str = ""
    ) -> tuple[str, ...]:
        # Validation is identical for list and read; no global cross-contract list.
        RecordKey(namespace, contract, site, user_scope, "_validation")
        try:
            with closing(self._connection_factory()) as connection:
                with connection:
                    with closing(connection.cursor()) as cursor:
                        cursor.execute(
                            "SELECT record_id FROM epc_record_heads "
                            "WHERE namespace = %s AND contract = %s AND site = %s "
                            "AND user_scope = %s ORDER BY record_id",
                            (namespace, contract, site, user_scope),
                        )
                        return tuple(row[0] for row in cursor.fetchall())
        except Exception as exc:
            raise ManagedStorageError("Could not list scoped managed records.") from exc
