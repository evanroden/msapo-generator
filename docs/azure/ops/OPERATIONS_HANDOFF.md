# MSAPO on Azure App Service: A11 operations handoff

Status: **PROPOSED / no ENFRA signoff / no production activation**. Date: 2026-11-11.
Source baseline: main SHA 57c5cd87e3e441dfea3cddbc666248f8e469d986; architecture A01 draft PR #849, docs/azure/MIGRATION_MANIFEST.md on its branch. The user's requested A03 storage contract is **not yet published/confirmed in this repository**; A01's own proposed workstream mapping names A03 as platform/IaC and A05 as storage, so reconcile agent IDs before acceptance. **PLATFORM BLOCKER:** Microsoft App Service Linux mount guidance explicitly says not to use custom storage mounts for local databases such as SQLite or components relying on file handles and locks. The A01 conditional single-instance Azure Files + SQLite fallback is therefore NOT an accepted production recommendation, even if shallow host checks pass. Favor an ENFRA-approved managed transactional database (PostgreSQL or Azure SQL after adapter/schema review) and separately backed-up original/artifact object storage. Azure Files may be evaluated for eligible non-database file uses only. See https://learn.microsoft.com/en-us/azure/app-service/configure-connect-to-azure-storage This document is NOT evidence that Azure resources exist.

## 1. Service profile and ownership matrix

- Product: Monthly, Purchase Order (PO), and Expense; Streamlit Python 3.12; Linux App Service custom container on port 8501; /_stcore/health checks process HTTP, **not persistence readiness**. Keep exactly one writable active instance until database/file concurrency, session and slot overlap are proven.
- Workload baseline: Ubuntu 24.04 + LibreOffice Writer/Calc 24.2-compatible renderer and explicit fonts; current requirements.lock pinned; About reads APP_GIT_COMMIT when not on Render. The release identity is source SHA + immutable container image digest + environment/slot. A display string alone does not verify image provenance.
- Data: reports/history, uploaded originals/sources, reusable designs/charts/templates, contract/site directories, approvals, browser recovery records if server-persisted, epc_memory.db, smartsheet_submissions.db, generated retained deliverables and external submission reconciliation state. Browser-only unsaved drafts are NOT protected by server backups.
- Source of truth: A01/P20 release coordinator owns accepted production SHA; A03/A05 own approved storage schema; data custodian owns retention/restore; infrastructure may not override application-level idempotency.

| Responsibility | Proposed accountable role | Backup/approval role | ENFRA name and contact |
|---|---|---|---|
| Business priority, acceptable outage/data loss | MSAPO business owner | ENFRA change authority | TBD |
| Azure App Service, ACR, DNS, managed identity and network | Azure platform/SRE | Network + IAM security | TBD |
| Python/Streamlit, renderer, telemetry instrumentation, builds | Application engineering | P20 release coordinator | TBD |
| SQL durability or Azure Files safety and file/object backups | DBA + storage lead | Data steward | TBD |
| Smartsheet reconciliation, approval routing and attachment state | PO/integration owner | Business owner | TBD |
| AI availability, endpoints, quota and data policy | AI integration/governance owner | Security/data owner | TBD |
| Backup policy, isolated restore, disaster recovery | Backup custodian | DBA + business owner | TBD |
| Vulnerability/secret incident and audit policy | Security incident lead | ENFRA IAM | TBD |
| Alerts/rotation/severity/acknowledgement | SRE/on-call lead | Business owner | TBD |

Do not wire an Azure Monitor action group until the named primary/backup, business-hours versus 24/7 schedule, contact channels, escalation policy, ownership acceptance and test acknowledgement are recorded in a restricted ENFRA change record. The role in alert-spec.json is the **proposed recipient**, not a configured destination.

## 2. What is monitored, by whom, and what happens

Legend: **CODE** means current source supports observation or failure mode; **TEMPLATE** means a disabled alert/KQL definition exists here; **NOT TESTED** means no Azure ingestion, route or live workload test has occurred.

