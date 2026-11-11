# A05/A09 — MSAPO persistence boundary and data crosswalk (App Service)

**Status: DRAFT / preparation only (2026-11-11).** This follows A01's
`docs/azure/MIGRATION_MANIFEST.md` on PR #849, source main
`57c5cd87e3e441dfea3cddbc666248f8e469d986`. A01 is not merged.
This branch must not be merged/deployed as an Azure cutover. No live data
was exported, copied, converted, or migrated. No ENFRA database, container,
tenant or approval was discovered in the connected repository.

**Decision requested from A05:** ENFRA-approved *transactional* database
(PostgreSQL Flexible Server candidate; Azure SQL Database alternative) and
approved durable original/artifact store (Blob candidate). PostgreSQL has
row-level transactional compare-and-swap, SQL JSONB, standard connections and
managed identity options. Azure SQL also supports the required transactions
but needs separately tested T-SQL migrations, locking/concurrency and driver
contracts. Neither is approved by this document. Azure Files alone is **not**
an accepted replacement for SQLite semantics, even with DELETE journal mode,
flock or one App Service instance. The historical
`docs/AZURE_MIGRATION.md` is for Container Apps, not App Service.

## 1. Authoritative source-of-truth inventory

All paths below are relative to `EPC_DATA_DIR`; current resolution in
`app/memory.py`: configured env var, then Render `/test1` mount, then
repository-local `data_store`. The QA testing context can redirect that
root. The Smartsheet store has its own matching root resolution, not the
Monthly QA context. Verify both independently.

| Source and owner | State and write semantics | Proposed durable destination |
|---|---|---|
| `epc_memory.db` — `app/memory.py` | SQLite, incremental per-contract/site/browser learning; tables `admin_emails`, `contacts`, `vendor_contacts`, `vendor_contact_events`, `device_requesters`, `device_requester_events`, `device_account_managers`, `device_account_manager_events`, `device_expense_profiles`, `device_expense_employees`, `expense_approvers`, `expense_approver_events`, `device_report_preparers`, `device_report_preferences`; schema migrations and legacy reads | A05-approved relational tables, every current exact key/count/routing column and identity hash retained; adapter NOT yet wired |
| `smartsheet_submissions.db` — `app/smartsheet_store.py` | SQLite `submissions` table keyed by exact submission fingerprint, lease/token, attached JSON, attempts, remote row ID as **text**, `uncertain` and attachment partial state. SQLite `BEGIN IMMEDIATE` + ownership checks prevent duplicate PO creation | PostgreSQL `epc_submission_claims` candidate; production adapter and real PostgreSQL concurrency tests are still blockers |
| `monthly_reports/library/<contract-hash>/<profile>/manifest.json` — `monthly_report_library.py` | Revisioned profile head, `history/*.json`, current slot assignments, audit records, per-slot versions, expected revision and `.write-lock` | `epc_record_heads` + immutable `epc_record_versions`; exact JSON bytes and revision numbers, database CAS |
| `monthly_reports/snapshots/<contract-hash>/<profile>/<period>.json` | Saved full drafts, omissions, open issues, entered editor, provenance, approved page and source decisions; `history/<period>-<revision>.json` | Scoped `snapshot` head + versions (never treat snapshots as disposable) |
| `monthly_reports/active_work/<browser-hash>/.../manifest` and assets — `monthly_report_active_work.py` | Unfinished per-browser, contract, profile, period state with revision, generation, recovery and tombstones | Per-user-scoped transactional active work + durable referenced objects; preserve explicit discard and stale-generation protections |
| `monthly_reports/library/.../sources/<sha256><suffix>` — `monthly_report_sources.py` | Original bytes and parser evidence; identity is SHA-256 and suffix, with stable ReportSource IDs, page references and site review | Immutable Blob original under an opaque scoped key, with original filename/suffix/source identity in authorized DB metadata |
| `monthly_reports/library/.../assets`, `imports` and compatibility/source-view receipts — `monthly_report_library.py` and `monthly_report_objects.py` | Content-addressed images and native DOCX, validated imported reviews, source-view replay and receipts; hard link dedupe, atomic publication | Blob immutable bytes + PostgreSQL version/receipt references; keep exact digest and source-view replay identity |
| `monthly_reports/directory/<contract-hash>/manifest.json` and `history` — `monthly_report_directory.py` | Contract/site contacts, aliases, archived state, provenance and independent `directory_locks` | Shared contract-scoped `directory` head + immutable versions with transaction/CAS |
| `monthly_reports/designs/master` and `designs/<contract-hash>` — `monthly_report_designs.py` | Master and approved contract design manifests/history, companion DOCX/PDF, metadata and hashes | `design_master` and `design_contract` record namespaces; binary designs to Blob, existing pins and IDs intact |
| `monthly_reports/org_chart_defaults/<contract-hash>` — `monthly_report_org_chart_defaults.py` | Contract-wide approved standing org charts, assets, history and revisioned manifest | `org_chart_defaults` record namespace + immutable Blob assets |
| Cover gallery/originals and shared source bundles — `monthly_report_cover_storage.py`, `monthly_report_cover_originals.py`, `monthly_report_shared_source_bundles.py` | Directory-FD protection, path scoping, exclusive creation, receipt checks and owner-only directory access; originals and approved reused artwork | Scoped object bytes + database receipts/authorization. This is a **caller rewrite**, not a path substitution |
| Fixture vault, admission, QA isolation — `monthly_report_fixture_vault.py`, `monthly_report_fixture_runs.py`, `monthly_report_testing.py` | Synthetic fixture evidence and private QA namespaces, generation/tombstone lifecycle, exclusive file create/rename, no-follow access, locks | Keep QA separate and isolated. A05/A09 must classify any approved private fixtures before deciding retention or migration |
| Other file-producing jobs — `app/config.py`, `app/pdf_converter.py`, `app/monthly_report_render_jobs.py`, `app/receipt_jobs.py`, document/receipt/expense paths | Output working directories, Streamlit downloads, LibreOffice conversion profiles and on-disk temporary files | Durable *final approved artifacts* only when explicitly saved; conversion workspaces and transient downloads remain ephemeral |

