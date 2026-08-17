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
pair also remembers the reviewed administrator and mail choice. Each confirmed
employee name/number pair is kept separately for that browser and account, so
returning to an employee's exact normalized name recalls the right number even
after another employee prepares a report. Employee Home Business Unit and
baseline coding are derived from the account in the active UI. Receipt files,
transaction data, mileage entries, and signature confirmation are never written
to this store. Legacy coding columns remain in the table for backward-compatible
reads.

Confirmed expense approver name/email pairs form a separate account-scoped
directory. They are shared across authorized browsers using the same account so
employees can search a familiar approver by name; they never cross account
boundaries. A per-draft event key prevents reruns from inflating history and
moves a corrected draft away from an obsolete approver.

Nothing learned on one contract is ever surfaced on another; even administrator
details remain scoped to the exact account.

Storage is a SQLite file on the Render persistent disk (mounted at /test1).
Falls back to a repo-local ./data_store for local dev, and degrades gracefully
(no learning, no crash) if the database can't be opened at all.

EVERY public function here is failure-swallowing by design: memory is a
convenience and must never take down a PO or an expense report the operator has
already produced. The cost of that choice is that ALL failures in this module
are silent -- an unwritable disk, a schema mismatch and "nothing learned yet"
are indistinguishable to every caller, and none of them logs. When device
recall stops working in production, suspect this module even though nothing
raised. See _SCHEMA for the specific silent failure that schema drift causes.

Callers: app/web_ui.py (account-manager and vendor-representative recall on the
PO flow) and app/expense_ui.py (expense profile, employee number, and the
account-scoped approver directory). Both feed the browser token produced by
app/device_identity.py; "" is a valid token meaning "no device", and every
device-scoped function returns empty for it rather than sharing one bucket.

Single-instance only. The idempotency guarantees below rest on SQLite
transactions against one local file (FM-G05); learning must move to a shared
transactional database before this app is ever scaled past one instance.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path

# Read only by suggest_admin_emails/suggest_contacts, which have no caller in
# the app today. Not a live tuning knob -- changing it changes nothing visible.
SUGGEST_THRESHOLD = 5
# The LEGACY requester threshold, still read by remembered_device_requester.
# The active flow uses record_device_account_manager, which remembers after ONE
# ready package for a device+account pair; that reversal is deliberate (see the
# module docstring and FM-C07) and must not be "restored" to a threshold.
REQUESTER_SUGGEST_THRESHOLD = 3

