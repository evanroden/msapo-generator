"""Persistent idempotency state for Smartsheet PO submissions.

The API route must not create a second row when a user double-clicks, Streamlit
reruns, or the browser is reopened after a partial attachment failure. This
small SQLite store records the deterministic submission key, the created row,
and each attachment that reached Smartsheet.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


class SubmissionStoreError(RuntimeError):
    """Raised when duplicate-prevention state cannot be read or written."""


@dataclass(frozen=True)
class SubmissionClaim:
    allowed: bool
    reason: str
    status: str
    row_id: str | None
    attached: frozenset[str]


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
                    updated_at REAL NOT NULL
                )
                """
            )
            return conn
        except (OSError, sqlite3.Error) as exc:
            raise SubmissionStoreError(
                f"Smartsheet submission history is unavailable: {exc}"
            ) from exc

    @staticmethod
    def _claim_from_row(row: tuple | None, *, allowed: bool, reason: str) -> SubmissionClaim:
        if row is None:
            return SubmissionClaim(allowed, reason, "pending", None, frozenset())
        status, row_id, attached_json = row
        try:
            attached = frozenset(json.loads(attached_json or "[]"))
        except (TypeError, json.JSONDecodeError):
            attached = frozenset()
        return SubmissionClaim(allowed, reason, status, row_id, attached)

    def claim(self, submission_key: str, *, stale_after_seconds: int = 600) -> SubmissionClaim:
        """Claim a submission or safely resume a row created by an earlier attempt."""
        now = time.time()
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status, row_id, attached_json, updated_at "
                    "FROM submissions WHERE submission_key = ?",
                    (submission_key,),
                ).fetchone()

                if row is None:
                    conn.execute(
                        "INSERT INTO submissions "
                        "(submission_key, status, row_id, attached_json, last_error, updated_at) "
                        "VALUES (?, 'pending', NULL, '[]', NULL, ?)",
                        (submission_key, now),
                    )
                    conn.commit()
                    return SubmissionClaim(True, "new", "pending", None, frozenset())

                status, row_id, attached_json, updated_at = row
                if status == "complete":
                    conn.commit()
                    return self._claim_from_row(
                        (status, row_id, attached_json), allowed=False, reason="complete"
                    )

                if row_id:
                    conn.execute(
                        "UPDATE submissions SET status = 'pending', last_error = NULL, "
                        "updated_at = ? WHERE submission_key = ?",
                        (now, submission_key),
                    )
                    conn.commit()
                    return self._claim_from_row(
                        ("pending", row_id, attached_json),
                        allowed=True,
                        reason="resume",
                    )

                if status == "pending" and now - float(updated_at) < stale_after_seconds:
                    conn.commit()
                    return self._claim_from_row(
                        (status, row_id, attached_json),
                        allowed=False,
                        reason="in_progress",
                    )

                conn.execute(
                    "UPDATE submissions SET status = 'pending', last_error = NULL, "
                    "updated_at = ? WHERE submission_key = ?",
                    (now, submission_key),
                )
                conn.commit()
                return self._claim_from_row(
                    ("pending", row_id, attached_json), allowed=True, reason="retry"
                )
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not reserve the Smartsheet submission: {exc}"
            ) from exc

    def record_row(self, submission_key: str, row_id: str | int) -> None:
        self._update(
            "UPDATE submissions SET row_id = ?, status = 'pending', updated_at = ? "
            "WHERE submission_key = ?",
            (str(row_id), time.time(), submission_key),
        )

    def record_attachment(self, submission_key: str, fingerprint: str) -> None:
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT attached_json FROM submissions WHERE submission_key = ?",
                    (submission_key,),
                ).fetchone()
                if row is None:
                    raise SubmissionStoreError("Submission record disappeared before attachment update.")
                try:
                    attached = set(json.loads(row[0] or "[]"))
                except (TypeError, json.JSONDecodeError):
                    attached = set()
                attached.add(fingerprint)
                conn.execute(
                    "UPDATE submissions SET attached_json = ?, updated_at = ? "
                    "WHERE submission_key = ?",
                    (json.dumps(sorted(attached)), time.time(), submission_key),
                )
                conn.commit()
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not record the Smartsheet attachment: {exc}"
            ) from exc

    def finish(self, submission_key: str, status: str, error: str | None = None) -> None:
        if status not in {"complete", "partial", "failed"}:
            raise ValueError(f"Unsupported submission status: {status}")
        self._update(
            "UPDATE submissions SET status = ?, last_error = ?, updated_at = ? "
            "WHERE submission_key = ?",
            (status, error, time.time(), submission_key),
        )

    def get(self, submission_key: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status, row_id, attached_json, last_error, updated_at "
                    "FROM submissions WHERE submission_key = ?",
                    (submission_key,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not read the Smartsheet submission: {exc}"
            ) from exc
        if row is None:
            return None
        status, row_id, attached_json, last_error, updated_at = row
        try:
            attached = json.loads(attached_json or "[]")
        except (TypeError, json.JSONDecodeError):
            attached = []
        return {
            "status": status,
            "row_id": row_id,
            "attached": attached,
            "last_error": last_error,
            "updated_at": updated_at,
        }

    def _update(self, sql: str, params: tuple) -> None:
        try:
            with self._connect() as conn:
                cur = conn.execute(sql, params)
                if cur.rowcount != 1:
                    raise SubmissionStoreError("Smartsheet submission record was not found.")
                conn.commit()
        except sqlite3.Error as exc:
            raise SubmissionStoreError(
                f"Could not update the Smartsheet submission: {exc}"
            ) from exc