**Do not silently exclude** saved report imports, design metadata, source-view
receipts, approved standing charts, retained omission decisions or period-item
tombstones because their filenames resemble caches. Conversely, do not migrate
`monthly_report_preview_store.py`'s `TemporaryDirectory`, transient
thumbnail caches, scratch rendering, LibreOffice temporary profiles, local
content/metafile caches or regenerated preview PDF images as primary records.
Cache regeneration must check the durable original first.

## 2. Filesystem-operation contract audit

| Source implementation | Load-bearing operation | Managed-service treatment |
|---|---|---|
| `monthly_report_library._locked/_atomic_write` | `flock`, temp file, `fsync`, `os.replace`, directory `fsync` | Head CAS and version append in **one DB transaction**; no two-object/blob "atomic rename" assumption |
| `monthly_report_objects._publish_link/_store` | `os.link`, owner locks, immutable `chmod(0444)`, `os.replace` | Conditional immutable object create; repeated hash references, verify exact bytes, no hard links |
| `monthly_report_cover_storage` | `openat`/`dir_fd`, `O_NOFOLLOW`, `O_EXCL`, `fchmod`, `flock`, exclusive scratch dirs | Opaque storage keys + scoped authorizer + conditional writes; separate safe materialization to local temp for Pillow/Word |
| `monthly_report_active_work` | Saved draft assets, `flock`, replace, tombstone and unlink | Versioned active-work head; no unreviewed deletion of referenced originals |
| `monthly_report_directory`, `designs`, `org_chart_defaults` | Separate lock directories, multiple history/head writes | Transactional CAS with immutable version rows |
| `monthly_report_testing`, `fixture_vault` | `flock` on dirs, `os.rename`, `os.open(O_EXCL/O_NOFOLLOW)`, `shutil.rmtree` | Keep per-test local scratch; any durable vault implementation requires separate tenant/QA isolation |
| `smartsheet_store` | `BEGIN IMMEDIATE`, row/lease ownership, per-file attachment evidence, remote reconciliation | `SELECT ... FOR UPDATE` or guarded DML on the primary DB; never hold an open transaction across HTTP |
| `sqlite_storage` | `WAL` versus `DELETE` based on mountinfo | Neither mode establishes correctness on App Service shared storage |
| `scripts/migrate_data.py` | SQLite backup API, tar checksums, hard-link restoration, `os.replace` | A09 source **reader** only, after approval; target must be a logical transactional/object import with two-phase validation |
| `scripts/host_check.py` | `chmod(0600/0700)`, process locks, SQLite open/read, storage ownership | Historical POSIX host probe; add actual managed DB and Blob acceptance tests, not a green file-mount-only check |