# Re-executed on EVERY connection, which is why every statement is
# CREATE TABLE IF NOT EXISTS.
#
# CREATE TABLE IF NOT EXISTS is a NO-OP on an older table, so changing a schema
# below still requires a migration. _migrate_expense_approver_identity handles
# the one historical change this module has needed; any future field or key
# change needs an equivalent guarded migration, not only an edit here.
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
CREATE TABLE IF NOT EXISTS device_expense_employees (
    device_hash    TEXT NOT NULL,
    account_key    TEXT NOT NULL,
    employee_key   TEXT NOT NULL,
    employee_name  TEXT NOT NULL,
    employee_number TEXT NOT NULL,
    last_used      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (device_hash, account_key, employee_key)
);
CREATE TABLE IF NOT EXISTS expense_approvers (
    account_key    TEXT NOT NULL,
    approver_key   TEXT NOT NULL,
    display_name   TEXT NOT NULL,
    email          TEXT NOT NULL,
    use_count      INTEGER NOT NULL DEFAULT 0,
    last_used      REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account_key, approver_key, email)
);
CREATE TABLE IF NOT EXISTS expense_approver_events (
    account_key  TEXT NOT NULL,
    context_id   TEXT NOT NULL,
    approver_key TEXT NOT NULL,
    email        TEXT NOT NULL,
    recorded_at  REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account_key, context_id)
);
"""


def _migrate_expense_approver_identity(conn: sqlite3.Connection) -> None:
    """Upgrade the name-only approver key without losing confirmed history."""
    def _shape() -> tuple[tuple[str, ...], set[str]]:
        directory_info = conn.execute(
            "PRAGMA table_info(expense_approvers)"
        ).fetchall()
        event_info = conn.execute(
            "PRAGMA table_info(expense_approver_events)"
        ).fetchall()
        primary_key = tuple(
            row[1]
            for row in sorted(directory_info, key=lambda row: row[5])
            if row[5]
        )
        return primary_key, {row[1] for row in event_info}

    expected_key = ("account_key", "approver_key", "email")
    primary_key, event_columns = _shape()
    if primary_key == expected_key and "email" in event_columns:
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        # Another connection may have completed the migration while this one
        # waited for the write lock. Re-read under the lock before renaming.
        primary_key, event_columns = _shape()
        if primary_key == expected_key and "email" in event_columns:
            conn.commit()
            return
        if primary_key != ("account_key", "approver_key") or "email" in event_columns:
            raise sqlite3.OperationalError("Unsupported expense approver schema")
        conn.execute("ALTER TABLE expense_approvers RENAME TO expense_approvers_legacy")
        conn.execute(
            "ALTER TABLE expense_approver_events "
            "RENAME TO expense_approver_events_legacy"
        )
        conn.execute(
            "CREATE TABLE expense_approvers ("
            "account_key TEXT NOT NULL,approver_key TEXT NOT NULL,"
            "display_name TEXT NOT NULL,email TEXT NOT NULL,"
            "use_count INTEGER NOT NULL DEFAULT 0,last_used REAL NOT NULL DEFAULT 0,"
            "PRIMARY KEY (account_key,approver_key,email))"
        )
        conn.execute(
            "CREATE TABLE expense_approver_events ("
            "account_key TEXT NOT NULL,context_id TEXT NOT NULL,"
            "approver_key TEXT NOT NULL,email TEXT NOT NULL,"
            "recorded_at REAL NOT NULL DEFAULT 0,"
            "PRIMARY KEY (account_key,context_id))"
        )
        conn.execute(
            "INSERT INTO expense_approvers "
            "(account_key,approver_key,display_name,email,use_count,last_used) "
            "SELECT account_key,approver_key,display_name,email,use_count,last_used "
            "FROM expense_approvers_legacy"
        )
        conn.execute(
            "INSERT INTO expense_approver_events "
            "(account_key,context_id,approver_key,email,recorded_at) "
            "SELECT e.account_key,e.context_id,e.approver_key,a.email,e.recorded_at "
            "FROM expense_approver_events_legacy AS e "
            "JOIN expense_approvers_legacy AS a "
            "ON a.account_key=e.account_key AND a.approver_key=e.approver_key"
        )
        conn.execute("DROP TABLE expense_approver_events_legacy")
        conn.execute("DROP TABLE expense_approvers_legacy")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _data_dir() -> Path:
    # EPC_DATA_DIR wins over the mount so every test can point the whole module
    # at a tmp_path. The /test1 probe is is_dir(), not exists(): when the Render
    # disk is not attached the path is simply absent and the repo-local
    # data_store keeps local development working. A Render dashboard value can
    # shadow render.yaml for this variable -- confirm both during deployment.
    env = os.getenv("EPC_DATA_DIR")
    if env:
        return Path(env)
    mounted = Path("/test1")  # the Render persistent disk's mount path
    if mounted.is_dir():
        return mounted
    return Path(__file__).resolve().parent.parent / "data_store"


def _db_path() -> Path:
    # Creates the directory as a side effect, so callers must not invoke this
    # before their own validation. Every public function below rejects invalid
    # identity arguments BEFORE calling _connect(), which is what lets
    # tests assert that a rejected input leaves no database file behind at all.
    d = _data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "epc_memory.db"


def _connect() -> sqlite3.Connection | None:
    """Open (and initialize) the database; None if storage is unavailable.

    Returns an open connection the CALLER must close -- every public function
    below does so in a ``finally``. Returns None instead of raising when the
    disk is missing, read-only, full or corrupt (FM-G04), so learning degrades
    without touching the workflow.

    WAL is set per connection because there is no separate init step; the pragma
    is a no-op once the file is already in WAL mode.
    """
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(_db_path(), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _migrate_expense_approver_identity(conn)
        return conn
    except Exception:
        if conn is not None:
            conn.close()
        return None


def _norm_email(email: str | None) -> str:
    # Ends-only strip, deliberately NOT the whitespace collapse _norm_name does:
    # an address is stored as the operator confirmed it. The consequence is that
    # an interior newline or tab survives normalization AND survives
    # _looks_like_email below -- see the note there.
    return (email or "").strip().lower()


def _norm_name(name: str | None) -> str:
    # Collapses interior runs so "  Evan   Roden " and "Evan Roden" are one
    # person. This is the DISPLAY form that gets written back into the widget;
    # _requester_key is the comparison form.
    return " ".join((name or "").split())


def _requester_key(name: str | None) -> str:
    # casefold(), not lower(): this is a matching key for human names, and
    # app/expense_ui.py's _employee_name_key derives its own key the same way.
    # The two must stay equivalent or a remembered employee number stops pairing
    # with the name in the field -- silently, as a blank rather than an error.
    return _norm_name(name).casefold()


def _account_key(account: str | None) -> str:
    # Account/contract values come from contracts.contract_names(), so this
    # normally changes nothing. It exists so a re-exported contracts.json that
    # merely re-cases or re-spaces an account name does not orphan every
    # device-scoped row already learned under the old spelling.
    #
    # NOTE the asymmetry: the contract-scoped tables (admin_emails, contacts,
    # vendor_contacts) key on the RAW contract string instead, so they do not
    # get that protection. Do not "unify" it without migrating those rows.
    return " ".join((account or "").split()).casefold()


def _device_hash(device_token: str | None) -> str:
    # The raw browser token is NEVER persisted -- that is the privacy boundary
    # documented in the 2026-08-04 handoff, and tests assert the stored value is
    # a 64-character digest rather than the token.
    #
    # No format validation on purpose: device_identity.device_token() already
    # allow-lists the real cookie, and keeping this permissive is what lets the
    # tests drive the whole module with readable tokens like "browser-a". The
    # 200-character cap is only a guard against hashing an absurd input.
    token = (device_token or "").strip()
    if not token or len(token) > 200:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _norm_vendor(vendor: str | None) -> str:
    # The STORED key, punctuation intact: "acme mechanical, inc." is written to
    # vendor_contacts exactly like this. _vendor_match_key is a second, looser
    # key computed only at read time, so history is never rewritten by a change
    # to the suffix list below.
    return " ".join((vendor or "").split()).lower()


# Suffixes stripped only from the END of a vendor name, so "LP Gas Co" keeps its
# leading "LP". A name that is nothing but suffixes ("LP", "Limited") collapses
# to "" -- vendor_reps() guards on that explicitly, because an empty match key
# would otherwise equal the empty key of every other suffix-only vendor and hand
# one vendor's representatives to another.
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
    """Normalize punctuation and legal suffixes without fuzzy name guessing.

    Lets "Acme Mechanical, Inc." and "ACME Mechanical" resolve to the same
    representatives. It is intentionally NOT fuzzy: "Trane" and "Trane U.S.
    Inc." do not match, because the alternative is offering one vendor's contact
    for another's quote, which the operator has no reason to double-check.
    """
    # The findall drops every non-alphanumeric character, so "St. Mary's Supply"
    # and "St Marys Supply" agree. The loop pops repeatedly because real names
    # end in stacked suffixes ("Foo Services Co Inc").
    words = re.findall(r"[a-z0-9]+", _norm_vendor(vendor))
    while words and words[-1] in _LEGAL_VENDOR_SUFFIXES:
        words.pop()
    return " ".join(words)


def _looks_like_email(email: str) -> bool:
    """Cheap plausibility check before an address is worth remembering.

    NOT a validator, and deliberately weaker than the three real ones in this
    codebase (smartsheet._EMAIL_RE, workflow_review._EMAIL_RE and
    expense_report._looks_like_email, which all require a non-space run either
    side of the "@" and a dot in the domain).

    It accepts "@.", "a@b@c.d", and -- because it tests only for a literal
    SPACE, while _norm_email does not collapse interior whitespace -- an address
    carrying a newline or tab, which is exactly the shape a PDF-wrapped address
    arrives in. Those get stored and later prefilled, and the strict validator
    downstream then blocks the submission with no hint that memory is to blame.

    On the PO path this is a second gate only: web_ui teaches vendor contacts
    solely from a package that already passed validate_submission_fields.
    """
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
    unavailable (the app keeps working, it just doesn't learn).

    LEGACY, and the only writer of admin_emails/contacts. No production caller
    remains -- the active flow calls record_vendor_contact instead. Keep it: it
    also increments vendor_contacts, which vendor_reps() and therefore the live
    representative recall still read, so historical rows written by this
    function are still surfaced today (pinned by
    test_legacy_vendor_history_remains_available).

    Unlike record_vendor_contact this has NO context_id, so it counts once per
    call -- a Streamlit rerun would inflate it. That is the defect that made the
    event-keyed replacement necessary; do not re-wire this into the UI.
    """
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

    Returns the current use count, or 0 for invalid input or unavailable
    storage -- the caller cannot distinguish those, and does not need to.

    ``context_id`` carries the whole guarantee. It comes from
    po_context.vendor_contact_memory_context_id, which hashes the package with
    the vendor/contact/requester fields EXCLUDED, so correcting a
    representative on an otherwise identical package hits the same event row.
    Passing a per-rerun value here would restore the rerun inflation this
    design exists to prevent, and nothing would look wrong.

    ``contract`` is used RAW (not _account_key'd) because it is the primary key
    of this table's existing rows; see the note on _account_key.
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
        # BEGIN IMMEDIATE, not the implicit transaction: the read of the prior
        # event and the counter update that depends on it must not interleave
        # with another writer, or a correction can decrement a count that a
        # concurrent write already moved. Taking the write lock up front also
        # turns contention into the 5s busy timeout rather than a mid-flight
        # "database is locked". Every "BEGIN IMMEDIATE" block in this module
        # owns its own commit/rollback and must not be wrapped in "with conn".
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT vendor,name,email FROM vendor_contact_events "
            "WHERE contract=? AND context_id=?",
            (contract, context),
        ).fetchone()

        # Correction path. The decrement-then-delete pair is what makes a
        # corrected package stop teaching the WRONG representative: without it,
        # fixing a typo'd contact would leave both the wrong and the right pair
        # in vendor_reps(), and the wrong one would keep the higher count and so
        # keep winning remembered_vendor_contact(). The DELETE is guarded on
        # count<=0 so a pair still earned by OTHER packages survives.
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
            # Pure rerun of an already-recorded package: refresh recency only,
            # never the count. This is the branch that makes Streamlit's
            # constant re-execution harmless.
            #
            # UPDATE-only, so it cannot RECREATE a vendor_contacts row that went
            # missing while its event row survived; the count then reads 0
            # forever for this package. record_expense_approver was changed to
            # an upsert for exactly that reason -- see the
            # "..._recovers_if_its_directory_row_is_missing" test in
            # tests/test_expense_memory.py -- but this function,
            # record_device_account_manager and record_device_requester
            # were not.
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
    """Admin emails used >= SUGGEST_THRESHOLD times on THIS contract only.

    UNREFERENCED: no caller in app/, pages/, scripts/ or tests. Its only writer
    is record_send, which is itself no longer called in production, so it
    returns [] on any current deployment. Reported as a dead-code candidate
    rather than removed -- removal is a separate verified phase.
    """
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
    """(name, email) pairs used >= SUGGEST_THRESHOLD times on THIS contract.

    UNREFERENCED, same as suggest_admin_emails: no caller anywhere, and its only
    writer (record_send) is no longer called in production. The live equivalent
    is vendor_reps/remembered_vendor_contact, which are vendor-scoped and
    event-deduplicated. Dead-code candidate, not removed here.
    """
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
    threshold — a vendor rarely has more than a few reps).

    Ordered most-used then most-recent, de-duplicated on (name, email), and
    never crossing a contract boundary. Returns [] for an unknown contract or
    vendor and for unavailable storage -- the caller cannot tell those apart.

    Exact vendor spelling is tried FIRST and the suffix-normalized fallback runs
    only when it finds nothing. Reversing that would let history stored under
    "Acme Mechanical, Inc." and "Acme Mechanical LLC" -- genuinely different
    legal entities in some markets -- merge into one list.
    """
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
        # One SELECT for the whole contract, then filtered in Python, because
        # the fallback below has to compute _vendor_match_key over the STORED
        # spellings -- SQL cannot express it, and a per-vendor query would miss
        # every row whose stored name differs only by a legal suffix.
        exact = [row for row in rows if row[0] == vend]
        if exact:
            matched = exact
        else:
            match_key = _vendor_match_key(vend)
            # ``match_key and`` is not defensive noise. A vendor named only by a
            # legal suffix ("LP", "Limited") normalizes to "", and without this
            # guard "" would equal the key of every other suffix-only vendor and
            # return the wrong company's representatives -- confidently, with no
            # sign to the operator that the name did not really match.
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

    Returns ("", "") -- never a half pair -- when nothing is known. Name and
    email are ONE identity here, as they are in the expense approver recall:
    returning a remembered email beside a different name is the failure this
    shape prevents.
    """
    reps = vendor_reps(contract, vendor)
    if not reps:
        return "", ""
    wanted_email = _norm_email(contact_email)
    wanted_name = _requester_key(contact_name)
    # Email before name before frequency. An address is the near-unique
    # identifier, a name is not: two reps at one vendor can share a name, and
    # falling back to reps[0] on a name collision would attach the busier rep's
    # address to the person the quote actually names.
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

    Returns the current use count, or 0 for invalid input or unavailable
    storage. Callers ignore the number; it exists for the tests that pin the
    idempotency and correction behaviour.

    ONE ready package is enough -- there is no threshold here, unlike the legacy
    record_device_requester below. That reversal is deliberate (FM-C07): a
    shared browser is handled by "the latest verified user wins" rather than by
    making the first user earn a default over three packages.

    web_ui only calls this when the package passed ready + Smartsheet field
    validation + attachment preflight, so an abandoned or rejected draft never
    teaches a name. Loosening that gate is what would let a bad draft train the
    default for the next person on the same browser.
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
            # Rerun of an already-counted package. display_name is refreshed
            # even though manager_key is unchanged, so a capitalization fix
            # ("evan roden" -> "Evan Roden") reaches the prefill; the KEY is
            # casefolded, so that is not a new person.
            #
            # UPDATE-only: if the directory row were missing while its event row
            # survived, this silently restores nothing and the count stays 0.
            # See the matching note in record_vendor_contact.
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
    """Return the latest requester for this exact browser and account.

    "" when this browser has never completed a package for this account, when
    the cookie is absent, or when storage is unavailable -- the caller seeds a
    blank field either way and cannot distinguish them.

    ORDER BY last_used before use_count, deliberately inverted from what a
    "most trusted" ranking would do. On a shared tablet the person who last
    completed a package IS the likely next requester; ranking by use_count
    first would keep prefilling a departed colleague's name for months.
    """
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


