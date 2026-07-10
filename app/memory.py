"""
Per-contract memory for Email Process Control.

Learns, strictly scoped to one contract at a time:
  - administrator (recipient) emails      -> suggested after >= 5 uses
  - quote contact name+email pairs        -> suggested after >= 5 uses
  - a vendor's known reps                 -> suggested whenever the vendor is
                                             identified (vendors rarely have
                                             more than a handful of reps)

Nothing learned on one contract is ever surfaced on another — the same way
David is only relevant to RRH.

Storage is a SQLite file on the Render persistent disk (mounted at /test1).
Falls back to a repo-local ./data_store for local dev, and degrades gracefully
(no learning, no crash) if the database can't be opened at all.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

SUGGEST_THRESHOLD = 5

_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_emails (
    contract TEXT NOT NULL,
    email    TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, email)
);
CREATE TABLE IF NOT EXISTS contacts (
    contract TEXT NOT NULL,
    name     TEXT NOT NULL,
    email    TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, name, email)
);
CREATE TABLE IF NOT EXISTS vendor_contacts (
    contract TEXT NOT NULL,
    vendor   TEXT NOT NULL,
    name     TEXT NOT NULL,
    email    TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    last_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, vendor, name, email)
);
"""


def _data_dir() -> Path:
    env = os.getenv("EPC_DATA_DIR")
    if env:
        return Path(env)
    mounted = Path("/test1")  # the Render persistent disk's mount path
    if mounted.is_dir():
        return mounted
    return Path(__file__).resolve().parent.parent / "data_store"


def _db_path() -> Path:
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "epc_memory.db"


def _connect() -> sqlite3.Connection | None:
    """Open (and initialize) the database; None if storage is unavailable."""
    try:
        conn = sqlite3.connect(_db_path(), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn
    except Exception:
        return None


def _norm_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _norm_name(name: str | None) -> str:
    return " ".join((name or "").split())


def _norm_vendor(vendor: str | None) -> str:
    return " ".join((vendor or "").split()).lower()


def _looks_like_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1] and " " not in email


def record_send(
    *,
    contract: str,
    admin_email: str | None = None,
    vendor: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
) -> bool:
    """Record one send's details for a contract. Returns False if storage is
    unavailable (the app keeps working, it just doesn't learn)."""
    if not contract:
        return False
    conn = _connect()
    if conn is None:
        return False
    now = time.time()
    admin = _norm_email(admin_email)
    name = _norm_name(contact_name)
    cemail = _norm_email(contact_email)
    vend = _norm_vendor(vendor)
    try:
        with conn:
            if admin and _looks_like_email(admin):
                conn.execute(
                    "INSERT INTO admin_emails (contract,email,count,last_used) VALUES (?,?,1,?) "
                    "ON CONFLICT(contract,email) DO UPDATE SET count=count+1, last_used=?",
                    (contract, admin, now, now),
                )
            # Contact pairs only count when the name AND a plausible email match up
            if name and cemail and _looks_like_email(cemail):
                conn.execute(
                    "INSERT INTO contacts (contract,name,email,count,last_used) VALUES (?,?,?,1,?) "
                    "ON CONFLICT(contract,name,email) DO UPDATE SET count=count+1, last_used=?",
                    (contract, name, cemail, now, now),
                )
                if vend:
                    conn.execute(
                        "INSERT INTO vendor_contacts (contract,vendor,name,email,count,last_used) VALUES (?,?,?,?,1,?) "
                        "ON CONFLICT(contract,vendor,name,email) DO UPDATE SET count=count+1, last_used=?",
                        (contract, vend, name, cemail, now, now),
                    )
        return True
    except Exception:
        return False
    finally:
        conn.close()


def suggest_admin_emails(contract: str) -> list[str]:
    """Admin emails used >= SUGGEST_THRESHOLD times on THIS contract only."""
    conn = _connect()
    if conn is None or not contract:
        return []
    try:
        rows = conn.execute(
            "SELECT email FROM admin_emails WHERE contract=? AND count>=? "
            "ORDER BY count DESC, last_used DESC",
            (contract, SUGGEST_THRESHOLD),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def suggest_contacts(contract: str) -> list[tuple[str, str]]:
    """(name, email) pairs used >= SUGGEST_THRESHOLD times on THIS contract."""
    conn = _connect()
    if conn is None or not contract:
        return []
    try:
        rows = conn.execute(
            "SELECT name, email FROM contacts WHERE contract=? AND count>=? "
            "ORDER BY count DESC, last_used DESC",
            (contract, SUGGEST_THRESHOLD),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def vendor_reps(contract: str, vendor: str | None) -> list[tuple[str, str]]:
    """Every rep we've EVER seen for this vendor on THIS contract (no
    threshold — a vendor rarely has more than a few reps)."""
    vend = _norm_vendor(vendor)
    conn = _connect()
    if conn is None or not contract or not vend:
        return []
    try:
        rows = conn.execute(
            "SELECT name, email FROM vendor_contacts WHERE contract=? AND vendor=? "
            "ORDER BY count DESC, last_used DESC",
            (contract, vend),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()