Path-based libraries (PIL, PyMuPDF, python-docx, LibreOffice) may use
per-request, nonshared, permission-restricted temporary materialization **after**
checking a caller's authorization and Blob checksum. They must not receive a
Blob URL as though it were a `Path`. Upload outputs as immutable objects
before recording authoritative references. A failed transaction may leave an
unreferenced object; a periodic audited garbage collector may remove it only
after retention/reachability checks.

## 3. Target record and object mappings (A09 crosswalk contract)

`app/managed_persistence.py` is a candidate, **not wired into UI/Render**.
Each record key is `(namespace, contract, site, user_scope, record_id)`.
The columns preserve existing literal identities; never reconstruct an identity
from a display label, path slug or filename. Shared standing content has an
explicit empty user scope; browser-owned unfinished work keeps its existing
hashed device/user identity. A04/A05 must enforce authorization **before**
constructing these keys; the key alone is not an access-control mechanism.

| Legacy unit | Candidate record namespace / record ID | Source-to-target verification |
|---|---|---|
| One profile head + each `history/<revision>.json` | `profile` / existing profile key | Same contract, profile key, revision, asset refs, audit and exact SHA-256 |
| Saved period and all history | `snapshot` / profile key + period key (unambiguous encoded tuple, not slash parsing) | Same saved revisions, open issues, omissions, actor/editor and source provenance |
| Active work | `active_work` / existing profile and period tuple, user_scope=existing browser hash | Same generation, revision, bytes, asset refs, tombstone state |
| Contract directory | `directory` / original directory identity | Exact contract aliases, sites, contacts and provenance |
| Master/contract design | `design_master` / reserved shared scope; `design_contract` / original hash | Same default, version history, section order, companion PDF and DOCX hash |
| Org chart defaults | `org_chart_defaults` / original contract-wide identity | Same pins/history and original chart bytes |
| SHA-256 sources and assets | Immutable scoped Blob object | Same raw byte digest/length, original filename/suffix, source ID, page evidence |
| Smartsheet `submissions` | `epc_submission_claims.submission_key` unchanged | Same exact key, remote row ID **text**, attachments, lease/status, attempts, uncertain state |
| SQLite memory tables | Normalized managed tables, schema mapping **pending** | All 14 source table counts, unique identities, preference counters, role columns and device hashes |

The binary boundary `app/managed_blob_objects.py` uses a digest of
(namespace, contract, site, user_scope) in the Blob name rather than putting
customer/person names in object keys. It creates only if absent and reads back
SHA-256 and length; it never exposes a path/rename API. Any Blob authorization
and container tenancy strategy still requires A04/A05 review. Source/target
records must have a typed object reference with digest, size and scope.

The provisional SQL DDL is
`docs/azure/SCHEMA_POSTGRESQL_CANDIDATE.sql`. It includes `creating`
for the Smartsheet crash window described by pending PR #847. **Do not**
map an expired, row-less `creating` claim to `retry`; only confirmed
remote reconciliation by full submission key may recover it. Partial
attachments resume only on an identified remote row; a missing/corrupt
attachment list fails closed. Do not mark a verified row `complete` until
all attachments are checked. Reconcile with #830/#847 and P20 before wiring.

