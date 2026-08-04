import sqlite3

import pytest

from app.smartsheet_store import SubmissionStore, SubmissionStoreError


def _expire_lease(store: SubmissionStore, key: str) -> None:
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE submissions SET lease_expires_at = 0 WHERE submission_key = ?",
            (key,),
        )
        conn.commit()


def test_lease_blocks_concurrent_workers_before_and_after_row_creation(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "abc123"

    first = store.claim(key)
    second = store.claim(key)

    assert first.allowed and first.reason == "new" and first.lease_token
    assert not second.allowed and second.reason == "in_progress"

    store.record_row(key, first.lease_token, 987)
    still_blocked = store.claim(key)
    assert not still_blocked.allowed and still_blocked.reason == "in_progress"

    _expire_lease(store, key)
    resumed = store.claim(key)
    assert resumed.allowed and resumed.reason == "resume"
    assert resumed.row_id == "987"
    assert resumed.lease_token and resumed.lease_token != first.lease_token


def test_partial_row_resumes_without_reuploading_recorded_attachments(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "partial"
    claim = store.claim(key)
    assert claim.lease_token

    store.record_row(key, claim.lease_token, "row-1")
    store.record_attachment(key, claim.lease_token, "file-one")
    store.finish(key, claim.lease_token, "partial", "second file failed")

    resumed = store.claim(key)
    assert resumed.allowed and resumed.reason == "resume"
    assert resumed.attached == frozenset({"file-one"})
    assert resumed.lease_token

    store.record_attachment(key, resumed.lease_token, "file-two")
    store.finish(key, resumed.lease_token, "complete")
    duplicate = store.claim(key)

    assert not duplicate.allowed and duplicate.reason == "complete"
    assert duplicate.row_id == "row-1"
    assert duplicate.attached == frozenset({"file-one", "file-two"})


def test_ambiguous_creation_without_row_is_blocked_until_reconciled(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "uncertain"
    claim = store.claim(key)
    assert claim.lease_token

    store.finish(key, claim.lease_token, "uncertain", "request timed out")
    blocked = store.claim(key)

    assert not blocked.allowed
    assert blocked.reason == "uncertain"
    assert "timed out" in (blocked.last_error or "")

    store.reconcile_row(key, "row-verified")
    resumed = store.claim(key)
    assert resumed.allowed
    assert resumed.row_id == "row-verified"


def test_reconciliation_can_recover_after_local_database_loss(tmp_path):
    store = SubmissionStore(tmp_path / "new-submissions.db")
    store.reconcile_row("remote-key", "remote-row")

    record = store.get("remote-key")
    assert record is not None
    assert record["status"] == "partial"
    assert record["row_id"] == "remote-row"


def test_definite_failed_submission_without_row_can_retry(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "retry-me"
    first = store.claim(key)
    assert first.lease_token
    store.finish(key, first.lease_token, "failed", "validation rejected")

    retry = store.claim(key)
    assert retry.allowed and retry.reason == "retry"
    assert retry.row_id is None


def test_corrupt_attachment_history_fails_closed(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "corrupt"
    claim = store.claim(key)
    assert claim.lease_token
    store.finish(key, claim.lease_token, "partial")

    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE submissions SET attached_json = 'not-json' WHERE submission_key = ?",
            (key,),
        )
        conn.commit()

    with pytest.raises(SubmissionStoreError, match="corrupt"):
        store.claim(key)


def test_submission_record_and_retention_cleanup(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "inspect-me"
    claim = store.claim(key)
    assert claim.lease_token
    store.record_row(key, claim.lease_token, "row-1")
    store.record_attachment(key, claim.lease_token, "attachment-hash")
    store.finish(key, claim.lease_token, "complete")

    record = store.get(key)
    assert record is not None
    assert record["status"] == "complete"
    assert record["row_id"] == "row-1"
    assert record["attached"] == ["attachment-hash"]
    assert record["attempts"] == 1

    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE submissions SET updated_at = 0 WHERE submission_key = ?",
            (key,),
        )
        conn.commit()
    assert store.cleanup(retention_days=30) == 1
    assert store.get(key) is None
