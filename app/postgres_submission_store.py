"""Provisional PostgreSQL Smartsheet claim adapter; NOT used by live submissions.

One PostgreSQL transaction decides claim ownership. No database transaction
stays open during Smartsheet HTTP operations. The rowless "creating" state must
be committed BEFORE row creation is attempted (PR #847 crash-window contract).
No Azure or PostgreSQL connection is made merely by importing this module.
"""
from __future__ import annotations

import json
import uuid
from contextlib import closing, contextmanager

from app.smartsheet_store import SubmissionClaim, SubmissionStoreError

_ALLOWED_FINAL = frozenset({"complete", "partial", "failed", "uncertain"})


def _attachments(value) -> frozenset[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError) as exc:
            raise SubmissionStoreError("Smartsheet attachment evidence is corrupt.") from exc
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SubmissionStoreError("Smartsheet attachment evidence has invalid shape.")
    return frozenset(value)


class PostgresSubmissionStore:
    """Lease-fenced idempotency with database-clock expiry and row locks.

    Supply an ENFRA-authorized psycopg-compatible fresh connection factory.
    This is deliberately not a POSIX/SQLite adapter, and not selected via an
    environment switch until the whole submission/reconciliation API is tested.
    """

    def __init__(self, connection_factory):
        self._connect = connection_factory

    @contextmanager
    def _transaction(self):
        try:
            with closing(self._connect()) as connection:
                with connection:
                    with closing(connection.cursor()) as cursor:
                        yield cursor
        except SubmissionStoreError:
            raise
        except Exception as exc:
            raise SubmissionStoreError(
                "Smartsheet managed submission history is unavailable; submission blocked."
            ) from exc

    @staticmethod
    def _lease_seconds(value):
        return max(30, int(value))

    def claim(self, submission_key: str, *, lease_seconds: int = 300) -> SubmissionClaim:
        token = uuid.uuid4().hex
        seconds = self._lease_seconds(lease_seconds)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO epc_submission_claims "
                "(submission_key, status, row_id, attached_json, updated_at, "
                "lease_token, lease_expires_at, attempts) "
                "VALUES (%s, 'pending', NULL, '[]'::jsonb, NOW(), %s, "
                "NOW() + make_interval(secs => %s), 1) "
                "ON CONFLICT DO NOTHING RETURNING submission_key",
                (submission_key, token, seconds),
            )
            if cursor.fetchone() is not None:
                return SubmissionClaim(
                    True, "new", "pending", None, frozenset(), token
                )
            # Serialize all competing callers to the SAME exact key. Claim is
            # committed before any subsequent remote API request.
            cursor.execute(
                "SELECT status, row_id, attached_json, last_error, lease_token, "
                "(lease_expires_at > NOW()) AS lease_live "
                "FROM epc_submission_claims WHERE submission_key = %s FOR UPDATE",
                (submission_key,),
            )
            row = cursor.fetchone()
            if row is None:
                raise SubmissionStoreError("Smartsheet claim disappeared during reconciliation.")
            status, row_id, attachments, last_error, owner, lease_live = row
            attached = _attachments(attachments)
            if status == "complete":
                return SubmissionClaim(
                    False, "complete", status, row_id, attached, None, last_error
                )
            # A process may have died after the remote POST and before saving
            # its row ID. Lease expiry must NEVER authorize a duplicate POST.
            if status in ("creating", "uncertain") and not row_id:
                return SubmissionClaim(
                    False, "uncertain", status, None, attached, None, last_error
                )
            if owner and lease_live:
                return SubmissionClaim(
                    False, "in_progress", status, row_id, attached, None, last_error
                )
            cursor.execute(
                "UPDATE epc_submission_claims SET status = 'pending', "
                "last_error = NULL, lease_token = %s, "
                "lease_expires_at = NOW() + make_interval(secs => %s), "
                "updated_at = NOW(), attempts = attempts + 1 "
                "WHERE submission_key = %s",
                (token, seconds, submission_key),
            )
            return SubmissionClaim(
                True, "resume" if row_id else "retry", "pending",
                row_id, attached, token,
            )

    def _owned_update(self, submission_key, lease_token, sql, params=()):
        # sql is a LITERAL from this class; all external values are bound.
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE epc_submission_claims SET " + sql +
                " WHERE submission_key = %s AND lease_token = %s "
                "AND lease_expires_at > NOW()",
                (*params, submission_key, lease_token),
            )
            if cursor.rowcount != 1:
                raise SubmissionStoreError(
                    "Smartsheet submission lease expired, or belongs to another worker."
                )

    def renew(self, submission_key, lease_token, *, lease_seconds=300):
        self._owned_update(
            submission_key, lease_token,
            "lease_expires_at = NOW() + make_interval(secs => %s), updated_at = NOW()",
            (self._lease_seconds(lease_seconds),),
        )

    def mark_creating(self, submission_key, lease_token):
        """Commit the danger marker immediately before any row-create HTTP POST."""
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE epc_submission_claims "
                "SET status = 'creating', updated_at = NOW() "
                "WHERE submission_key = %s AND lease_token = %s "
                "AND lease_expires_at > NOW() AND status = 'pending' "
                "AND row_id IS NULL",
                (submission_key, lease_token),
            )
            if cursor.rowcount != 1:
                raise SubmissionStoreError(
                    "Cannot begin remote creation without an owned pending claim."
                )

    def record_row(self, submission_key, lease_token, row_id):
        # Text is intentional; Smartsheet row IDs cannot be JSON floats.
        value = str(row_id)
        if not value:
            raise ValueError("Remote row ID is required.")
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE epc_submission_claims "
                "SET row_id = %s, status = 'pending', last_error = NULL, "
                "updated_at = NOW() "
                "WHERE submission_key = %s AND lease_token = %s "
                "AND lease_expires_at > NOW() "
                "AND (row_id IS NULL OR row_id = %s)",
                (value, submission_key, lease_token, value),
            )
            if cursor.rowcount != 1:
                raise SubmissionStoreError(
                    "Cannot replace a different Smartsheet row or an expired owner."
                )

    def record_attachment(self, submission_key, lease_token, fingerprint):
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT attached_json FROM epc_submission_claims "
                "WHERE submission_key = %s AND lease_token = %s "
                "AND lease_expires_at > NOW() AND row_id IS NOT NULL FOR UPDATE",
                (submission_key, lease_token),
            )
            row = cursor.fetchone()
            if row is None:
                raise SubmissionStoreError(
                    "Cannot attach without an owned, unexpired Smartsheet claim."
                )
            attached = set(_attachments(row[0]))
            attached.add(str(fingerprint))
            cursor.execute(
                "UPDATE epc_submission_claims SET attached_json = %s::jsonb, "
                "updated_at = NOW() WHERE submission_key = %s AND lease_token = %s",
                (json.dumps(sorted(attached)), submission_key, lease_token),
            )
            if cursor.rowcount != 1:
                raise SubmissionStoreError("Smartsheet attachment ownership changed.")

    def finish(self, submission_key, lease_token, status, error=None):
        if status not in _ALLOWED_FINAL:
            raise ValueError("Unsupported Smartsheet final status.")
        self._owned_update(
            submission_key, lease_token,
            "status = %s, last_error = %s, updated_at = NOW(), "
            "lease_token = NULL, lease_expires_at = NULL",
            (status, error),
        )

    def reconcile_row(self, submission_key, row_id):
        """Caller must first verify exactly one remote row by FULL submission key.

        The store cannot verify that external fact. A found row is always
        partial, never complete: attachments still require recheck. Preserve
        previously recorded attachment hashes while invalidating old leases.
        """
        value = str(row_id)
        if not value:
            raise ValueError("Remote row ID is required.")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO epc_submission_claims "
                "(submission_key, status, row_id, attached_json, updated_at, "
                "lease_token, lease_expires_at, attempts) "
                "VALUES (%s, 'partial', %s, '[]'::jsonb, NOW(), NULL, NULL, 0) "
                "ON CONFLICT (submission_key) DO UPDATE SET "
                "row_id = EXCLUDED.row_id, status = 'partial', "
                "last_error = NULL, updated_at = NOW(), "
                "lease_token = NULL, lease_expires_at = NULL",
                (submission_key, value),
            )

    def get(self, submission_key):
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT status, row_id, attached_json, last_error, "
                "EXTRACT(EPOCH FROM updated_at), "
                "EXTRACT(EPOCH FROM lease_expires_at), attempts "
                "FROM epc_submission_claims WHERE submission_key = %s",
                (submission_key,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            status, row_id, raw_attached, error, updated, expires, attempts = row
            return {
                "status": status, "row_id": row_id,
                "attached": sorted(_attachments(raw_attached)),
                "last_error": error,
                "updated_at": float(updated),
                "lease_expires_at": float(expires) if expires is not None else None,
                "attempts": attempts,
            }

    def cleanup(self, *, retention_days=365):
        days = max(30, int(retention_days))
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM epc_submission_claims "
                "WHERE status IN ('complete', 'failed') "
                "AND updated_at < NOW() - make_interval(days => %s)",
                (days,),
            )
            return max(0, cursor.rowcount)