## 4. A05 authorization/compatibility gates

1. Written ENFRA choice of PostgreSQL **or** Azure SQL, Azure Blob **or**
   approved alternate; region, network access, identity, tenant, retention,
   backup/restore owner, key rotation, encryption, and RPO/RTO. No IDs or
   connection strings are to be committed to this public repository.
2. A04 provides authenticated subject, group/role authorization, contract/site
   and shared/individual standing-content rules. Backend calls must validate
   those scopes *before* reads and writes, not merely accept a caller-supplied
   `RecordKey`.
3. Finish adapters for `memory.py`'s 14 tables and Smartsheet's complete
   `SubmissionStore` API; prove claim collisions, lease fencing, row/attachment
   recovery and actual POST crash windows. Do not activate direct Smartsheet API
   submission; checked-in Render remains disabled.
4. Rewrite all authoritative Monthly JSON and file caller paths to a
   transactional head + typed immutable-object boundary. Test listing,
   historical restoration, old record ID, exact source, stale-generation/QA
   isolation, cross-user and cross-site denial and durable re-open.
5. Real PostgreSQL/Azure SQL transactional and Blob conditional-put/identity
   tests in an **approved isolated nonproduction environment**, including
   concurrent processes/instances, restore, permission failures, version
   conflicts and injected partial failures. Offline fake tests do not prove
   platform compatibility.
6. Redacted logs, scoped service roles, no history UPDATE/DELETE permissions,
   immutable retention, audited cleanup and DR backup validation.
7. Set final production selection only after all callers are migrated and
   A05/A09/P20 evidence passes. Render stays on its existing storage backend
   throughout preparation. Single App Service instance is not proof of safety.

## 5. A09 extraction/import handshake — no live migration

Prepare **read-only** source manifests with exact source path, class, scope,
existing record ID, revision, size and SHA-256. Snapshot SQLite using its
backup API rather than copying a live WAL sidecar, and verify integrity,
foreign keys/schema identity and per-table row counts. Preserve raw historical
JSON and file bytes. Sensitive fields, user hashes and identities must remain
in ENFRA-approved restricted evidence, not public PRs or logs.

For each staged import: validate scope/ID → upload immutable bytes with
conditional create and read-back hash → upsert provisional DB metadata →
write every historical revision in sequence → compare-and-swap latest head →
verify all references and source lineage → compare counts/digests and
contract/site/user crosswalk. Use a separate isolated database/container with
no user traffic. A failed import must be restartable without republishing
different bytes or discarding uncertain PO claims. Don't run legacy tar
`restore` against Blob or PostgreSQL paths.

A09 output: stable old→new logical-key mapping, files and table row counts,
revision coverage, SHA-256 crosswalk, unresolved source/asset list, dry-run
transaction/recovery results, backup and rollback instructions, and a signed
cutover freeze. A05 signs schema and authorization; P20 reconciles pending
feature PR heads before selecting any production source SHA.

## 6. Current evidence, test commands and blockers

Focused tests in `tests/test_managed_persistence_contracts.py` use a mocked
transactional connection and in-memory Blob client. Run:

```sh
python -m pytest -q tests/test_managed_persistence_contracts.py \
  tests/test_smartsheet_store.py tests/test_sqlite_storage.py
```

They exercise expected revision conflicts, same-transaction history writes,
exact-byte read validation, scoped references, corrupt object refusal and
ambiguous uploads. They **do not** prove PostgreSQL SQL correctness against
a live server, Azure Blob behavior, Azure App Service compatibility or
production acceptance. Separate real-service and journey tests are required.

Remaining hard blockers: ENFRA service and IAM approval; complete memory
schema mapping; native Smartsheet PostgreSQL adapter and #847 integration;
end-to-end Monthly path replacement including source importer, cover/gallery,
designs/standing content, active work and history; per-user/cross-contract
authorization; A09 dry-run importer/reconciliation; backup/restore and
multi-process failure-injection; served App Service acceptance. PR #26 remains
unmerged and is **not** being reused wholesale.
