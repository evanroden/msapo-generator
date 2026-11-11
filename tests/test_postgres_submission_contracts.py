"""Offline PostgreSQL Smartsheet claim tests (no real PO or DB connections)."""
import json

import pytest

from app.postgres_submission_store import PostgresSubmissionStore
from app.smartsheet_store import SubmissionStoreError


class Cursor:
    def __init__(self, rows=(), rowcount=1):
        self.rows = iter(rows)
        self.rowcount = rowcount
        self.executions = []
        self.closed = False

    def execute(self, sql, params):
        self.executions.append((sql, params))

    def fetchone(self):
        return next(self.rows)

    def close(self):
        self.closed = True


class Connection:
    def __init__(self, rows=(), rowcount=1):
        self.cur = Cursor(rows, rowcount)
        self.committed = self.rolled_back = self.closed = False

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, error_type, exception, trace):
        self.committed = error_type is None
        self.rolled_back = error_type is not None

    def close(self):
        self.closed = True


def adapter(*rows, rowcount=1):
    connection = Connection(rows, rowcount)
    return PostgresSubmissionStore(lambda: connection), connection


def test_new_claim_is_committed_before_remote_write():
    store, conn = adapter(("key",))
    claim = store.claim("po-key")
    assert claim.allowed and claim.reason == "new" and claim.row_id is None
    assert claim.lease_token and len(claim.lease_token) == 32
    assert conn.committed and conn.closed and not conn.rolled_back
    sql, params = conn.cur.executions[0]
    assert "ON CONFLICT DO NOTHING RETURNING" in sql
    assert params[0] == "po-key" and params[-1] == 300


@pytest.mark.parametrize("state", ["creating", "uncertain"])
def test_expired_rowless_remote_attempt_blocks_duplicate_post(state):
    store, conn = adapter(None, (state, None, [], "remote outcome unknown", None, False))
    claim = store.claim("same-quote")
    assert not claim.allowed and claim.reason == "uncertain"
    assert claim.lease_token is None and claim.row_id is None
    assert len(conn.cur.executions) == 2
    assert "FOR UPDATE" in conn.cur.executions[1][0]


def test_complete_cannot_be_reclaimed_after_lease_expiry():
    store, _ = adapter(None, ("complete", "9007199254740993", ["a"], None, None, False))
    claim = store.claim("key")
    assert not claim.allowed and claim.reason == "complete"
    assert claim.row_id == "9007199254740993"
    assert claim.attached == frozenset({"a"})


def test_live_owner_blocks_attachment_race():
    store, conn = adapter(None, ("partial", "42", ["a"], None, "other-token", True))
    claim = store.claim("key")
    assert not claim.allowed and claim.reason == "in_progress"
    assert len(conn.cur.executions) == 2


def test_known_row_with_expired_lease_resumes_only_attachments():
    store, conn = adapter(None, ("uncertain", "9007199254740993", ["quote"], None, None, False))
    claim = store.claim("key", lease_seconds=10)
    assert claim.allowed and claim.reason == "resume"
    assert claim.row_id == "9007199254740993"
    assert claim.attached == frozenset({"quote"})
    assert conn.cur.executions[2][1][1] == 30


def test_failed_rowless_submission_is_retryable():
    store, _ = adapter(None, ("failed", None, [], "definite rejection", None, False))
    claim = store.claim("key")
    assert claim.allowed and claim.reason == "retry"


@pytest.mark.parametrize("invalid", ["not-json", {"not": "list"}, ["good", 1]])
def test_corrupt_attachment_proof_fails_closed(invalid):
    store, conn = adapter(None, ("partial", "42", invalid, None, None, False))
    with pytest.raises(SubmissionStoreError):
        store.claim("key")
    assert conn.rolled_back and not conn.committed


def test_mark_creating_is_lease_owned_and_committed_before_post():
    store, conn = adapter()
    store.mark_creating("key", "token")
    assert conn.committed
    sql, params = conn.cur.executions[0]
    assert "status = 'creating'" in sql
    assert "AND lease_token = %s" in sql
    assert "AND status = 'pending'" in sql
    assert params == ("key", "token")


def test_missing_or_expired_mark_creating_raises_before_post():
    store, conn = adapter(rowcount=0)
    with pytest.raises(SubmissionStoreError):
        store.mark_creating("key", "stale")
    assert conn.rolled_back and conn.closed


def test_renew_and_finish_fence_ownership_and_release_lease():
    store, conn = adapter()
    store.finish("key", "lease", "partial", "attachment pending")
    sql, params = conn.cur.executions[0]
    assert "lease_expires_at = NULL" in sql
    assert "AND lease_expires_at > NOW()" in sql
    assert params[:2] == ("partial", "attachment pending")
    store2, conn2 = adapter()
    store2.renew("key", "lease", lease_seconds=3)
    assert conn2.cur.executions[0][1][0] == 30
    with pytest.raises(ValueError):
        store2.finish("key", "lease", "pending")


def test_record_row_preserves_large_textual_remote_identity():
    store, conn = adapter()
    store.record_row("key", "token", 9007199254740993)
    sql, params = conn.cur.executions[0]
    assert "row_id = %s" in sql
    assert params[0] == "9007199254740993"


def test_attachment_update_is_serialized_and_preserves_existing_fingerprints():
    store, conn = adapter((["old"],))
    store.record_attachment("key", "lease", "new")
    assert "FOR UPDATE" in conn.cur.executions[0][0]
    assert "attached_json = %s::jsonb" in conn.cur.executions[1][0]
    assert json.loads(conn.cur.executions[1][1][0]) == ["new", "old"]


def test_exact_key_reconciliation_is_partial_never_complete():
    store, conn = adapter()
    store.reconcile_row("key", "9007199254740993")
    sql, params = conn.cur.executions[0]
    assert "ON CONFLICT (submission_key) DO UPDATE" in sql
    assert "status = 'partial'" in sql
    assert "attached_json = EXCLUDED" not in sql
    assert params == ("key", "9007199254740993")


def test_cleanup_retains_uncertain_and_partial_rows():
    store, conn = adapter()
    assert store.cleanup(retention_days=1) == 1
    sql, params = conn.cur.executions[0]
    assert "status IN ('complete', 'failed')" in sql
    assert "uncertain" not in sql and "partial" not in sql
    assert params == (30,)


def test_database_unavailable_never_looks_like_a_new_claim():
    def outage():
        raise OSError("database network down")
    with pytest.raises(SubmissionStoreError):
        PostgresSubmissionStore(outage).claim("key")


def test_record_row_must_not_replace_existing_different_remote_row():
    store, conn = adapter(rowcount=0)
    with pytest.raises(SubmissionStoreError):
        store.record_row("key", "lease", "different-id")
    assert conn.rolled_back and not conn.committed
    sql, params = conn.cur.executions[0]
    assert "AND (row_id IS NULL OR row_id = %s)" in sql
    assert params[0] == "different-id" and params[-1] == "different-id"


def test_attachment_requires_known_remote_row():
    store, conn = adapter(rowcount=1)
    store.record_attachment("key", "lease", "fingerprint")
    sql, params = conn.cur.executions[0]
    assert "AND row_id IS NOT NULL FOR UPDATE" in sql
    assert params == ("key", "lease")