| Signal | Proposed alert/cadence | Proposed recipient and first response | State |
|---|---|---|---|
| Process startup/health and 5xx | App Service HealthCheckStatus and Http5xx, plus startup_failed; evaluate 5m with 15m lookback; health threshold evaluated after service's unhealthy period | Platform/SRE: correlate with deployed digest, startup log class, auth/port 8501; rollback to proven digest if recent deployment | CODE+TEMPLATE; Azure NOT TESTED |
| Exceptions and failed saves | Sanitized AppExceptions count, save_failed/commit_failed >0 in 15m | Application+DBA: stop unsafe writes, retain draft and compare revision/store state | TEMPLATE |
| Readiness to save/generate | Separate allowlisted readiness_blocked event when database, original store, locks, permissions, quota, template integrity or renderer dependency prevents safe operation | SRE+DBA: block affected operation; never infer READY from HTTP 200 | TEMPLATE |
| DB and file/object availability | database_unavailable, database_write_failed, file_store_unavailable, object_storage_unavailable, source_integrity_failed | DBA/storage: prevent commits/submissions until store continuity and provenance checked | TEMPLATE |
| Writer/Calc conversions | conversion_failed/timeout/invalid_pdf; p50/p95 duration in 30m buckets; initial p95 90,000 ms is only a tuning hypothesis | Renderer owner: check conversion-slot wait, resource pressure, temp filesystem and artifact checksum | CODE+TEMPLATE, baseline NOT MEASURED |
| Memory, CPU and temp/disk | App Service MemoryWorkingSet in bytes; plan CPU; private memory/OOM restart; explicit temp_pressure/disk_pressure event. Set thresholds only after SKU/quota known | Platform: inspect RSS/working set, LibreOffice concurrency, temp free bytes; do not auto-scale stateful SQLite writers | TEMPLATE |
| AI errors and 429 | ai_429 and ai_unavailable event counts only, no request/response or prompt | AI owner: check quota/egress/provider state, hold draft, retry boundedly and manually where necessary | TEMPLATE |
| External submission uncertainty | submission_uncertain or submission_state_untrusted: any event is Sev1 | PO owner: **do not retry** until remote row/attachments and local leases are reconciled | CODE+TEMPLATE |
| Backup/restore evidence and pipeline gaps | backup_failed, backup_overdue, restore_check_failed; independent telemetry-heartbeat silence check after native instrumentation exists | Backup custodian or SRE: verify last good protected cross-store recovery point | TEMPLATE |

Startup health is a shallow liveness signal. A protected/read-only readiness probe must separately prove that the selected transactional backend is reachable, journal/schema/lease health is acceptable, originals/artifact storage is reachable, output/temp space is sufficient, required renderer/font files are present, and dependency settings are internally valid. Run actual synthetic save/generate/reopen/read-back against an isolated test contract in authenticated non-production, **not from anonymous /_stcore/health** and never with client data. A synthetically successful isolated write is not a proof of real contract/site authorization.

## 3. Privacy-safe telemetry contract and dashboards

Templates: alert-spec.json; dashboard-queries.kql; log-alert.template.bicep; metric-alert.template.bicep. **Both Bicep examples default deployRule=false and enableAlert=false**, and were NOT deployed. KQL expects workspace-based App Insights AppEvents, which current main does **not** emit; instrument it in a separately reviewed application PR before creating production rules. App Service platform metrics require no application-level traces but must be verified on chosen SKU.

Emit only: timestamp, synthetic/random operation-scoped UUIDv4 correlation_id, safe event code and fixed outcome, workflow enum (monthly/po/expense/system), runtime full SHA, verified image digest, bounded duration_ms, coarse backend kind and fixed reason_code. No contract/site/report/source IDs, names, personal contact details, document fields, file paths/names, quotes/receipts, free-form exceptions, prompts, tokens, private links, URIs, query strings, raw stdout/stderr, or remote row/attachment identifiers. Do not hash low-entropy personal values as a workaround.

Use a new correlation ID for each operation; attach it to internal spans without serializing payloads. A synthetic probe must use an explicitly marked operation. Log sampling/filters, App Insights automatic dependency/request collection, stack traces, App Service HTTP access logging, and outbound SDK logging must be privacy-reviewed: ordinary HTTP tracing can include URLs/query strings and exception messages. Default-deny collection of unreviewed fields. Redact **at emission**; post-ingestion deletion is not sufficient. Restrict read access, diagnostic exports, retention and cross-workspace sharing as approved by ENFRA. Log a reason-code class rather than catching and printing an exception object.

