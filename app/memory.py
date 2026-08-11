"""
Per-contract and requester memory for Purchase Order Process Control.

Learns, strictly scoped to one contract at a time:
  - administrator (recipient) emails      -> suggested after >= 5 uses
  - quote contact name+email pairs        -> suggested after >= 5 uses
  - a vendor's known reps                 -> suggested whenever the vendor is
                                             identified (vendors rarely have
                                             more than a handful of reps)

The active streamlined flow remembers the last requester/asset manager for
each account on each anonymous browser after one completed package. Browser
tokens are random and stored only as hashes; Streamlit reruns do not increase
counts. This prevents an RRH manager from becoming the default requester on a
different ENFRA account while removing repeated name entry for the same user.

The older three-use device_requesters tables/functions remain readable for
backward compatibility, but the active UI no longer uses or exposes them.

After a valid reimbursement package is generated, the same browser/account
pair also remembers the reviewed employee number, Employee Home Business Unit,
administrator, mail choice, and default JDE coding. Receipt files and
transaction data are never written to this store.

Nothing learned on one contract is ever surfaced on another — the same way
David is only relevant to RRH.

Storage is a SQLite file on the Render persistent disk (mounted at /test1).
Falls back to a repo-local ./data_store for local dev, and degrades gracefully
(no learning, no crash) if the database can't be opened at all.
"""

from __future__ import annotations

import hashlib
import os
import re
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
CREATE TABLE IF NOT EXISTS vendor_contact_events (
    contract   TEXT NOT NULL,
    context_id TEXT NOT NULL,
    vendor     TEXT NOT NULL,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    recorded_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (contract, context_id)
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
CREATE TABLE IF NOT EXISTS device_account_managers (
    device_hash  TEXT NOT NULL,
    account_key  TEXT NOT NULL,
    manager_key  TEXT NOT NULL,
    display_name TEXT NOT NULL,
    use_count    INTEGER NOT NULL DEFAULT 0,
    last_used    REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, account_key, manager_key)
);
CREATE TABLE IF NOT EXISTS device_account_manager_events (
    device_hash TEXT NOT NULL,
    account_key TEXT NOT NULL,
    context_id  TEXT NOT NULL,
    manager_key TEXT NOT NULL,
    recorded_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, account_key, context_id)
);
CREATE TABLE IF NOT EXISTS device_expense_profiles (
    device_hash          TEXT NOT NULL,
    account_key          TEXT NOT NULL,
    employee_name        TEXT NOT NULL,
    employee_number      TEXT NOT NULL,
    employee_home_bu     TEXT NOT NULL,
    approver_name        TEXT NOT NULL,
    approver_email       TEXT NOT NULL,
    mail_destination     TEXT NOT NULL,
    satellite_office     TEXT NOT NULL,
    allocation_kind      TEXT NOT NULL,
    job_number           TEXT NOT NULL,
    service_center       TEXT NOT NULL,
    account_cost_type    TEXT NOT NULL,
    cost_code_or_wo_type TEXT NOT NULL,
    work_order_number    TEXT NOT NULL,
    company_number       TEXT NOT NULL,
    department_number    TEXT NOT NULL,
    ou_number            TEXT NOT NULL,
    gl_account_number    TEXT NOT NULL,
    last_used            REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, account_key)
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


def _account_key(account: str | None) -> str:
    return " ".join((account or "").split()).casefold()


def _device_hash(device_token: str | None) -> str:
    token = (device_token or "").strip()
    if not token or len(token) > 200:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _norm_vendor(vendor: str | None) -> str:
    return " ".join((vendor or "").split()).lower()


_LEGAL_VENDOR_SUFFIXES = frozenset(
    {
        "co",
        "company",
        "corp",
        "corporation",
        "inc",
        "incorporated",
        "llc",
        "lp",
        "ltd",
        "limited",
        "plc",
    }
)


def _vendor_match_key(vendor: str | None) -> str:
    """Normalize punctuation and legal suffixes without fuzzy name guessing."""
    words = re.findall(r"[a-z0-9]+", _norm_vendor(vendor))
    while words and words[-1] in _LEGAL_VENDOR_SUFFIXES:
        words.pop()
    return " ".join(words)


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


