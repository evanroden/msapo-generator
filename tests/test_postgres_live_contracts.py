"""Synthetic PostgreSQL service contract tests, opt-in via MSAPO_TEST_PG_DSN.

Tests actual PostgreSQL transaction/CAS/row locks against an isolated schema.
No production identity, remote Smartsheet writes or Azure service access.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.managed_persistence import PostgresRecordStore, RecordKey, RevisionConflict
from app.postgres_submission_store import PostgresSubmissionStore
from app.smartsheet_store import SubmissionStoreError


@pytest.fixture(scope="module")
def postgres_factory():
    dsn = os.environ.get("MSAPO_TEST_PG_DSN")
    if not dsn:
        pytest.skip("No isolated PostgreSQL service configured.")
    psycopg = pytest.importorskip("psycopg")
    schema = "epc_ci_" + uuid.uuid4().hex[:14]
    ddl = (Path(__file__).resolve().parents[1] /
           "docs/azure/SCHEMA_POSTGRESQL_CANDIDATE.sql").read_text()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET search_path TO "{schema}"')
        connection.execute(ddl)

    def connect():
        return psycopg.connect(dsn, options=f"-c search_path={schema}")

    yield connect
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f'DROP SCHEMA "{schema}" CASCADE')


def test_transactional_heads_history_and_digest_are_preserved(postgres_factory):
    store = PostgresRecordStore(postgres_factory)
    key = RecordKey("snapshot", "Contract A", "UMMC", "browser-a", "2026-10")
    original = b'{"schema":1,"provenance":["source-1"],"omissions":["page-9"]}'
    first = store.write(key, original, expected_revision=0)
    assert first.revision == 1 and first.raw == original
    assert first.sha256 == hashlib.sha256(original).hexdigest()
    assert store.read(key) == first
    with pytest.raises(RevisionConflict):
        store.write(key, b'{"schema":1}', expected_revision=0)
    second = store.write(key, b'{"schema":1,"revision":2}', expected_revision=1)
    assert store.read(key).revision == 2
    assert store.read(key, revision=1) == first
    assert store.read(key, revision=2) == second
    assert store.list_record_ids(namespace="snapshot", contract="Contract A",
                                 site="UMMC", user_scope="browser-a") == ("2026-10",)
    assert store.read(RecordKey("snapshot", "Other Contract", "UMMC",
                                "browser-a", "2026-10")) is None


def test_two_writers_only_one_cas_wins(postgres_factory):
    store = PostgresRecordStore(postgres_factory)
    key = RecordKey("profile", "Contract A", "", "", "race")
    store.write(key, b'{"revision":1}', expected_revision=0)

    def update(value):
        try:
            store.write(key, ('{"writer":' + str(value) + '}').encode(),
                        expected_revision=1)
            return "won"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [1, 2]))
    assert sorted(results) == ["conflict", "won"]
    assert store.read(key).revision == 2
    with postgres_factory() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM epc_record_versions WHERE namespace = 'profile' "
            "AND contract = 'Contract A' AND record_id = 'race'"
        ).fetchone()[0]
    assert count == 2


def test_ambiguous_post_crash_state_never_reclaims_rowless_create(postgres_factory):
    store = PostgresSubmissionStore(postgres_factory)
    key = "smartsheet-crash-" + uuid.uuid4().hex
    claim = store.claim(key)
    assert claim.allowed and claim.reason == "new"
    store.mark_row_create_started(key, claim.lease_token)
    with postgres_factory() as conn:
        conn.execute("UPDATE epc_submission_claims "
                     "SET lease_expires_at = NOW() - INTERVAL '1 hour' "
                     "WHERE submission_key = %s", (key,))
    blocked = store.claim(key)
    assert not blocked.allowed and blocked.reason == "uncertain"
    assert blocked.status == "creating"
    store.reconcile_row(key, "9007199254740993")
    resumed = store.claim(key)
    assert resumed.allowed and resumed.reason == "resume"
    assert resumed.row_id == "9007199254740993"
    store.record_attachment(key, resumed.lease_token, "source-sha256")
    store.finish(key, resumed.lease_token, "complete")
    complete = store.claim(key)
    assert not complete.allowed and complete.reason == "complete"
    assert complete.attached == frozenset({"source-sha256"})


def test_concurrent_claims_have_single_lease_owner(postgres_factory):
    key = "smartsheet-concurrent-" + uuid.uuid4().hex

    def claim(_):
        return PostgresSubmissionStore(postgres_factory).claim(key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, [0, 1]))
    assert sum(1 for c in results if c.allowed) == 1
    assert sum(1 for c in results if c.reason == "in_progress") == 1


def test_malformed_stored_attachment_evidence_fails_closed(postgres_factory):
    store = PostgresSubmissionStore(postgres_factory)
    key = "smartsheet-corrupt-" + uuid.uuid4().hex
    claim = store.claim(key)
    with postgres_factory() as conn:
        conn.execute(
            "UPDATE epc_submission_claims SET attached_json = %s::jsonb "
            "WHERE submission_key = %s", ('["valid",42]', key),
        )
        conn.execute(
            "UPDATE epc_submission_claims SET lease_expires_at = NOW() - INTERVAL '1 hour' "
            "WHERE submission_key = %s", (key,),
        )
    with pytest.raises(SubmissionStoreError):
        store.claim(key)
