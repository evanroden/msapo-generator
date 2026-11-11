# A09 — MSAPO Render → Azure data migration: offline preparation

**State (2026-11-11):** synthetic-only preparation; **not** approval to copy, export, replace or export production data, provision services or change DNS. A01 is draft PR #849. A03's selected durable storage/schema adapter is not approved or published in `main`. `scripts/azure_data_rehearsal.py` therefore implements only the existing POSIX/SQLite contract; it is **not** an Azure SQL/PostgreSQL/Blob importer. A managed-backend importer and associated logical-schema/relationship tests remain **blocked on A03**. No live data is needed to run these commands.

## Storage inventory and disposition

| Persisted state | Existing source | Target / treatment |
|---|---|---|
| PO/Expense learned contacts, vendor contacts/events, requester and account manager events, expense profiles/employees, approver identities/events, report preparers/preferences | `EPC_DATA_DIR/epc_memory.db` (`app/memory.py`) | Preserve SQLite file unchanged **only** if A03 approves and target passes locking tests. Otherwise relational row adapter must preserve keys, all columns, timestamps, migrations and uniqueness. |
| Smartsheet submission key/status/row ID, attachment fingerprints, lease tokens/expiry, attempts, error/reconciliation state | `EPC_DATA_DIR/smartsheet_submissions.db` (`app/smartsheet_store.py`) | Preserve all rows and durable attempt/lease state. Never clear uncertain/pending rows to force retry. Resolve unexpired claims before freeze, and reconcile any uncertain remote side effects without a second submission. |
| Monthly contract/site profiles, saved reports/snapshots, revision history, audit/provenance, originals/import receipts, reviewed sources, images, pooled hard-linked report objects | `EPC_DATA_DIR/monthly_reports/library`, `snapshots`, `objects` and related paths (`app/monthly_report_library.py`, `monthly_report_sources.py`, `monthly_report_objects.py`) | Preserve exact relative identifiers/bytes, modes, MTIMEs, history, pinned ownership and hard-link semantics or explicitly adapt object references. Read/reopen and regenerate Word/PDF. |
| Contract directories, contacts, site identities and aliases | `monthly_reports/directory` (`app/monthly_report_directory.py`) | Preserve originals and revisions; check current manifest against latest history. |
| Approved design references and reusable master chart/diagram/source, branding, cover, templates and shared testing references | `monthly_reports/designs` and other `monthly_reports` directories; `app/monthly_report_designs.py`, `monthly_report_cover_storage.py`, `monthly_report_shared_templates.py`, `monthly_report_shared_source_bundles.py`, `monthly_report_shared_fixtures.py` | Preserve every authoritative object. Shared testing shelves may be retention-restricted: do not silently omit without separately approved classification. |
| Server-side unfinished browser recovery journals and attached pictures | `monthly_reports/active_work` (`app/monthly_report_active_work.py`) | Preserve exact token-derived owner scope, fingerprint, period, generation and assets. Browser token continuity is **not guaranteed** when the origin changes. |
| Derived previews, image raster/cache, converter working files | Runtime and `monthly_reports` cache paths (`app/monthly_report_preview_store.py` and related modules) | Initial rehearsal archives **everything** in `EPC_DATA_DIR`; only a reviewed inventory may declare specific subtrees disposable, never rely on a name heuristic. |
| Browser-only unsaved Streamlit session state, unsubmitted forms, device cookies/local storage | Client browser / session process, not consistently in `EPC_DATA_DIR` | **Cannot be restored from server snapshot**. Require save/close user notice, documented browser context/origin handling, and active-work continuity tests before cutover. |
| Uploaded quote/receipt originals and generated PO/Expense handoff files | Check running implementation paths and runtime persistence; not all session files are durable | A09 must not label transient files durable. A10 must verify each original survives if the workflow promises persistence; no silent recreation/reanalysis. |