def record_vendor_contact(
    *,
    contract: str,
    vendor: str | None,
    contact_name: str | None,
    contact_email: str | None,
    context_id: str | None,
) -> int:
    """Remember one verified vendor representative for an account and vendor.

    A generated package counts once. Regenerating the same package is
    idempotent, while correcting its vendor representative moves the event to
    the corrected pair instead of teaching both values.
    """
    vend = _norm_vendor(vendor)
    name = _norm_name(contact_name)
    email = _norm_email(contact_email)
    context = (context_id or "").strip()
    if (
        not contract
        or not vend
        or not name
        or not email
        or not _looks_like_email(email)
        or not context
        or len(vend) > 240
        or len(name) > 160
        or len(context) > 200
    ):
        return 0

    conn = _connect()
    if conn is None:
        return 0
    now = time.time()
    current = (vend, name, email)
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT vendor,name,email FROM vendor_contact_events "
            "WHERE contract=? AND context_id=?",
            (contract, context),
        ).fetchone()

        if prior and tuple(prior) != current:
            conn.execute(
                "UPDATE vendor_contacts SET count=count-1 "
                "WHERE contract=? AND vendor=? AND name=? AND email=?",
                (contract, prior[0], prior[1], prior[2]),
            )
            conn.execute(
                "DELETE FROM vendor_contacts WHERE contract=? AND vendor=? "
                "AND name=? AND email=? AND count<=0",
                (contract, prior[0], prior[1], prior[2]),
            )

        if not prior or tuple(prior) != current:
            conn.execute(
                "INSERT INTO vendor_contact_events "
                "(contract,context_id,vendor,name,email,recorded_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(contract,context_id) DO UPDATE SET "
                "vendor=excluded.vendor,name=excluded.name,email=excluded.email,"
                "recorded_at=excluded.recorded_at",
                (contract, context, vend, name, email, now),
            )
            conn.execute(
                "INSERT INTO vendor_contacts "
                "(contract,vendor,name,email,count,last_used) VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(contract,vendor,name,email) DO UPDATE SET "
                "count=count+1,last_used=excluded.last_used",
                (contract, vend, name, email, now),
            )
        else:
            conn.execute(
                "UPDATE vendor_contact_events SET recorded_at=? "
                "WHERE contract=? AND context_id=?",
                (now, contract, context),
            )
            conn.execute(
                "UPDATE vendor_contacts SET last_used=? WHERE contract=? "
                "AND vendor=? AND name=? AND email=?",
                (now, contract, vend, name, email),
            )

        row = conn.execute(
            "SELECT count FROM vendor_contacts WHERE contract=? AND vendor=? "
            "AND name=? AND email=?",
            (contract, vend, name, email),
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
            "SELECT vendor,name,email,count,last_used FROM vendor_contacts "
            "WHERE contract=? ORDER BY count DESC, last_used DESC",
            (contract,),
        ).fetchall()
        exact = [row for row in rows if row[0] == vend]
        if exact:
            matched = exact
        else:
            match_key = _vendor_match_key(vend)
            matched = [
                row
                for row in rows
                if match_key and _vendor_match_key(row[0]) == match_key
            ]
        seen: set[tuple[str, str]] = set()
        result: list[tuple[str, str]] = []
        for _, name, email, _, _ in matched:
            pair = (str(name), str(email))
            if pair not in seen:
                seen.add(pair)
                result.append(pair)
        return result
    except Exception:
        return []
    finally:
        conn.close()


def remembered_vendor_contact(
    contract: str,
    vendor: str | None,
    *,
    contact_name: str | None = None,
    contact_email: str | None = None,
) -> tuple[str, str]:
    """Return the best verified representative for this account and vendor.

    A contact value extracted from the current quote can select the matching
    historical pair. Otherwise the most-used, most-recent pair wins. No result
    is ever borrowed from another account or a merely similar vendor name.
    """
    reps = vendor_reps(contract, vendor)
    if not reps:
        return "", ""
    wanted_email = _norm_email(contact_email)
    wanted_name = _requester_key(contact_name)
    if wanted_email:
        for name, email in reps:
            if _norm_email(email) == wanted_email:
                return name, email
    if wanted_name:
        for name, email in reps:
            if _requester_key(name) == wanted_name:
                return name, email
    return reps[0]


