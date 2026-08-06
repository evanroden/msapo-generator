"""
Per-contract and requester memory for Purchase Order Process Control.

Learns, strictly scoped to one contract at a time:
  - administrator (recipient) emails      -> suggested after >= 5 uses
  - quote contact name+email pairs        -> suggested after >= 5 uses
  - a vendor's known reps                 -> suggested whenever the vendor is
                                             identified (vendors rarely have
                                             more than a handful of reps)

Separately remembers a requester for one anonymous browser after the same
normalized name is used on three distinct prepared PO contexts. Browser tokens
are random and stored only as hashes; Streamlit reruns do not increase counts.

Nothing learned on one contract is ever surfaced on another — the same way
David is only relevant to RRH.

Storage is a SQLite file on the Render persistent disk (mounted at /test1).
Falls back to a repo-local ./data_store for local dev, and degrades gracefully
(no learning, no crash) if the database can't be opened at all.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

SUGGEST_THRESHOLD = 5
REQUESTER_SUGGEST_THRESHOLD = 3

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
CREATE TABLE IF NOT EXISTS device_requesters (
    device_hash   TEXT NOT NULL,
    requester_key TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    use_count     INTEGER NOT NULL DEFAULT 0,
    last_used     REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, requester_key)
);
CREATE TABLE IF NOT EXISTS device_requester_events (
    device_hash   TEXT NOT NULL,
    context_id    TEXT NOT NULL,
    requester_key TEXT NOT NULL,
    recorded_at   REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, context_id)
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


def _requester_key(name: str | None) -> str:
    return _norm_name(name).casefold()


def _device_hash(device_token: str | None) -> str:
    token = (device_token or "").strip()
    if not token or len(token) > 200:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


def record_device_requester(
    *, device_token: str | None, requester_name: str | None, context_id: str | None
) -> int:
    """Record one requester use for one prepared PO on one browser.

    The opaque browser token is hashed before storage. A PO context can count only
    once, so Streamlit reruns and repeated page visits do not inflate the threshold.
    Correcting the requester on the same context moves that one use to the corrected
    name. Returns the current use count, or 0 when memory is unavailable/invalid.
    """
    device = _device_hash(device_token)
    name = _norm_name(requester_name)
    requester = _requester_key(name)
    context = (context_id or "").strip()
    if not device or not requester or not context or len(name) > 160 or len(context) > 200:
        return 0

    conn = _connect()
    if conn is None:
        return 0
    now = time.time()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT requester_key FROM device_requester_events "
            "WHERE device_hash=? AND context_id=?",
            (device, context),
        ).fetchone()
        if prior and prior[0] != requester:
            conn.execute(
                "UPDATE device_requesters SET use_count=use_count-1 "
                "WHERE device_hash=? AND requester_key=?",
                (device, prior[0]),
            )
            conn.execute(
                "DELETE FROM device_requesters WHERE device_hash=? AND requester_key=? "
                "AND use_count<=0",
                (device, prior[0]),
            )

        if not prior or prior[0] != requester:
            conn.execute(
                "INSERT INTO device_requester_events "
                "(device_hash,context_id,requester_key,recorded_at) VALUES (?,?,?,?) "
                "ON CONFLICT(device_hash,context_id) DO UPDATE SET "
                "requester_key=excluded.requester_key, recorded_at=excluded.recorded_at",
                (device, context, requester, now),
            )
            conn.execute(
                "INSERT INTO device_requesters "
                "(device_hash,requester_key,display_name,use_count,last_used) "
                "VALUES (?,?,?,1,?) "
                "ON CONFLICT(device_hash,requester_key) DO UPDATE SET "
                "display_name=excluded.display_name, use_count=use_count+1, "
                "last_used=excluded.last_used",
                (device, requester, name, now),
            )
        else:
            conn.execute(
                "UPDATE device_requesters SET display_name=?, last_used=? "
                "WHERE device_hash=? AND requester_key=?",
                (name, now, device, requester),
            )

        row = conn.execute(
            "SELECT use_count FROM device_requesters "
            "WHERE device_hash=? AND requester_key=?",
            (device, requester),
        ).fetchone()
        conn.commit()
        return int(row[0]) if row else 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        conn.close()


def remembered_device_requester(device_token: str | None) -> str:
    """Most-recent requester with at least three distinct PO contexts."""
    device = _device_hash(device_token)
    if not device:
        return ""
    conn = _connect()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT display_name FROM device_requesters "
            "WHERE device_hash=? AND use_count>=? "
            "ORDER BY last_used DESC, use_count DESC LIMIT 1",
            (device, REQUESTER_SUGGEST_THRESHOLD),
        ).fetchone()
        return str(row[0]) if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


def forget_device_requester(device_token: str | None) -> bool:
    """Forget requester learning for this browser without affecting other memory."""
    device = _device_hash(device_token)
    if not device:
        return False
    conn = _connect()
    if conn is None:
        return False
    try:
        with conn:
            conn.execute("DELETE FROM device_requester_events WHERE device_hash=?", (device,))
            conn.execute("DELETE FROM device_requesters WHERE device_hash=?", (device,))
        return True
    except Exception:
        return False
    finally:
        conn.close()
