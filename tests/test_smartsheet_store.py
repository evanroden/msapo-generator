from app.smartsheet_store import SubmissionStore


def test_submission_store_blocks_concurrent_duplicate_and_resumes_partial_row(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "abc123"

    first = store.claim(key)
    second = store.claim(key)

    assert first.allowed and first.reason == "new"
    assert not second.allowed and second.reason == "in_progress"

    store.record_row(key, 987)
    resumed = store.claim(key)

    assert resumed.allowed and resumed.reason == "resume"
    assert resumed.row_id == "987"

    store.record_attachment(key, "file-one")
    store.finish(key, "partial", "second file failed")
    resumed_again = store.claim(key)

    assert resumed_again.allowed and resumed_again.reason == "resume"
    assert resumed_again.attached == frozenset({"file-one"})

    store.record_attachment(key, "file-two")
    store.finish(key, "complete")
    duplicate = store.claim(key)

    assert not duplicate.allowed and duplicate.reason == "complete"
    assert duplicate.row_id == "987"
    assert duplicate.attached == frozenset({"file-one", "file-two"})


def test_failed_submission_without_row_can_be_retried(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "retry-me"

    assert store.claim(key).allowed
    store.finish(key, "failed", "network error")

    retry = store.claim(key)

    assert retry.allowed
    assert retry.reason == "retry"
    assert retry.row_id is None


def test_submission_record_can_be_inspected(tmp_path):
    store = SubmissionStore(tmp_path / "submissions.db")
    key = "inspect-me"

    store.claim(key)
    store.record_row(key, "row-1")
    store.record_attachment(key, "attachment-hash")
    store.finish(key, "complete")

    record = store.get(key)

    assert record is not None
    assert record["status"] == "complete"
    assert record["row_id"] == "row-1"
    assert record["attached"] == ["attachment-hash"]
    assert record["last_error"] is None