**Known source logging hazard:** app/pdf_converter.py currently logs LibreOffice stdout/stderr when conversion fails. These strings can include filenames and source-derived content. Replace this with a coarse exit category/errno and private safe correlation ID BEFORE enabling log forwarding. app/memory.py documents silent failure swallowing; add internal failure counters without changing its graceful-degrade behavior, distinguishing optional learning from critical save safety. Smartsheet store errors must continue to fail closed.

Recommended dashboard tiles: (1) active build digest, safe startup and readiness, (2) save success/fail by workflow and error class, (3) storage availability/backup recency, (4) conversion p50/p95/failures, (5) app/plan CPU/RSS and scratch free space, (6) AI 429/unavailable counts, (7) submission uncertainty/lease reconciliation, (8) telemetry ingestion gaps and cost GB/day. Dashboard queries must never project full Properties or raw exception text.

## 4. Backups, recovery points, and retention

**NOT CONFIRMED:** retention duration, location, redundancy, backup frequency, approved database, approved file store, protection tier, and named restore authority. Azure PostgreSQL flexible-server automatic point-in-time backups (if selected) have platform retention limits, but the ENFRA retention choice remains TBD. Azure Files/Blob versioning or snapshots need explicit backup policy and separate restore tests. Microsoft's App Service backup feature **excludes custom-mounted storage**, and mounted Azure Files is not a supported substitute for managed relational storage for SQLite; a web-app backup is not a sufficient data-recovery plan. App Service Linux custom storage uses storage account shared-access keys for mounts, not direct Entra RBAC; account-key controls and rotation must be included if mounted files are approved. App Service config, Key Vault references, registry tags/digests, IaC and authorization assignments require reproducible configuration backup; a database dump does not restore these.

Backup coverage matrix (all authoritative items MUST have a mapped mechanism):
- Transactional records: report revisions/history, identity and provenance, contract/site entitlements, consent/approval markers, Smartsheet submission claims/leases/remote IDs/fingerprints, learned contacts and preferences. **DB PITR or an application-consistent SQLite backup**.
- Authoritative objects: uploaded originals with hash, saved master/templates/designs, approved reusable images/charts, rendered retained outputs, attachments, import source archives. **Versioned object backup or verified snapshot/export**, restoring original identities and bytes.
- Operational configuration: source SHA/image digest, immutable release artifact in ACR, Entra/app/service/RBAC config, App Service settings and storage mappings, certificate/DNS/network paths, selected dependency versions. **IaC/config inventory/secret-reference recovery** (never export actual secret values into GitHub).
- Browser-only unfinished work: **not server backed**. User/browser recovery needs explicit export/communication procedure; do not promise server DR protects it.

Cross-store recovery point requirement: pause all write paths including background jobs/secondary slots and externally triggered submissions, record a monotonic cutoff/watermark, copy or snapshot ALL stores for that cutoff, verify SHA256/record counts/relations and store the manifest separately. Existing scripts/migrate_data.py backs up SQLite files individually and exports files while traversal is in progress; it does **not** prove an atomic whole-application snapshot during concurrent writes. Do not use live per-DB backups as evidence of consistent source/report history.

**Proposed, NOT committed targets for ENFRA to decide:**
- Higher-availability option: RPO no more than 1 hour, RTO no more than 4 hours, **conditional** on demonstrated cross-store backup cadence, tested restore throughput, approved staff coverage and submission reconciliation. Neither is currently achievable/verified by evidence.
- Lower-cost/business-hours alternative: RPO up to 24 hours, RTO within the next business day. Also requires a business owner acceptance of potentially unrecoverable work.
- Retention fields: operational restore window = TBD days; off-site/geo copy = TBD; long-term archive = TBD; legal hold = TBD; deletion = TBD; synthetic restore cadence = proposed quarterly, approval TBD.

