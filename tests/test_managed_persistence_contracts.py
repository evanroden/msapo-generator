"""Offline boundary checks; optional real-service tests remain A05 acceptance gates.

No PostgreSQL, Azure Blob, Smartsheet, Render or client connection is made.
"""
import hashlib
import json

import pytest

from app.managed_blob_objects import (
    AzureBlobObjects, BlobIntegrityError, BlobReference, BlobStoreUnavailable,
    ObjectScope,
)
from app.managed_persistence import (
    PostgresRecordStore, RecordIntegrityError, RecordKey, RevisionConflict,
)


class FakeCursor:
    def __init__(self, responses=()):
        self.responses = iter(responses)
        self.statements = []
        self.closed = False

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return next(self.responses)

    def fetchall(self):
        return next(self.responses)

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, responses=()):
        self.cursor_value = FakeCursor(responses)
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        self.rolled_back = kind is not None
        self.committed = kind is None

    def cursor(self):
        return self.cursor_value

    def close(self):
        self.closed = True


def key(**overrides):
    value = dict(namespace="snapshot", contract="A-001", site="um-mc",
                 user_scope="browser-hash", record_id="report-2026-10")
    value.update(overrides)
    return RecordKey(**value)


def test_scope_is_exact_and_identity_preserving():
    k = key(record_id="2026-10/a:b", contract="Contract & Co.")
    assert k.sql_values() == ("snapshot", "Contract & Co.", "um-mc", "browser-hash", "2026-10/a:b")
    with pytest.raises(ValueError):
        key(site="foreign\x00site")
    with pytest.raises(ValueError):
        key(contract="")
    with pytest.raises(ValueError):
        key(record_id="\n")
    assert key(user_scope="").user_scope == ""  # deliberately shared scope


def test_postgres_create_is_atomic_head_plus_immutable_version():
    connection = FakeConnection([(1,)])
    record = PostgresRecordStore(lambda: connection).write(
        key(), b'{"schema":1,"raw":"preserve"}', expected_revision=0
    )
    assert record.revision == 1
    assert record.sha256 == hashlib.sha256(record.raw).hexdigest()
    assert connection.committed and not connection.rolled_back and connection.closed
    head, history = connection.cursor_value.statements
    assert "ON CONFLICT DO NOTHING RETURNING revision" in head[0]
    assert "INSERT INTO epc_record_versions" in history[0]
    assert head[1][:5] == key().sql_values()
    assert history[1][:5] == key().sql_values()
    assert history[1][-2] == record.raw


def test_postgres_expected_revision_conflict_rolls_back_without_history():
    connection = FakeConnection([None])
    with pytest.raises(RevisionConflict):
        PostgresRecordStore(lambda: connection).write(
            key(), b'{"schema":1}', expected_revision=7
        )
    assert connection.rolled_back and not connection.committed and connection.closed
    assert len(connection.cursor_value.statements) == 1
    query, params = connection.cursor_value.statements[0]
    assert "AND revision = %s RETURNING revision" in query
    assert params[-1] == 7


def test_postgres_successful_cas_uses_exact_old_revision_and_history():
    connection = FakeConnection([(3,)])
    result = PostgresRecordStore(lambda: connection).write(
        key(), b'{"schema":1,"omission":"approved"}', expected_revision=2
    )
    assert result.revision == 3
    assert connection.committed
    assert "INSERT INTO epc_record_versions" in connection.cursor_value.statements[-1][0]


def test_postgres_does_not_silently_overwrite_unexpected_revision():
    connection = FakeConnection([(999,)])
    with pytest.raises(RecordIntegrityError):
        PostgresRecordStore(lambda: connection).write(key(), b"{}", expected_revision=1)
    assert connection.rolled_back
    assert len(connection.cursor_value.statements) == 1


def test_postgres_read_verified_bytes_and_exact_scope():
    raw = b'{"schema":1,"source":["x","y"]}'
    digest = hashlib.sha256(raw).hexdigest()
    connection = FakeConnection([(4, memoryview(raw), digest)])
    result = PostgresRecordStore(lambda: connection).read(key(), revision=4)
    assert result.raw == raw and result.revision == 4
    sql, params = connection.cursor_value.statements[0]
    assert "FROM epc_record_versions" in sql
    assert params == (*key().sql_values(), 4)


def test_postgres_corrupt_history_fails_closed():
    connection = FakeConnection([(1, b'{"bad":1}', "0" * 64)])
    with pytest.raises(RecordIntegrityError):
        PostgresRecordStore(lambda: connection).read(key())
    assert connection.closed


def test_postgres_missing_record_is_only_legitimate_empty_answer():
    connection = FakeConnection([None])
    assert PostgresRecordStore(lambda: connection).read(key()) is None
    assert connection.committed


