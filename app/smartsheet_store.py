"""Persistent, fail-closed idempotency state for Smartsheet PO submissions.

A Smartsheet write is not transactionally coupled to local SQLite. The store
therefore records an ownership lease, the remote row ID, attachment fingerprints,
and an explicit ``uncertain`` state for writes whose remote outcome is unknown.
Only the lease owner may mutate a claimed submission.

Used exclusively by ``app.smartsheet.submit_po`` and
``app.smartsheet.reconcile_submission``. Nothing in the Streamlit UI touches it
directly.

The governing rule for every method here: when the state cannot be TRUSTED,
raise ``SubmissionStoreError`` rather than returning a benign-looking default.
An empty attachment list and an unreadable attachment list look identical to a
caller that treats errors as "nothing recorded yet" -- and the second one means
re-uploading files that are already on the row (FM-B06). Nothing in this module
may ever answer "no record" when it means "cannot tell".
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
    """The answer to "may I act on this submission, and what already exists?".

    ``allowed`` and ``lease_token`` move together: a token is issued only with
    permission, and every mutating method requires it. ``reason`` is what the
    caller branches on -- "new"/"resume"/"retry" when allowed, and
    "complete"/"uncertain"/"in_progress" when not; each of the three refusals
    needs a DIFFERENT operator message, which is why this is a reason string and
    not a bare bool.

    ``attached`` is the set of attachment fingerprints already uploaded, so a
    resume finishes the remaining files instead of re-sending all of them.
    """

    allowed: bool
    reason: str
    status: str
    row_id: str | None
    attached: frozenset[str]
    lease_token: str | None
    last_error: str | None = None


# "pending" is deliberately absent: it is the in-flight state and may only be
# set by claim(), never by finish(). Allowing finish(..., "pending") would let a
# worker release its lease while leaving the submission looking active forever.
_ALLOWED_FINAL_STATUSES = {"complete", "partial", "failed", "uncertain"}


class SubmissionStore:
    """SQLite-backed duplicate prevention for Smartsheet PO writes.

    One row per submission key. Concurrency is handled by an expiring ownership
    lease rather than by an open transaction, because the protected section
    spans several HTTP requests that can take minutes -- holding a SQLite write
    transaction across them would block every other request on the process.

    Construct with an explicit path in tests; production uses
    ``from_environment``.
    """

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def from_environment(cls) -> "SubmissionStore":
        """Locate the database on the deployment's persistent disk.

        EPC_DATA_DIR is set to the mounted Render disk in render.yaml. The
        fallback is CWD-relative and therefore EPHEMERAL: if that variable is
        ever removed from the dashboard, duplicate-prevention history silently
        starts over on every container restart while everything still appears to
        work. Note that ``app/memory.py`` resolves the same variable with an
        extra fallback to the mount path; the two are not interchangeable.
        """
        root = Path(os.getenv("EPC_DATA_DIR", "./data_store"))
        return cls(root / "smartsheet_submissions.db")

    def _connect(self) -> sqlite3.Connection:
        """Open the database, creating the directory, file and schema as needed.

        ``isolation_level=None`` puts the connection in autocommit mode so that
        the explicit ``BEGIN IMMEDIATE`` statements below actually control the
        transaction boundaries; with Python's default implicit handling, the
        driver would open its own transaction and the claim would no longer be
        atomic against a concurrent worker.

        WAL plus a 10s busy timeout is what lets a second Streamlit rerun wait
        rather than immediately fail with "database is locked".

        The ALTER TABLE block migrates databases created before leases existed.
        It is guarded by PRAGMA table_info rather than by try/except, so a
        genuine schema error still surfaces instead of being mistaken for
        "column already present".

        Raises SubmissionStoreError on any OS or SQLite failure -- callers must
        treat an unavailable store as a reason to block the submission, never as
        an empty one.
        """
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
        """Decode the attachment-fingerprint list, failing CLOSED on damage.

        The tempting simplification is ``json.loads(raw or "[]")`` inside a
        try/except that returns ``frozenset()``. That is the FM-B06 bug: a
        corrupt row would be read as "nothing attached yet" and the next resume
        would upload every file again, with no error anywhere. The shape check
        matters as much as the parse -- valid JSON that is not a list of strings
        is corruption too.
        """
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

        Refusal reasons, in the order they are tested -- the order is the policy:

        * ``complete``  -- already fully submitted; returns the known row ID so
          the caller can report success rather than an error.
        * ``uncertain`` -- a prior write's outcome is unknown AND no row ID was
          ever recorded. Blocked until ``reconcile_row`` supplies one. Testing
          this BEFORE the lease check is essential: an expired lease must not
          turn an unresolved ambiguous write into a fresh attempt.
        * ``in_progress`` -- another worker holds an unexpired lease. This still
          applies after the row exists (FM-F02): a second process must not start
          attaching to a row the first one is still working on.

        Otherwise the lease is taken and ``reason`` is ``resume`` (a row ID
        survives, finish its attachments) or ``retry`` (definitely failed before
        any row existed, safe to start over).

        The lease floor of 30 seconds prevents a caller from passing a tiny or
        negative ``lease_seconds`` and effectively disabling the lock.
        """
        now = time.time()
        token = uuid.uuid4().hex
        expires = now + max(30, int(lease_seconds))
        try:
            with self._connect() as conn:
                # BEGIN IMMEDIATE takes the write lock up front, so the
                # read-then-insert/update below cannot interleave with another
                # worker's identical sequence. A plain BEGIN (or SQLite's
                # deferred default) would let two concurrent submissions both
                # read "no row" and both be granted a claim -- two POs, one
                # quote (FM-F01).
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

                # "and not row_id" is load-bearing. An uncertain record that DOES
                # carry a row ID (FM-F05: the row was created, only the local
                # write of its ID failed) is resumable, because the ID identifies
                # the exact row to finish rather than a second one to create.
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
        """Apply an update only if this caller still owns the lease.

        The lease token in the WHERE clause is the entire concurrency guard:
        checking ownership with a separate SELECT would leave a window in which
        the lease expires between the check and the write.

        ``sql_fragment`` is interpolated into the statement, so it must remain a
        LITERAL supplied by this module -- every call site passes a hard-coded
        string and all runtime values go through ``params``. Never route a
        caller-supplied fragment here.

        Raises SubmissionStoreError when zero rows match, which means the lease
        expired or another worker took over; the caller must abort rather than
        continue writing to a submission it no longer owns.
        """
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
        """Extend this worker's lease. Raises if it has already been lost.

        Called between long HTTP operations. The raise is the useful part: it is
        how ``submit_po`` discovers mid-flight that another worker took over,
        before it uploads a file to a row it no longer owns.
        """
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
        """Persist the created remote row ID under the current lease.

        The single most important write in this module: until it succeeds, a
        crash leaves a row that exists remotely and is unknown locally. Its
        failure is reported by ``submit_po`` as ``uncertain`` with the row ID
        included, so an operator has the ID even though the database does not.

        The ID is stored as TEXT. Smartsheet row IDs exceed 2^53 and would lose
        precision as a JSON/float round trip; keeping them textual everywhere
        means the stored value always compares equal to the remote one.
        """
        self._owned_update(
            submission_key,
            lease_token,
            "row_id = ?, status = 'pending', last_error = NULL, updated_at = ?",
            (str(row_id), time.time()),
        )

    def record_attachment(
        self, submission_key: str, lease_token: str, fingerprint: str
    ) -> None:
        """Add one attachment fingerprint to the submission's recorded set.

        A read-modify-write rather than an ``_owned_update``, because the value
        is a JSON list rather than a scalar. That is why it needs its own
        BEGIN IMMEDIATE: without the write lock, two concurrent recordings would
        each read the old list and the second would erase the first's entry --
        which presents later as a file being uploaded twice.

        Both the SELECT and the UPDATE carry the lease token, so an expired
        lease raises instead of silently writing nothing.
        """
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
        """Record a terminal status and RELEASE the lease.

        Clearing ``lease_token``/``lease_expires_at`` is what makes the next
        claim's reason correct: a "partial" or "failed" record with a dangling
        lease would report ``in_progress`` to the operator's retry for the full
        lease window, for a worker that is already gone.

        Raises ValueError -- not SubmissionStoreError -- on an unknown status,
        because that is a programming error in the caller, not a storage fault,
        and it must not be swallowed by the store-failure handling in
        ``submit_po``.
        """
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

        Deliberately writes status ``partial``, never ``complete``: the remote
        lookup proves the ROW exists and says nothing about its attachments, so
        the next claim must resume and re-check them. Marking it complete here
        would leave a PO row permanently missing its quote with the system
        reporting success.

        It is also the ONE method with no lease check -- it is the recovery path
        for a database that may have been recreated from scratch, where no lease
        can exist. Clearing the lease columns can therefore evict a live worker;
        that worker's next ``renew`` raises and its submission fails closed,
        which is the intended outcome of a human intervening mid-flight.
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
        """Read-only inspection of one submission; ``None`` when no record.

        Diagnostic/test accessor -- ``submit_po`` uses ``claim`` instead, which
        is atomic. ``None`` here means "no such key", never "could not read":
        storage faults raise, and a corrupt attachment list still raises out of
        ``_decode_attached`` rather than being reported as an empty list.
        """
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
        """Delete old completed/failed records; retain partial/uncertain records.

        The status filter is the whole point and must not be widened: a
        ``partial`` record still names attachments that exist remotely, and an
        ``uncertain`` one is the only evidence that a possibly-created row needs
        reconciling. Deleting either turns a recoverable state into a duplicate.

        Retention is floored at 30 days, so a caller cannot accidentally prune
        the duplicate-prevention window down to nothing; the default of a year
        is how long a byte-identical resubmission is still recognised as one.
        """
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
