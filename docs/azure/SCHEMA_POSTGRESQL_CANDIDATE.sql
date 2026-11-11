-- PROPOSED A05 schema: PostgreSQL only. NOT approved/provisioned/applied.
-- Apply through an ENFRA-reviewed migration identity; the runtime must not run DDL.
-- Exact legacy contract/site/user/record IDs are stored as values, never path slugs.
-- Privilege separation: app may SELECT/INSERT heads/versions, UPDATE heads,
-- but must not UPDATE/DELETE historical versions. Enforce via GRANT/REVOKE
-- and an ENFRA-controlled migration/backup owner before production.
BEGIN;

CREATE TABLE IF NOT EXISTS epc_record_heads (
    namespace TEXT NOT NULL,
    contract TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    user_scope TEXT NOT NULL DEFAULT '',
    record_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 1),
    payload_bytes BYTEA NOT NULL CHECK (octet_length(payload_bytes) <= 67108864),
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, contract, site, user_scope, record_id)
);

CREATE TABLE IF NOT EXISTS epc_record_versions (
    namespace TEXT NOT NULL,
    contract TEXT NOT NULL,
    site TEXT NOT NULL DEFAULT '',
    user_scope TEXT NOT NULL DEFAULT '',
    record_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision >= 1),
    payload_bytes BYTEA NOT NULL CHECK (octet_length(payload_bytes) <= 67108864),
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[a-f0-9]{64}$'),
    saved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (namespace, contract, site, user_scope, record_id, revision),
    FOREIGN KEY (namespace, contract, site, user_scope, record_id)
        REFERENCES epc_record_heads (namespace, contract, site, user_scope, record_id)
        ON DELETE RESTRICT
);

-- PostgreSQL replacement candidate for Smartsheet's SQLite submissions table.
-- Never convert 'creating' with no row_id to a new claim after lease expiry:
-- a remote row-create POST may already have succeeded. The exact-key remote
-- reconciliation path is required before an unknown result can resume.
CREATE TABLE IF NOT EXISTS epc_submission_claims (
    submission_key TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'creating', 'complete', 'partial', 'failed', 'uncertain')
    ),
    row_id TEXT,
    attached_json JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(attached_json) = 'array'),
    last_error TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    attempts BIGINT NOT NULL DEFAULT 0 CHECK (attempts >= 0)
);
CREATE INDEX IF NOT EXISTS epc_submission_claims_retention
    ON epc_submission_claims (updated_at)
    WHERE status IN ('complete', 'failed');

-- Authoritative objects must be uploaded and read-back verified before their
-- references are published by a successful record CAS transaction. Orphans
-- from unsuccessful CAS are harmless and require reviewed garbage collection;
-- missing/corrupt objects are NOT silently skipped.
CREATE TABLE IF NOT EXISTS epc_object_receipts (
    scope_digest TEXT NOT NULL CHECK (scope_digest ~ '^[a-f0-9]{64}$'),
    object_key TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    content_length BIGINT NOT NULL CHECK (content_length >= 0),
    content_class TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scope_digest, object_key)
);

COMMIT;
