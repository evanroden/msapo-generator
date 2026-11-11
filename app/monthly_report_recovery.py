"""Scoped active monthly-report draft recovery.

This stores only registered editable fields for an active working report.
It intentionally does not store uploads, generated files, or report snapshots.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time

from app.memory import _connect

_RECOVERY_TTL_NOTE = "No automatic expiry is enforced here; cleanup policy is separate."


def _identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS monthly_active_drafts (
            browser_hash TEXT NOT NULL,
            account_hash TEXT NOT NULL,
            report_key TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (browser_hash, account_hash, report_key)
        )
        """
    )


def save_active_draft(browser_token: str, account_key: str, report_key: str, payload: dict[str, object]) -> bool:
    if not browser_token or not account_key or not report_key:
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        _ensure_table(conn)
        import json
        conn.execute(
            "INSERT OR REPLACE INTO monthly_active_drafts VALUES (?, ?, ?, ?, ?)",
            (_identity(browser_token), _identity(account_key), report_key, json.dumps(payload), time.time()),
        )
        conn.commit()
        return True
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False
    finally:
        conn.close()


def load_active_draft(browser_token: str, account_key: str, report_key: str) -> dict[str, object] | None:
    if not browser_token or not account_key or not report_key:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT payload FROM monthly_active_drafts WHERE browser_hash=? AND account_hash=? AND report_key=?",
            (_identity(browser_token), _identity(account_key), report_key),
        ).fetchone()
        if not row:
            return None
        import json
        value = json.loads(row[0])
        return value if isinstance(value, dict) else None
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        conn.close()