**Isolated restore test (never against live production):**
1. Preflight: verify restore authority, release/image digest, tenant and contract isolation; create an empty isolated target with no live external credentials, routes or DNS.
2. Choose one matched DB+file checkpoint and corresponding application schema/image. Validate index manifest, SHA256, object version/checkpoint, record counts, timestamps, parent-child relations and all submission keys.
3. Restore database and original objects in correct order with network egress to Smartsheet and AI disabled. For SQLite use file permissions/locks/journal and PRAGMA integrity_check; for managed SQL use service PITR plus schema/integrity checks. Never overwrite populated targets accidentally.
4. Reopen the restored application with a synthetic identity and run save/reopen/generate and export on synthetic Monthly/PO/Expense data; verify source byte hashes, document page order and PDF integrity. Reconcile uncertain submissions **without causing new external rows**.
5. Record start/end timestamps, last committed recovery point, elapsed restoration, achieved RPO/RTO, schema/image identifiers, discrepancies and reviewer. Destroy isolated copies under policy after evidence is recorded. Do not place private content in evidence.
6. If mismatch, hold recovery/cutover, quarantine target, preserve last-good backups and escalate to DBA/data owner.

## 5. Incident runbooks

### A. Failed deployment / bad startup

Trigger: startup_failure, HealthCheckStatus unhealthy, 5xx spike or failed authenticated smoke. Platform on-call owns triage. Compare source SHA, registry image digest, App Service configured digest, port/health/Entra boundary and recent app settings or secret reference changes. Preserve logs with safe correlation IDs. Stop further promotion. Roll back to **previously tested immutable digest** with its compatible schema and configuration ONLY after checking database migration backward compatibility; if DB schema is incompatible, require an approved forward repair/restore plan rather than blindly rolling back. Verify process health, authorization, safe-readiness, one writer, synthetic save/reopen, Word/PDF and error rates before reopening traffic. Record deployment/rollback evidence; P20 remains the release owner.

### B. Database, Azure Files or object-store loss/corruption

Trigger: readiness_blocked, database_unavailable, source_integrity_failed, backup gap or duplicate-prevention state inaccessible. Put app into a supported read-only/maintenance gate and **block unsafe saves, generation and external submission**; do not create a fresh empty fallback store or coerce a journal mode. Check storage permissions, mount path /test1 if selected, quota, locks, network/private DNS, managed identity and schema versions. Preserve a forensic copy and current snapshots. Select last matched checkpoint; verify hashes and restore to empty isolated target. If original content or submission reconciliation is incomplete, do not switch production. After validation, restore one writer only and observe synthetic save/generate/reopen and duplicate prevention. Inform business owner of measured data gap; do not assert target RPO/RTO unless achieved.

### C. DOCX/PDF/LibreOffice conversion failure

Trigger: timeout, invalid PDF, failed conversion, unusually high p95 or temp/memory pressure. Preserve the accepted draft and original DOCX, retry only after determining failure class. Verify conversion slot, time budget, temp free space, fontconfig/font packages, LibreOffice version, scratch permissions, OS exit class and resource/OOM counters. Never log the document, path, stdout or stderr into central telemetry. Compare against pinned known-good renderer with synthetic geometry fixtures; roll back image if renderer/font drift is confirmed and schema permits. Confirm generated PDF magic, page count/order/geometry, tables, captions, grayscale, signature fonts and cleansed intermediates. Do not switch to unqualified conversion backend or reduce fidelity to conceal failure.

### D. AI unavailable/throttled

Trigger: ai_429/ai_unavailable or auth/connectivity failures. Check approved endpoint, network/proxy/CA, credential reference validity and bounded retry budget without printing prompts/tokens. Keep user draft and original upload intact. Show truthful manual/retry path; do not silently use a different AI provider, unapproved gateway or synthetic facts. A provider timeout must not become a completed extraction. Re-enable AI only after synthetic provider-fake validation and authorized isolated endpoint smoke. For partially completed PO/Expense/Monthly work preserve existing approval gates.

### E. Smartsheet outcome uncertain

Trigger: submission_uncertain or submission_state_untrusted. Block automatic resubmission. Confirm the local key/lease, last acknowledged remote row and uploaded attachment fingerprints from controlled stores. Reconcile with approved external destination using an authorized operator. Only then resume missing attachments under the same idempotency identity. Escalate unresolved states to PO owner; no live test sends in preparation.

## 6. Capacity and cost acceptance

No Azure region, confirmed SKU, approved network pattern or ENFRA budget was found in A01 or any available A03 storage submission. An A01 **benchmark candidate** of approximately 2 vCPU/8 GiB (P1v3 class) is not a confirmed subscription choice or authorized purchase. **No legitimate regional total can be calculated yet.** The companion monthly-cost-model.csv includes all expense drivers with blank region/SKU/rates. Use the selected region + SKU, contract discounts/commitments, capacity observations and the official Azure calculator before signing a number.