def test_postgres_list_never_queries_all_contracts():
    connection = FakeConnection([[("report-a",), ("report-b",)]])
    names = PostgresRecordStore(lambda: connection).list_record_ids(
        namespace="snapshot", contract="A-001", site="um-mc", user_scope=""
    )
    assert names == ("report-a", "report-b")
    sql, params = connection.cursor_value.statements[0]
    assert "contract = %s AND site = %s AND user_scope = %s" in sql
    assert params == ("snapshot", "A-001", "um-mc", "")


def test_postgres_rejects_malformed_payload_before_opening_connection():
    def fail():
        raise AssertionError("Database must not be opened")
    adapter = PostgresRecordStore(fail)
    with pytest.raises(ValueError):
        adapter.write(key(), b"not json", expected_revision=0)
    with pytest.raises(ValueError):
        adapter.write(key(), b'["not an object"]', expected_revision=0)
    with pytest.raises(ValueError):
        adapter.write(key(), b"{}", expected_revision=-1)
    with pytest.raises(ValueError):
        adapter.write(key(), b"{}", expected_revision=True)


class AlreadyExists(Exception):
    error_code = "BlobAlreadyExists"


class AmbiguousUpload(Exception):
    error_code = "LeaseIdMismatchWithBlobOperation"


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket = bucket
        self.name = name

    def upload_blob(self, raw, *, overwrite, metadata):
        assert overwrite is False
        if self.name in self.bucket:
            raise AlreadyExists()
        self.bucket[self.name] = bytes(raw)
        assert metadata["sha256"] == hashlib.sha256(raw).hexdigest()
        assert metadata["length"] == str(len(raw))

    def download_blob(self):
        if self.name not in self.bucket:
            raise FileNotFoundError(self.name)
        return self

    def readall(self):
        return self.bucket[self.name]


class FakeContainer:
    def __init__(self):
        self.objects = {}

    def get_blob_client(self, name):
        return FakeBlob(self.objects, name)


def test_immutable_blob_roundtrip_and_same_scope_idempotency():
    client = FakeContainer()
    store = AzureBlobObjects(client)
    scope = ObjectScope("source", "RRH", "site-a")
    ref = store.put(scope, b"the exact original")
    assert store.put(scope, b"the exact original") == ref
    assert store.read(scope, ref) == b"the exact original"
    assert ref.key.startswith("v1/") and "RRH" not in ref.key
    assert len(client.objects) == 1


def test_blob_scope_prevents_cross_contract_or_user_references():
    store = AzureBlobObjects(FakeContainer())
    source = ObjectScope("source", "RRH", "site-a", "u1")
    ref = store.put(source, b"original")
    for foreign in (
        ObjectScope("source", "OTHER", "site-a", "u1"),
        ObjectScope("source", "RRH", "site-b", "u1"),
        ObjectScope("source", "RRH", "site-a", "u2"),
    ):
        with pytest.raises(BlobIntegrityError):
            store.read(foreign, ref)
    with pytest.raises(BlobIntegrityError):
        store.read(source, BlobReference("../escape", ref.sha256, ref.length, ref.scope_digest))


def test_blob_tamper_fails_closed_even_if_name_and_length_match():
    client = FakeContainer()
    store = AzureBlobObjects(client)
    scope = ObjectScope("report", "contract")
    ref = store.put(scope, b"abcdef")
    client.objects[ref.key] = b"ABCDEF"
    with pytest.raises(BlobIntegrityError):
        store.read(scope, ref)
    with pytest.raises(BlobIntegrityError):
        store.put(scope, b"abcdef")


def test_blob_missing_and_ambiguous_upload_are_not_empty_or_success():
    scope = ObjectScope("report", "contract")
    client = FakeContainer()
    store = AzureBlobObjects(client)
    ref = store.put(scope, b"abc")
    del client.objects[ref.key]
    with pytest.raises(BlobStoreUnavailable):
        store.read(scope, ref)

    class AmbiguousContainer(FakeContainer):
        def get_blob_client(self, name):
            class Broken(FakeBlob):
                def upload_blob(self, raw, *, overwrite, metadata):
                    self.bucket[self.name] = bytes(raw)  # Remote write might have landed
                    raise AmbiguousUpload()
            return Broken(self.objects, name)
    ambiguous = AmbiguousContainer()
    with pytest.raises(BlobStoreUnavailable):
        AzureBlobObjects(ambiguous).put(scope, b"abc")
    assert len(ambiguous.objects) == 1  # Retry must verify, never assume success.


def test_existing_render_backend_remains_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv("EPC_DATA_DIR", str(tmp_path))
    from app.smartsheet_store import SubmissionStore
    store = SubmissionStore.from_environment()
    assert isinstance(store, SubmissionStore)
    assert store.path == tmp_path / "smartsheet_submissions.db"
    assert not store.path.exists()  # No live database migration or side effects.