def record_device_account_manager(
    *,
    device_token: str | None,
    account: str | None,
    manager_name: str | None,
    context_id: str | None,
) -> int:
    """Remember one requester/asset manager for one device and ENFRA account.

    A verified PO context counts once. Correcting the name on the same context
    moves that event instead of double-counting. The latest valid name becomes
    the next default for this exact device+account pair after the first use.
    """
    device = _device_hash(device_token)
    account_key = _account_key(account)
    name = _norm_name(manager_name)
    manager = _requester_key(name)
    context = (context_id or "").strip()
    if (
        not device
        or not account_key
        or not manager
        or not context
        or len(name) > 160
        or len(account_key) > 240
        or len(context) > 200
    ):
        return 0

    conn = _connect()
    if conn is None:
        return 0
    now = time.time()
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT manager_key FROM device_account_manager_events "
            "WHERE device_hash=? AND account_key=? AND context_id=?",
            (device, account_key, context),
        ).fetchone()
        if prior and prior[0] != manager:
            conn.execute(
                "UPDATE device_account_managers SET use_count=use_count-1 "
                "WHERE device_hash=? AND account_key=? AND manager_key=?",
                (device, account_key, prior[0]),
            )
            conn.execute(
                "DELETE FROM device_account_managers "
                "WHERE device_hash=? AND account_key=? AND manager_key=? "
                "AND use_count<=0",
                (device, account_key, prior[0]),
            )

        if not prior or prior[0] != manager:
            conn.execute(
                "INSERT INTO device_account_manager_events "
                "(device_hash,account_key,context_id,manager_key,recorded_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(device_hash,account_key,context_id) "
                "DO UPDATE SET manager_key=excluded.manager_key, "
                "recorded_at=excluded.recorded_at",
                (device, account_key, context, manager, now),
            )
            conn.execute(
                "INSERT INTO device_account_managers "
                "(device_hash,account_key,manager_key,display_name,use_count,last_used) "
                "VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(device_hash,account_key,manager_key) DO UPDATE SET "
                "display_name=excluded.display_name, use_count=use_count+1, "
                "last_used=excluded.last_used",
                (device, account_key, manager, name, now),
            )
        else:
            conn.execute(
                "UPDATE device_account_managers SET display_name=?, last_used=? "
                "WHERE device_hash=? AND account_key=? AND manager_key=?",
                (name, now, device, account_key, manager),
            )

        row = conn.execute(
            "SELECT use_count FROM device_account_managers "
            "WHERE device_hash=? AND account_key=? AND manager_key=?",
            (device, account_key, manager),
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


def remembered_device_account_manager(
    device_token: str | None, account: str | None
) -> str:
    """Return the latest requester for this exact browser and account."""
    device = _device_hash(device_token)
    account_key = _account_key(account)
    if not device or not account_key:
        return ""
    conn = _connect()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT display_name FROM device_account_managers "
            "WHERE device_hash=? AND account_key=? AND use_count>=1 "
            "ORDER BY last_used DESC, use_count DESC LIMIT 1",
            (device, account_key),
        ).fetchone()
        return str(row[0]) if row else ""
    except Exception:
        return ""
    finally:
        conn.close()


_EXPENSE_PROFILE_FIELDS = (
    "employee_name",
    "employee_number",
    "employee_home_bu",
    "approver_name",
    "approver_email",
    "mail_destination",
    "satellite_office",
    "allocation_kind",
    "job_number",
    "service_center",
    "account_cost_type",
    "cost_code_or_wo_type",
    "work_order_number",
    "company_number",
    "department_number",
    "ou_number",
    "gl_account_number",
)


def record_expense_profile(
    *,
    device_token: str | None,
    account: str | None,
    values: dict[str, object],
) -> bool:
    """Remember reviewed employee/admin/default coding for this browser+account.

    Receipt images, merchants, dates, descriptions, and amounts are deliberately
    excluded. The profile is written only after the operator generates a valid
    package and the latest verified values replace the prior defaults.
    """
    device = _device_hash(device_token)
    account_key = _account_key(account)
    if not device or not account_key:
        return False
    cleaned = {
        field: " ".join(str(values.get(field, "") or "").split())
        for field in _EXPENSE_PROFILE_FIELDS
    }
    if any(len(value) > 240 for value in cleaned.values()):
        return False
    if cleaned["approver_email"] and not _looks_like_email(
        cleaned["approver_email"].lower()
    ):
        return False

    conn = _connect()
    if conn is None:
        return False
    columns = ",".join(_EXPENSE_PROFILE_FIELDS)
    placeholders = ",".join("?" for _ in _EXPENSE_PROFILE_FIELDS)
    assignments = ",".join(f"{field}=excluded.{field}" for field in _EXPENSE_PROFILE_FIELDS)
    try:
        with conn:
            conn.execute(
                "INSERT INTO device_expense_profiles "
                f"(device_hash,account_key,{columns},last_used) "
                f"VALUES (?,?,{placeholders},?) "
                "ON CONFLICT(device_hash,account_key) DO UPDATE SET "
                f"{assignments},last_used=excluded.last_used",
                (
                    device,
                    account_key,
                    *(cleaned[field] for field in _EXPENSE_PROFILE_FIELDS),
                    time.time(),
                ),
            )
        return True
    except Exception:
        return False
    finally:
        conn.close()


def remembered_expense_profile(
    device_token: str | None,
    account: str | None,
) -> dict[str, str]:
    """Return the latest expense defaults for this exact browser+account."""
    device = _device_hash(device_token)
    account_key = _account_key(account)
    if not device or not account_key:
        return {}
    conn = _connect()
    if conn is None:
        return {}
    columns = ",".join(_EXPENSE_PROFILE_FIELDS)
    try:
        row = conn.execute(
            f"SELECT {columns} FROM device_expense_profiles "
            "WHERE device_hash=? AND account_key=?",
            (device, account_key),
        ).fetchone()
        if not row:
            return {}
        return dict(zip(_EXPENSE_PROFILE_FIELDS, map(str, row)))
    except Exception:
        return {}
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