Collect per environment on the **same immutable image** and synthetic fixtures: cold start / warm restart, 1/2/3 concurrent authenticated users and tabs, 512 MiB upload ingress feasibility (do not assume), Monthly AUTH01/02/03 synthetic stand-ins, PO with multi-attachment retry, Expense PDF/Excel, full Word/PDF conversion wall time p50/p95/p99, request latency, CPU/RSS/high water, LibreOffice peak concurrent RSS, scratch disk bytes/free%, storage operations and queue waits, AI calls/tokens/429 (counts only), ACR image size, retained-source GB growth and Log Analytics GB/day. Use authentic private originals only in authorized isolated acceptance; do not copy them to public CI. Size for upload+renderer peak, not idle memory. Log measurement date, source SHA, digest, region, SKU, concurrency and confidence.

Cost categories per environment: App Service plan instance-hours + slots/extra instances, ACR SKU/storage/tasks, managed DB compute/storage/IO/backup/replication OR Azure Files capacity/transactions/snapshots, Blob capacity/requests/tiering/versioning/replication, Log Analytics ingestion/retention/query/alert rules and App Insights, networking (private endpoints, VNet/NAT/Firewall/WAF/DNS/egress), Key Vault operations, backup vault protected instances/storage/restore egress, cross-region transfer and test/staging idle resources. Avoid double counting included capacity; retain monthly baseline and p95 scenario. Check cost alerts separately from failure alerts.

## 7. Dependency and renderer maintenance

Monthly review by application engineering + security, cadence approval TBD: inventory operating-system CVEs, Python requirements.lock hashes/versions, Anthropic SDK protocol, Azure SDK compatibility, Streamlit/front-end patches, fontconfig, LO Writer/Calc and App Service image provenance. Build exact digest in an isolated staging branch; regenerate lock intentionally; record package/dependency inventory and font file names/versions (no binary font redistribution). Compare against last accepted synthetic and authorized private masters in Monthly/PO/Expense. Assert page count/order, dimensions, line wrapping, charts, grayscale, embedded images, table row breaks and headings, signatures, attachment inclusion, editable DOCX and PDF pixels. Test timeouts/memory/upload/locking and old-format restore. Reject pixel/page/font regression unless documented and business-approved. No auto-update of production renderer, base image or fonts, even for a security patch, without emergency change controls and signed fidelity result. Coordinate merge with P20 exact-head release gates; canary/rollback must use compatible schema.

## 8. Verification ledger and release gates

**Code inspected:** main Dockerfile, requirements.lock, .streamlit/config.toml, render.yaml, scripts/host_check.py, scripts/migrate_data.py, app/sqlite_storage.py, app/memory.py, app/smartsheet_store.py, app/pdf_converter.py and A01 draft PR #849. A03 or A05 approved region/SKU/storage and target Azure environment not observed. Mandatory storage design review includes the Microsoft App Service Linux prohibition on local databases over custom mounts and the exclusion of those mounts from App Service backups. **Synthetic contract-only validation:** duplicate IDs, all alerts disabled, specific save-failure routing and forbidden-key check were run against alert-spec.json before publication; no Azure resources were created. KQL executed in Log Analytics: **NOT TESTED**. Bicep compilation by Azure CLI: **NOT TESTED**. Native Azure App Service telemetry and actual alert delivery: **NOT TESTED**. Backups/restore and capacity/cost: **NOT TESTED**.

Before A11 accepted, require: selected A03 architecture; ENFRA named owner+alternate for each Sev1/Sev2; approved retention/RPO/RTO; approved actual region/SKU and budget; instrumented safe events; Bicep lint/what-if in a nonproduction subscription; synthetic injection proving every alert and its corresponding no-alert control; acknowledged action-group routes; cross-store restore from one coordinated checkpoint; correlated build digest and authenticated save/reopen/Word/PDF; budgeted measured capacity; privacy audit of ingress and exception logs. Never infer completion of A10 acceptance from an A11 documentation PR.

No paid resources, live restore, email/Smartsheet submissions, changed alert routes, approval, merge, release, or production cutover are part of this document.