This list is an **application-code inventory**, not an assertion that Render's current disk contains each object. `migrate_data.py` includes every accessible file under the selected source root and refuses symlinks/unreadable entries. Its archive manifest contains actual paths, potentially sensitive names, and is **restricted**. Reconciliation output does not include document content or original file paths, except database **table/schema names**, which are code-defined and are not customer document content. Never publish the actual archive, raw manifest, freeze ticket or production reconciliation report to a public repository.

## Snapshot and restore guarantees

`migrate_data.py` independently backs up each SQLite database and copies filesystem assets. **This is not a cross-store consistent point in time while the app writes**. A09 requires an explicit out-of-band full write fence. A backup API alone does not satisfy M07/M08/M16. A write-freeze attestation is an operator statement and **does not automate or prove** ingress, worker, background-job or external submission fencing. The migration controller must additionally confirm no active writer/process/slot can access the source.

`azure_data_rehearsal.py` adds: a mandatory matching freeze attestation; before/after source metadata scans; refusal of skipped changing files; validation of duplicate archive members/manifest paths; archive SHA-256; full relative-file checksum, directory and hard-link checks; SQLite integrity, `foreign_key_check`, schema version/table row counts; a current-manifest/latest-history relationship check for Monthly library and directory records; atomic same-parent publishing of an entirely new target directory; idempotent exact-match re-import; and sanitized JSON reconciliation output. It never enables `--replace-existing`. Interrupted staging is removed and safely retried; already accepted **different** target data blocks import. Exact SQL/data byte equality is checked against the SQLite backup payload on first import; the original source database may differ physically due to SQLite's backup normalization.

**Important limits:** This tool does not replicate writes, detect a malicious concurrent writer that restores file metadata, create a distributed lock, translate backend schemas, recover from two simultaneously active applications, or implement asynchronous Smartsheet/AI side-effect compensation. Do not run the application against a staging directory while it is being imported. Any POSIX mount must prove atomic rename, lock semantics and retention of permission bits on that actual App Service/approved Azure mount before using this path. After the app begins writing to Azure, the imported baseline is no longer a valid equality target; capture a fresh fenced checkpoint and assess Azure change history before rollback.

## Fully synthetic local rehearsal

From a repository checkout on the chosen exact SHA with `pytest` installed:

```sh
python -m pytest -q tests/test_azure_data_rehearsal.py tests/test_migrate_data.py
```

For a synthetic fixture root (never production), create a `fence.json` **outside** the source:

```json
{"classification":"synthetic","writers_fenced":true,"change_id":"SYNTHETIC-ONLY","fenced_utc":"2026-11-11T18:00:00Z"}
```

```sh
python -m scripts.azure_data_rehearsal snapshot --source /tmp/msapo-synthetic-source --archive /tmp/msapo-synthetic.tar.gz --freeze-attestation /tmp/fence.json
python -m scripts.azure_data_rehearsal verify --archive /tmp/msapo-synthetic.tar.gz
python -m scripts.azure_data_rehearsal import-posix --archive /tmp/msapo-synthetic.tar.gz --target /tmp/msapo-synthetic-restored-NEW
python -m scripts.azure_data_rehearsal reconcile --archive /tmp/msapo-synthetic.tar.gz --target /tmp/msapo-synthetic-restored-NEW > /tmp/msapo-synthetic-reconciliation.json
# Deliberate idempotent replay: must report "already_imported".
python -m scripts.azure_data_rehearsal import-posix --archive /tmp/msapo-synthetic.tar.gz --target /tmp/msapo-synthetic-restored-NEW
```

The test suite covers: synthetic saved-report metadata/history reopen, an original PDF byte-for-byte check, retained hard links, contacts and pending submission keys, repeated import, write-fence rejection, source movement during export, a truncated transfer, interrupted restoration/clean replay, foreign accepted-target refusal, and target tampering detection. These are offline file-and-DB tests. **No claim of actual Word/PDF fidelity, rendered pages, Azure WebSocket behavior, storage mount semantics, or browser report recovery has been made.** A10 must complete those tests on the exact authenticated isolated candidate and include actual exported DOCX/PDF hashes and visual diffs.