# The single source of truth for the device_expense_profiles column list: it
# builds the INSERT columns, the ON CONFLICT assignments, the SELECT list, and
# the keys of the dict remembered_expense_profile() returns. Every name here
# MUST exist as a column in _SCHEMA under the same spelling.
#
# Adding a field is not a one-line change. There is no expense-profile migration,
# so on an existing deployment the new column will not exist, the SELECT raises,
# the except-branch returns {}, and ALL expense recall stops with no error --
# while a fresh tmp_path database makes every test pass. Read the _SCHEMA note.
#
# Order within the tuple is free (columns and placeholders are generated from
# it together), but it must stay consistent within a single call.
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

    Returns True only when both writes committed. False covers an absent
    cookie, an absent account, an over-long value, an implausible approver
    address, and unavailable storage -- indistinguishable to the caller, which
    ignores the result because a failed remember must never disturb a report the
    operator already has in hand.

    The exclusion list is a PRIVACY boundary, not an optimization: this table
    holds only what the operator would otherwise retype. Do not add a receipt,
    merchant, amount or signature field to _EXPENSE_PROFILE_FIELDS.

    Two rows are written -- the latest-profile row (one per device+account) and
    a per-employee row. The second exists because the first is overwritten by
    whoever files most recently, which used to hand the next employee the
    previous employee's number.
    """
    device = _device_hash(device_token)
    account_key = _account_key(account)
    if not device or not account_key:
        return False
    cleaned = {
        field: " ".join(str(values.get(field, "") or "").split())
        for field in _EXPENSE_PROFILE_FIELDS
    }
    # All-or-nothing: one over-long value abandons the WHOLE profile rather than
    # truncating it. A truncated employee number or job number would be written
    # back into the form on the next report and submitted as if confirmed.
    if any(len(value) > 240 for value in cleaned.values()):
        return False
    # Lowercased only for the check; the stored value keeps the operator's
    # casing, because it is redisplayed in the approver field rather than used
    # as a key. An EMPTY approver email is allowed through -- the field is
    # optional here and required by the report generator, not by memory.
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
    employee_name = cleaned["employee_name"]
    employee_number = cleaned["employee_number"]
    employee_key = _requester_key(employee_name)
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
            # Only a NAMED employee with a number earns a mapping row. Writing a
            # row keyed on "" would make every unnamed draft overwrite one
            # shared bucket, and remembered_expense_employee_number() would then
            # hand that number to the next employee who left the name blank.
            if employee_key and employee_number:
                conn.execute(
                    "INSERT INTO device_expense_employees "
                    "(device_hash,account_key,employee_key,employee_name,"
                    "employee_number,last_used) VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(device_hash,account_key,employee_key) DO UPDATE SET "
                    "employee_name=excluded.employee_name,"
                    "employee_number=excluded.employee_number,"
                    "last_used=excluded.last_used",
                    (
                        device,
                        account_key,
                        employee_key,
                        employee_name,
                        employee_number,
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
    """Return the latest expense defaults for this exact browser+account.

    Returns {} -- never a partially populated dict -- for an absent cookie or
    account, no stored row, or unavailable storage. expense_ui._seed_profile
    relies on that: it seeds through ``setdefault`` so a missing profile simply
    leaves the fields blank.

    Keys are exactly _EXPENSE_PROFILE_FIELDS and every value is a str. A schema
    drift makes this return {} silently rather than raising; see _SCHEMA.
    """
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


def remembered_expense_employee_number(
    device_token: str | None,
    account: str | None,
    employee_name: str | None,
) -> str:
    """Return the number confirmed for this employee/browser/account.

    Matching is exact after case and whitespace normalization. The legacy
    latest-profile row remains a fallback so existing deployments gain recall
    before their first report is generated with the new mapping table.

    Returns "" for an unknown employee, and expense_ui treats that as "clear the
    number field". Exact matching is the point: a fuzzy match would attach one
    employee's number to a similarly named colleague's reimbursement, and
    neither the operator nor the form would flag it.

    The legacy branch is NOT redundant with the mapping table. Every browser
    that filed a report before device_expense_employees existed has a profile
    row and no mapping row; deleting the fallback silently drops recall for
    those users until they file once more.
    """
    device = _device_hash(device_token)
    account_key = _account_key(account)
    employee_key = _requester_key(employee_name)
    if not device or not account_key or not employee_key:
        return ""
    conn = _connect()
    if conn is None:
        return ""
    try:
        row = conn.execute(
            "SELECT employee_number FROM device_expense_employees "
            "WHERE device_hash=? AND account_key=? AND employee_key=?",
            (device, account_key, employee_key),
        ).fetchone()
        if row:
            return str(row[0])

        legacy = conn.execute(
            "SELECT employee_name,employee_number FROM device_expense_profiles "
            "WHERE device_hash=? AND account_key=?",
            (device, account_key),
        ).fetchone()
        if legacy and _requester_key(str(legacy[0])) == employee_key:
            return str(legacy[1])
        return ""
    except Exception:
        return ""
    finally:
        conn.close()


def record_expense_approver(
    *,
    account: str | None,
    approver_name: str | None,
    approver_email: str | None,
    context_id: str | None,
) -> int:
    """Remember one confirmed expense approver for an exact account.

    Re-generating one in-progress report is idempotent. Correcting its approver
    moves that event to the corrected identity. Correcting an email on that
    same report replaces its older identity; two different people with the same
    normalized name and different emails remain distinct. Returns the current
    use count, or zero when validation/storage is unavailable.

    ACCOUNT-scoped, NOT device-scoped -- the only store here that is shared
    between browsers. That is the feature: an employee on a new phone can search
    an administrator their colleague already confirmed. Identity is the
    normalized name plus email, scoped to the account.

    An approver email is REQUIRED here (unlike in record_expense_profile): this
    directory exists to pair a name with an address, and a nameless or
    address-less entry would let expense_ui offer a name that blanks the email
    when selected.
    """
    account_key = _account_key(account)
    name = _norm_name(approver_name)
    approver_key = _requester_key(name)
    email = _norm_email(approver_email)
    context = (context_id or "").strip()
    if (
        not account_key
        or not approver_key
        or not _looks_like_email(email)
        or not context
        or len(account_key) > 240
        or len(name) > 160
        or len(email) > 240
        or len(context) > 200
    ):
        return 0

    conn = _connect()
    if conn is None:
        return 0
    now = time.time()
    current = (approver_key, email)
    try:
        conn.execute("BEGIN IMMEDIATE")
        prior = conn.execute(
            "SELECT approver_key,email FROM expense_approver_events "
            "WHERE account_key=? AND context_id=?",
            (account_key, context),
        ).fetchone()
        if prior and tuple(prior) != current:
            conn.execute(
                "UPDATE expense_approvers SET use_count=use_count-1 "
                "WHERE account_key=? AND approver_key=? AND email=?",
                (account_key, prior[0], prior[1]),
            )
            conn.execute(
                "DELETE FROM expense_approvers WHERE account_key=? "
                "AND approver_key=? AND email=? AND use_count<=0",
                (account_key, prior[0], prior[1]),
            )

        if not prior or tuple(prior) != current:
            conn.execute(
                "INSERT INTO expense_approver_events "
                "(account_key,context_id,approver_key,email,recorded_at) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(account_key,context_id) DO UPDATE SET "
                "approver_key=excluded.approver_key,"
                "email=excluded.email,"
                "recorded_at=excluded.recorded_at",
                (account_key, context, approver_key, email, now),
            )
            conn.execute(
                "INSERT INTO expense_approvers "
                "(account_key,approver_key,display_name,email,use_count,last_used) "
                "VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(account_key,approver_key,email) DO UPDATE SET "
                "display_name=excluded.display_name,"
                "use_count=use_count+1,last_used=excluded.last_used",
                (account_key, approver_key, name, email, now),
            )
        else:
            # Same approver, same report: an UPSERT, not the plain UPDATE its
            # three sibling functions use. Two reasons, both load-bearing.
            #
            # It RECOVERS a directory row that went missing while its event row
            # survived; a plain UPDATE would match nothing and this account
            # would never see that approver again, silently. Pinned by the
            # "..._recovers_if_its_directory_row_is_missing" test in
            # tests/test_expense_memory.py.
            #
            # It also re-applies the display spelling without touching use_count.
            conn.execute(
                "INSERT INTO expense_approvers "
                "(account_key,approver_key,display_name,email,use_count,last_used) "
                "VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(account_key,approver_key,email) DO UPDATE SET "
                "display_name=excluded.display_name,"
                "last_used=excluded.last_used",
                (account_key, approver_key, name, email, now),
            )

        row = conn.execute(
            "SELECT use_count FROM expense_approvers "
            "WHERE account_key=? AND approver_key=? AND email=?",
            (account_key, approver_key, email),
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


def expense_approvers(account: str | None) -> list[tuple[str, str]]:
    """Return confirmed approver name/email pairs for this account only.

    Only approvers CONFIRMED by a generated report appear. In particular the
    RRH administrator that _seed_profile fills from deployment configuration is
    absent until the first report is filed -- expense_ui compensates by
    prepending the current field value to its option list, and that compensation
    is required, not belt-and-braces.

    Ordering feeds a fuzzy-search selectbox: most-used, then most-recent, then
    NOCASE alphabetical so the list is stable rather than reshuffling between
    reruns for approvers with equal counts.
    """
    account_key = _account_key(account)
    if not account_key:
        return []
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT display_name,email FROM expense_approvers "
            "WHERE account_key=? AND use_count>=1 "
            "ORDER BY use_count DESC,last_used DESC,display_name COLLATE NOCASE",
            (account_key,),
        ).fetchall()
        return [(str(name), str(email)) for name, email in rows]
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

    LEGACY and DELIBERATELY UNWIRED. This is the original browser-wide,
    three-use requester memory; the active flow uses
    record_device_account_manager, which is scoped to device+account and
    remembers after one package. The reversal was intentional -- one manager's
    name must not become the default on a different ENFRA account -- and
    tests/test_smartsheet_handoff_entrypoint.py asserts that web_ui does NOT
    call this function. Reconnecting it would reintroduce the cross-account
    leak, and nothing in the UI would look wrong.

    Kept because the device_requesters rows on the production disk are still
    readable and the behaviour is regression-tested. Do not delete without a
    verified removal pass.
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
    """Most-recent requester with at least three distinct PO contexts.

    LEGACY reader for record_device_requester, browser-wide and NOT scoped to an
    account. Exercised only by tests/test_requester_memory.py; the active flow
    reads remembered_device_account_manager instead. Not dead in the removable
    sense -- it still documents and pins the superseded behaviour -- but it must
    not be reintroduced into the UI.
    """
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
    """Forget requester learning for this browser without affecting other memory.

    Clears BOTH legacy requester tables together. Deleting only the
    device_requesters rows would leave orphaned event rows, and a later
    re-record on one of those contexts would take the "already counted" branch
    and never rebuild the directory row.

    True means the statements ran, NOT that anything was deleted -- there is no
    "nothing to forget" signal. False means an absent token or unavailable
    storage.

    Touches only the legacy tables: device_account_managers,
    device_expense_profiles and the approver directory are untouched.

    The active UI exposes no forget control at all
    (tests/test_smartsheet_handoff_entrypoint.py asserts web_ui never names this
    function), because a shared browser is handled by latest-user-wins instead.
    Called only from tests today; keep it for operator support and for any
    future removal pass.
    """
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
