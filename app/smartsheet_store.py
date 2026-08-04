"""Persistent, fail-closed idempotency state for Smartsheet PO submissions.

A Smartsheet write is not transactionally coupled to local SQLite. The store
therefore records an ownership lease, the remote row ID, attachment fingerprints,
and an explicit ``uncertain`` state for writes whose remote outcome is unknown.
Only the lease owner may mutate a claimed submission.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


class SubmissionStoreError(RuntimeError):
    """Raised when duplicate-prevention state cannot be trusted."""


@dataclass(frozen=True)
class SubmissionClaim:
    allowed: bool
    reason: str
    status: str
    row_id: str | None
    attached: frozenset[str]
    lease_token: str | None
    last_error: str | None = None


_ALLOWED_FINAL_STATUSES = {"complete", "partial", "failed", "uncertain"}


class SubmissionStore:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def from_environment(cls) -> "SubmissionStore":
        root = Path(os.getenv("EPC_DATA_DIR", "./data_store"))
        return cls(root / "smartsheet_submissions.db")

    def _connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    submission_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    row_id TEXT,
                    attached_json TEXT NOT NULL DEFAULT '[]',
                    last_error TEXT,
                    updated_at REAL NOT NULL,
                    lease_token TEXT,
                    lease_expires_at REAL,
                    attempts INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(submissions)").fetchall()
            }
            if "lease_token" not in columns:
                conn.execute("ALTER TABLE submissions ADD COLUMN lease_token TEXT")
            if "lease_expires_at" not in columns:
                conn.execute("ALTER TABLE submissions ADD COLUMN lease_expires_at REAL")
            if "attempts" not in columns:
                conn.execute(
                    "ALTER TABLE submissions ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
                )
            return conn
        except (OSError, sqlite3.Error) as exc:
            raise SubmissionStoreError(
                f"Smartsheet submission history is unavailable: {exc}"
            ) from exc

    @staticmethod
    def _decode_attached(raw: str | None) -> frozenset[str]:
        try:
            value = json.loads(raw or "[]")
        except (TypeError, json.JSONDecodeError) as exc:
            raise SubmissionStoreError(
                "Smartsheet attachment history is corrupt; submission is blocked to "
                "avoid duplicate attachments."
            ) from exc
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise SubmissionStoreError(
                "Smartsheet attachment history has an invalid shape; submission is blocked."
            )
        return frozenset(value)

    def claim(
        self,
        submission_key: str,
        *,
        lease_seconds: int = 300,
    ) -> SubmissionClaim:
        """Reserve one submission attempt with an expiring ownership lease.

        ``uncertain`` without a row ID is never retried automatically: the remote
        service may have created a row even though the response was lost.
        """
        now = time.time()
        token = uuid.uuid4().hex
        expires = now + max(30, int(lease_seconds))
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status, row_id, attached_json, last_error, "
                    "lease_token, lease_expires_at FROM submissions "
                    "WHERE submission_key = ?",
                    (submission_key,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        "INSERT INTO submissions "
                        "(submission_key, status, row_id, attached_json, last_error, "
                        "updated_at, lease_token, lease_expires_at, attempts) "
                        "VALUES (?, 'pending', NULL, '[]', NULL, ?, ?, ?, 1)",
                        (submission_key, now, token, expires),
                    )
                    conn.commit()
                    return SubmissionClaim(
                        True, "new", "pending", None, frozenset(), token
                    )

                status, row_id, attached_json, last_error, owner, lease_expires = row
                attached = self._decode_attached(attached_json)
                if status == "complete":
                    conn.commit()
                    return SubmissionClaim(
                        False, "complete", status, row_id, attached, None, last_error
                    )

                if status == "uncertain" and not row_id:
                    conn.commit()
                    return SubmissionClaim(
                        False, "uncertain", status, None, attached, None, last_error
                    )

                if owner and lease_expires and float(lease_expires) > now:
                    conn.commit()
                    return SubmissionClaim(
                        False, "in_progress", status, row_id, attached, None, last_error
                    )

                reason = "resume" if row_id else "retry"
                conn.execute(
                    "UPDATE submissions SET status = 'pending', last_error = NULL, "
                    "updated_at = ?, lease_token = ?, lease_expires_at = ?, "
                    "attempts = attempts + 1 WHERE submission_key = ?",
                    (now, token, expires, submission_key),
                )
                conn.commit()
                return SubmissionClaim(
                    True, reason, "pending", row_id, attached, token
                )
        except SubmissionStoreError:
            raise
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not reserve the Smartsheet submission: {exc}"
            ) from exc

    def _owned_update(
        self,
        submission_key: str,
        lease_token: str,
        sql_fragment: str,
        params: tuple,
    ) -> None:
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    f"UPDATE submissions SET {sql_fragment} "
                    "WHERE submission_key = ? AND lease_token = ?",
                    (*params, submission_key, lease_token),
                )
                if cur.rowcount != 1:
                    raise SubmissionStoreError(
                        "The Smartsheet submission lease expired or belongs to another request."
                    )
                conn.commit()
        except SubmissionStoreError:
            raise
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not update the Smartsheet submission: {exc}"
            ) from exc

    def renew(self, submission_key: str, lease_token: str, *, lease_seconds: int = 300) -> None:
        now = time.time()
        self._owned_update(
            submission_key,
            lease_token,
            "updated_at = ?, lease_expires_at = ?",
            (now, now + max(30, int(lease_seconds))),
        )

    def record_row(
        self, submission_key: str, lease_token: str, row_id: str | int
    ) -> None:
        self._owned_update(
            submission_key,
            lease_token,
            "row_id = ?, status = 'pending', last_error = NULL, updated_at = ?",
            (str(row_id), time.time()),
        )

    def record_attachment(
        self, submission_key: str, lease_token: str, fingerprint: str
    ) -> None:
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT attached_json FROM submissions "
                    "WHERE submission_key = ? AND lease_token = ?",
                    (submission_key, lease_token),
                ).fetchone()
                if row is None:
                    raise SubmissionStoreError(
                        "The Smartsheet submission lease expired before attachment update."
                    )
                attached = set(self._decode_attached(row[0]))
                attached.add(fingerprint)
                conn.execute(
                    "UPDATE submissions SET attached_json = ?, updated_at = ? "
                    "WHERE submission_key = ? AND lease_token = ?",
                    (
                        json.dumps(sorted(attached)),
                        time.time(),
                        submission_key,
                        lease_token,
                    ),
                )
                conn.commit()
        except SubmissionStoreError:
            raise
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not record the Smartsheet attachment: {exc}"
            ) from exc

    def finish(
        self,
        submission_key: str,
        lease_token: str,
        status: str,
        error: str | None = None,
    ) -> None:
        if status not in _ALLOWED_FINAL_STATUSES:
            raise ValueError(f"Unsupported submission status: {status}")
        self._owned_update(
            submission_key,
            lease_token,
            "status = ?, last_error = ?, updated_at = ?, lease_token = NULL, "
            "lease_expires_at = NULL",
            (status, error, time.time()),
        )

    def reconcile_row(self, submission_key: str, row_id: str | int) -> None:
        """Adopt one remotely verified row, even after local-state loss.

        This upsert is safe only because the caller has verified the full
        submission-key cell on exactly one remote row.
        """
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO submissions (
                        submission_key, status, row_id, attached_json, last_error,
                        updated_at, lease_token, lease_expires_at, attempts
                    ) VALUES (?, 'partial', ?, '[]', NULL, ?, NULL, NULL, 0)
                    ON CONFLICT(submission_key) DO UPDATE SET
                        row_id = excluded.row_id,
                        status = 'partial',
                        last_error = NULL,
                        updated_at = excluded.updated_at,
                        lease_token = NULL,
                        lease_expires_at = NULL
                    """,
                    (submission_key, str(row_id), now),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not reconcile the Smartsheet row: {exc}"
            ) from exc

    def get(self, submission_key: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status, row_id, attached_json, last_error, updated_at, "
                    "lease_expires_at, attempts FROM submissions WHERE submission_key = ?",
                    (submission_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not read the Smartsheet submission: {exc}"
            ) from exc
        if row is None:
            return None
        status, row_id, attached_json, last_error, updated_at, lease_expires, attempts = row
        return {
            "status": status,
            "row_id": row_id,
            "attached": sorted(self._decode_attached(attached_json)),
            "last_error": last_error,
            "updated_at": updated_at,
            "lease_expires_at": lease_expires,
            "attempts": attempts,
        }

    def cleanup(self, *, retention_days: int = 365) -> int:
        """Delete old completed/failed records; retain partial/uncertain records."""
        cutoff = time.time() - max(30, retention_days) * 86400
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "DELETE FROM submissions WHERE status IN ('complete', 'failed') "
                    "AND updated_at < ?",
                    (cutoff,),
                )
                conn.commit()
                return max(0, cur.rowcount)
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not clean old Smartsheet submission history: {exc}"
            ) from exc