## Cutover prerequisites, final delta and rollback

1. Obtain A01/P20 final release SHA and approved A03 store contracts, identifiers, schema mapping and data-owner decision; identify all writes under `EPC_DATA_DIR` and paths outside it. Register approved host, storage and release authority in a **restricted** change record. Select a final candidate image digest and identical tested runtime versions; audit active repairs before accepting the baseline.
2. On an actual isolated App Service target, verify /test1 persistent mount or managed adapter; permissions, `flock`/SQLite locks, atomic write/rename, DB reopen, encrypted backup/restore, single active writer and slot/scale-out fencing. Confirm the selected schema and `user_version`/table columns. For a managed database, A03 must supply and review the logical row-transformer, transaction boundaries, object mapping and restartable import protocol **before** the migration may proceed.
3. Rehearse with non-identifying synthetic datasets on both isolated hosts. Inject interrupted transfer, corrupt archive/object, missing source, repeated import, stale target, failed promotion and failed restore. Capture migration JSON, sanitized file/count/schema/relationship reconciliation, target host check, recovery logs and actual resumed/reopened DOCX/PDF browser evidence. Record duration/RPO/RTO and operators privately.
4. Before a final authoritative export, block new sign-ins/form submits, stop all Render app writers, background jobs and webhook paths, **drain or cancel in-flight external submissions safely**, block any other deployment/slot writer, and confirm a versioned write-fence token is enforceable across runtime and persistence. Do not rely solely on quiet traffic, the freeze JSON, or a read-only page. Drain/resolve active Smartsheet claims and reconcile uncertainty externally without duplicate submission. Preserve browser-saved unfinished work; warn users that browser-only unsaved work will not migrate.
5. **Final delta:** no online cross-store delta/CDC is implemented. Treat the *last* fenced snapshot as authoritative, reconcile it fully against a fresh isolated Azure target, and keep Render write-fenced until Azure promotion. If freeze duration exceeds the accepted outage budget, cutover is blocked pending an A03-approved ordered/transactional delta and cross-store watermark protocol; do not combine an old SQLite backup with later files. When a full baseline is pre-seeded, always reconcile/replace it through a **new, empty target** using the last fenced source. Never overwrite accepted Azure data.
6. Verify the final complete archive checksum via a trusted out-of-band digest, per-object checksum, counts, schema versions, relationships, exact source/report identities, preserved provenance/audits and original bytes. Reopen representative historical/current/unfinished reports; render and download Word and PDF; run authenticated native synthetic acceptance and Smartsheet disabled/dry-run tests. Do not switch DNS until documented go/no-go approvals.
7. Enable Azure writes **only after** verified promotion; keep Render fenced. Record the cutover boundary, immutable source snapshot and Azure starting checkpoint. Detect and audit every Azure-side write. **Rollback after Azure receives writes:** fence Azure, create and verify a new Azure checkpoint, reconcile/export the Azure-side delta/accepted Smartsheet state and either restore Azure to last known-good *with preserved new writes*, or forward migrate those writes onto a separately verified fallback host. Verify user-visible reports and external idempotency before routing traffic. **Never simply resume writes against stale Render.** If safe reverse migration is not proven, stay on isolated Azure and restore the service there.
8. Obtain signed restoration, data-owner, A10 functional QA, security, on-call and change-authority approval. Retain immutable baseline and post-cutover checkpoints within the approved retention window. Only then retire Render resources and its QA workflow under a separately approved change.

## Evidence state

At document creation: **CODE PREPARED / LOCAL SOURCE SYNTAX VALIDATED**. Synthetic unit/integration tests and actual Azure storage/export/render browser rehearsals must be reported from real runs with exact commit SHA/digest and run links. No production export, transfer, backup, or restore was performed.

